#!/usr/bin/env python3
"""Offline generated-payload/authoritative-policy checks; never starts Unity."""
import argparse
import ctypes
import json
from pathlib import Path
import shlex
import subprocess

P = Path(__file__).resolve().parent
a = argparse.ArgumentParser(description=__doc__)
a.add_argument("--library", type=Path, required=True)
args = a.parse_args()
library = args.library.resolve(strict=True)
b = library.parent / (library.name + ".build")
out = b / "checks"
out.mkdir(exist_ok=False)
flags = ["-O2", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-I" + str(b),
         "-I" + str(P / "source"), "-I" + str(P / "source/geometry")]
subprocess.run(["cc", "-std=gnu11", *flags, str(P / "tests/input_payloads.c"), "-lm", "-o", str(out / "input")], check=True)
input_result = subprocess.check_output([str(out / "input")], text=True)
public = out / "public-Unity"
public.write_text("Test-only canonical profile key; never executed.\n")
settings = out / "test-settings.json"
(out / "config.generated.h").write_text("#define NS_PUBLIC_EDITOR " + json.dumps(str(public)) + "\n#define NS_SETTINGS_FILE " + json.dumps(str(settings)) + "\n")
gtk = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "gtk+-3.0", "json-c"], text=True))
subprocess.run(["c++", "-std=c++17", "-I" + str(out), *flags, "-ffunction-sections", "-fdata-sections", str(P / "tests/policy.cpp"),
                str(P / "source/startup.cpp"), str(b / "product_product_policy.c.o"), *gtk, "-Wl,--gc-sections", "-o", str(out / "policy")], check=True)

def document(enabled=True, percent=150):
    return {"schema_version": 2, "editors": {str(public): {"override_enabled": enabled, "ui_scale_percent": percent, "control_revision": 1}}, "extra_editors": []}

def run(mode, percent, doc):
    if doc is None:
        settings.unlink(missing_ok=True)
    else:
        settings.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    subprocess.run([str(out / "policy"), mode, str(percent)], check=True)

for percent in range(100, 201):
    run("custom", percent, document(percent=percent))
run("default", 0, document(False, 175))
run("default", 0, None)
run("default", 0, {"schema_version": 2, "editors": {}, "extra_editors": []})
for doc in ["{", document("false"), document(percent=True), document(percent=99), document(percent=201), document(percent=150.5)]:
    run("refuse", 0, doc)
ctypes.CDLL(str(library))  # Foreign process: no code hooks or GTK init.
result = {"generated_input_payloads": json.loads(input_result), "authoritative_policy_cases": 110,
          "read_once_after_file_change": True, "actual_dso_foreign_bypass": True, "Unity_run": False,
          "limits": "native callees/GTK objects mocked; actual product constructor covered by constructor_check.py"}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
