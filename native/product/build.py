#!/usr/bin/env python3
"""Build only. Never copies/launches/patches an Editor or modifies its settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source"
ELF_SHA = "d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec"


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor-source", type=Path, help="Optional exact Unity ELF for read-only guard verification")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    if output != output.resolve() or output.exists() or output.is_symlink():
        parser.error("A fresh canonical output is required.")
    profile = json.loads((HERE / "compatibility.json").read_text())
    if profile["original_sha256"] != ELF_SHA or profile["original_guards_verified"] != 59:
        parser.error("Unsupported committed compatibility profile")
    for rel, expected in profile["guard_source_sha256"].items():
        if digest(SOURCE / rel) != expected:
            parser.error("Frozen guard source changed: " + rel)
    original = None
    if args.editor_source:
        original = args.editor_source.resolve(strict=True)
        if digest(original) != ELF_SHA:
            parser.error("Unsupported Unity ELF; exact 6000.3.27f2 required")
        elf = original.read_bytes()
        phoff = struct.unpack_from("<Q", elf, 32)[0]
        ents, count = struct.unpack_from("<HH", elf, 54)
        segments = []
        for i in range(count):
            kind, _flags, offset, va, _pa, size, _mem, _align = struct.unpack_from("<IIQQQQQQ", elf, phoff + i * ents)
            if kind == 1: segments.append((va, size, offset))
        def native(va, size):
            for start, length, offset in segments:
                if start <= va and va + size <= start + length:
                    return elf[offset + va - start:offset + va - start + size]
            raise ValueError("Unmapped native guard: " + hex(va))
    verified = 0
    for rel in profile["guard_source_sha256"]:
        text = (SOURCE / rel).read_text()
        for address, length, data in re.findall(r'\{(?:"[^"]+",)?(0x[0-9a-f]+),(\d+),\{([^}]+)\}', text):
            values = bytes(int(v.strip(), 0) for v in data.split(",") if v.strip())
            if len(values) != int(length) or (original and native(int(address, 16), int(length)) != values):
                raise ValueError("Original byte guard mismatch: " + rel + " " + address)
            verified += 1
    if verified != 59: raise ValueError("Expected all 59 original byte guards")
    for item in [*profile["input_contexts"], profile["queued_repaint"]]:
        if original and native(int(item["address"],16),len(bytes.fromhex(item["bytes"]))) != bytes.fromhex(item["bytes"]):
            raise ValueError("Compatibility context mismatch")
    build = output.parent / (output.name + ".build")
    build.mkdir(parents=True, exist_ok=False)
    contexts = []
    for item in profile["input_contexts"]:
        data = bytes.fromhex(item["bytes"])
        contexts.append("{%s,%d,{%s}}," % (item["address"], len(data), ",".join(hex(x) for x in data)))
    (build / "input-contexts.generated.h").write_text("\n".join(contexts) + "\n")
    files = [
        "boot.c", "wrappers.generated.c", "trampolines.generated.c", "gpu-gates.generated.S",
        "rendering/scope_adapter.c", "geometry/geometry.c", "geometry/prepare.c", "geometry/extras.c",
        "content_geometry/accepted_content.c", "content_geometry/unity_adapter.c", "main_geometry/main.c",
        "input/input.c", "product/product_policy.c", "product/activation.c", "product/environment.c", "startup.cpp", "review/scopes.cpp", "rendering/render_boundary.cpp", "rendering/accepted_repaint.cpp", "geometry/birth.cpp",
    ]
    flags = ["-O2", "-fPIC", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
             "-I" + str(build), "-I" + str(SOURCE), "-I" + str(SOURCE / "deps"), "-I" + str(SOURCE / "geometry")]
    gtk = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "gtk+-3.0"], text=True))
    libraries = shlex.split(subprocess.check_output(["pkg-config", "--libs", "gtk+-3.0"], text=True))
    # Packaging provides PIC static json-c/OpenSSL archives here; local developer
    # builds may use pkg-config dynamic dependencies, recorded in build.json.
    dep_flags = shlex.split(os.environ.get("STATIC_DEPS_CFLAGS", subprocess.check_output(["pkg-config", "--cflags", "json-c", "openssl"], text=True)))
    dep_libs = shlex.split(os.environ.get("STATIC_DEPS_LIBS", subprocess.check_output(["pkg-config", "--libs", "json-c", "libcrypto"], text=True)))
    objects, commands = [], []
    source_pins = {str(p.relative_to(SOURCE)): digest(p) for p in SOURCE.rglob("*") if p.is_file()}
    for name in files:
        obj = build / (name.replace("/", "_") + ".o")
        cpp = name.endswith(".cpp")
        cmd = ["c++" if cpp else "cc", *(["-std=c++17"] if cpp else [] if name.endswith(".S") else ["-std=gnu11"]),
               *flags, *gtk, *dep_flags, "-c", str(SOURCE / name), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        objects.append(str(obj))
        commands.append(cmd)
    cmd = ["c++", "-shared", "-Wl,-z,defs,-z,relro,-z,now,--exclude-libs,ALL", *objects, *libraries, *dep_libs,
           "-ldl", "-pthread", "-lm", "-o", str(output)]
    subprocess.run(cmd, check=True)
    commands.append(cmd)
    if source_pins != {str(p.relative_to(SOURCE)): digest(p) for p in SOURCE.rglob("*") if p.is_file()}:
        raise RuntimeError("Source changed during build.")
    wrapper = output.parent / "wrapper-v2"
    if wrapper.exists(): raise ValueError("Fresh sibling wrapper-v2 required")
    cmd = ["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
           "-I" + str(HERE.parent), *dep_flags, str(HERE.parent / "launcher.c"),
           str(SOURCE / "product/product_policy.c"), str(SOURCE / "product/activation.c"),
           *dep_libs, "-lm", "-Wl,-z,relro,-z,now", "-o", str(wrapper)]
    subprocess.run(cmd, check=True); commands.append(cmd)
    manifest = dict(schema=2, constructor_contract="product-profile-v2", original_sha256=ELF_SHA,
                    files={"wrapper-v2":digest(wrapper), "native-v2.so":digest(output)})
    (output.parent / "manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    result = dict(abi=2, library=str(output), library_sha256=digest(output), constructor_contract="product-profile-v2",
                  host_environment_abi=1, restore_host_on_refusal=True, original_sha256=ELF_SHA,
                  compatibility_sha256=digest(HERE / "compatibility.json"), original_guards_verified=verified,
                  optional_original_verified=bool(original), input_context_guards=4, source_hashes=source_pins, commands=commands,
                  static_dependencies=bool(os.environ.get("STATIC_DEPS_LIBS")),
                  canonical_factor="float(percent/100.0) widened to double everywhere", parsed_percent_range=[100, 200],
                  queued_repaint_api_guard='0x3b335f0:16', accepted_allocation_repaint=True,
                  runtime_verified_percentages=[], Unity_run=False, production_applied=False, presented=False)
    (build / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("library", "library_sha256", "original_guards_verified", "Unity_run")}))


if __name__ == "__main__":
    main()
