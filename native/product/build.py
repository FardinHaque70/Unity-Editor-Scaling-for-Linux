#!/usr/bin/env python3
"""Build only. Never copies/launches/patches an Editor or modifies its settings."""
import argparse
import hashlib
import json
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
    parser.add_argument("--editor-source", type=Path, required=True)
    parser.add_argument("--target-exe", type=Path, required=True)
    parser.add_argument("--public-editor", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = args.editor_source.resolve(strict=True)
    target = args.target_exe.absolute()
    public = args.public_editor.absolute()
    settings = args.settings.absolute()
    output = args.output.absolute()
    if (target != target.resolve() or public != public.resolve() or not public.is_file() or
            settings != settings.resolve() or not settings.is_absolute() or target == public or
            output != output.resolve() or output.is_symlink() or output in (original, target, public, settings) or output.exists()):
        parser.error("Canonical target/public/settings paths, a distinct target and fresh canonical output are required.")
    if target.exists() and (target.samefile(public) or digest(target) != ELF_SHA):
        parser.error("Target must be the distinct preserved original-byte ELF, never the public launcher inode.")
    if settings.exists() and (settings.is_symlink() or not settings.is_file()):
        parser.error("Settings must be a regular canonical file or not yet present.")
    if digest(original) != ELF_SHA:
        parser.error("Unsupported Unity ELF; only exact 6000.3.27f2 is supported by this candidate.")
    elf = original.read_bytes()
    if elf[:4] != b"\x7fELF" or elf[4:6] != b"\x02\x01":
        parser.error("Expected little-endian ELF64.")
    phoff = struct.unpack_from("<Q", elf, 32)[0]
    ents, count = struct.unpack_from("<HH", elf, 54)
    segments = []
    for i in range(count):
        kind, _flags, offset, va, _pa, size, _mem, _align = struct.unpack_from("<IIQQQQQQ", elf, phoff + i * ents)
        if kind == 1:
            segments.append((va, size, offset))

    def native(va, size):
        for start, length, offset in segments:
            if start <= va and va + size <= start + length:
                return elf[offset + va - start:offset + va - start + size]
        raise ValueError("Unmapped native guard: " + hex(va))

    repaint_guard = bytes.fromhex('53 31 c0 48 85 f6 74 28 48 8b 5f 60 48 85 db 74')
    if native(0x3b335f0, len(repaint_guard)) != repaint_guard:
        raise ValueError('Original queued-repaint API guard mismatch')

    # Guards inherited from exact frozen source, verified against full-SHA source.
    verified = 0
    for rel in ("geometry/guards.h", "main_geometry/patches.generated.h", "main_geometry/contexts.generated.h",
                "input/guards.generated.h", "geometry/extras.generated.h", "rendering/entry_guards.h"):
        text = (SOURCE / rel).read_text()
        pattern = r'\{(?:"[^"]+",)?(0x[0-9a-f]+),(\d+),\{([^}]+)\}'
        for address, length, data in re.findall(pattern, text):
            values = bytes(int(v.strip(), 0) for v in data.split(",") if v.strip())
            size = int(length)
            if len(values) != size or native(int(address, 16), size) != values:
                raise ValueError("Original byte guard mismatch: " + rel + " " + address)
            verified += 1

    build = output.parent / (output.name + ".build")
    build.mkdir(parents=True, exist_ok=False)
    config = ("#define V6_ELF " + json.dumps(str(target)) + "\n#define V6_SHA " + json.dumps(ELF_SHA) +
              "\n#define NS_PUBLIC_EDITOR " + json.dumps(str(public)) + "\n#define NS_SETTINGS_FILE " + json.dumps(str(settings)) + "\n")
    (build / "config.generated.h").write_text(config)
    contexts = []
    for va, size in ((0x3C008E0, 0x9E), (0x3C00C80, 0xAA), (0x3BC4DD0, 16), (0x3BC5020, 16)):
        data = native(va, size)
        contexts.append("{%s,%d,{%s}}," % (hex(va), size, ",".join(hex(x) for x in data)))
    (build / "input-contexts.generated.h").write_text("\n".join(contexts) + "\n")
    files = [
        "boot.c", "wrappers.generated.c", "trampolines.generated.c", "gpu-gates.generated.S",
        "rendering/scope_adapter.c", "geometry/geometry.c", "geometry/prepare.c", "geometry/extras.c",
        "content_geometry/accepted_content.c", "content_geometry/unity_adapter.c", "main_geometry/main.c",
        "input/input.c", "product/product_policy.c", "product/environment.c", "startup.cpp", "review/scopes.cpp", "rendering/render_boundary.cpp", "rendering/accepted_repaint.cpp", "geometry/birth.cpp",
    ]
    flags = ["-O2", "-fPIC", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
             "-I" + str(build), "-I" + str(SOURCE), "-I" + str(SOURCE / "deps"), "-I" + str(SOURCE / "geometry")]
    gtk = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "gtk+-3.0", "json-c"], text=True))
    libraries = shlex.split(subprocess.check_output(["pkg-config", "--libs", "gtk+-3.0", "json-c"], text=True))
    objects, commands = [], []
    source_pins = {str(p.relative_to(SOURCE)): digest(p) for p in SOURCE.rglob("*") if p.is_file()}
    for name in files:
        obj = build / (name.replace("/", "_") + ".o")
        cpp = name.endswith(".cpp")
        cmd = ["c++" if cpp else "cc", *(["-std=c++17"] if cpp else [] if name.endswith(".S") else ["-std=gnu11"]),
               *flags, *gtk, "-c", str(SOURCE / name), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        objects.append(str(obj))
        commands.append(cmd)
    cmd = ["c++", "-shared", "-Wl,-z,defs,-z,relro,-z,now", *objects, *libraries,
           "-ldl", "-pthread", "-lm", "-lcrypto", "-o", str(output)]
    subprocess.run(cmd, check=True)
    commands.append(cmd)
    if source_pins != {str(p.relative_to(SOURCE)): digest(p) for p in SOURCE.rglob("*") if p.is_file()}:
        raise RuntimeError("Source changed during build.")
    result = dict(abi=1, library=str(output), library_sha256=digest(output), target_exe=str(target),
                  public_editor=str(public), settings_path=str(settings), constructor_contract="product-profile-v1",
                  host_environment_abi=1, restore_host_on_refusal=True, original_sha256=ELF_SHA, editor_source=str(original),
                  original_guards_verified=verified, input_context_guards=4, source_hashes=source_pins, commands=commands,
                  canonical_factor="float(percent/100.0) widened to double everywhere", parsed_percent_range=[100, 200],
                  queued_repaint_api_guard='0x3b335f0:16', accepted_allocation_repaint=True,
                  runtime_verified_percentages=[], Unity_run=False, production_applied=False, presented=False)
    (build / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("library", "library_sha256", "target_exe", "original_guards_verified", "Unity_run")}))


if __name__ == "__main__":
    main()
