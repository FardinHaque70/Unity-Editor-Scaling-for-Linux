Relocatable native startup scaling — product-profile-v2 / 0.4rc1
==============================================================

The unchanged scaling/input/allocation/Repaint payload is pinned to Linux x64
Unity 6000.3.27f2 SHA-256:
d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec
The parser accepts integer100..200; actual runtime evidence remains scoped to
the previously accepted percentages/environment. It does not prove all scales.

Build generic binaries without an installed Unity executable:
  python3 native/product/build.py --output native/prebuilt/native-v2.so
Writes native-v2.so, wrapper-v2, manifest.json and a .build metadata directory.
Optional --editor-source ORIGINAL verifies all59 frozen guards and four input
contexts read-only against the exact original SHA. compatibility.json contains
only the short pinned contexts, never Unity's executable. Builds refuse changed
guard sources. End users receive prebuilt binaries and need no compiler.

Packaging supplies STATIC_DEPS_CFLAGS and STATIC_DEPS_LIBS with PIC static
json-c/OpenSSL archives. These dependency symbols are hidden in the DSO. GTK3
and its normal host dependencies remain dynamic; no crypto dlopen is used.
Unspecified flags allow dynamic json-c/crypto for local developer builds only.

Runtime package layout:
  Editor/Unity                         public ELF copy of wrapper-v2
  Editor/.Unity.unity-scale-original    unchanged preserved original
  Editor/.unity-editor-scaling/         private user-owned mode0700 directory
    wrapper-v2
    native-v2.so
    activation.json
The launcher derives the package from /proc/self/exe. The DSO derives it from
its own module path. Neither contains installation/settings path constants.

activation.json is strict duplicate-free finite UTF-8 JSON with these fields:
  schema:2, constructor_contract:"product-profile-v2",
  public_editor, target_exe, settings (canonical absolute paths),
  wrapper:"wrapper-v2", library:"native-v2.so", owner_uid,
  original_sha256 (the exact SHA above), wrapper_sha256, library_sha256,
  original_identity:{st_dev,st_ino,st_size,st_mtime_ns}.
public_editor and target_exe must exactly match the derived Editor siblings.
Managed files must be regular, caller-owned and not group/other writable.
Symlink path components are refused. The package must be private. File snapshots
are checked for concurrent changes during hashing/reading; identity and full
SHA verification cover original/public launcher/package launcher/native library.
The installer supplies the trusted descriptor after verifying its release bundle.
The descriptor cannot redirect code or nominate an arbitrary executable.

All argv entries, including argv0 and empty arguments, are preserved. The host
GDK_SCALE/GDK_DPI_SCALE/GDK_BACKEND values are carried in the strict ABI1
UNITY_EDITOR_SCALING_HOST_ENV envelope. Inherited custom GDK state is restored
before helper/foreign bypass, Default or refusal. Constructor helpers/foreign
processes remove only their own preload entry before descriptor admission.
The launcher validates its activation before executing any role of the original.
Settings/public-editor environment metadata may only redundantly match the
validated descriptor. There is one authoritative settings read per GUI process.
Default retains the neutral loader for fresh OpenProject policy reads. Custom
keeps the accepted KDE Wayland/X11 GTK/OpenGL, thread, exact SHA and byte guards.
No live scale setter, production sampling timer or global desktop change exists.
Post-commit failure exits126; no partial native install may continue.

Read-only inspection API in source/startup.h:
  unity_native_startup_query(ns_status*, sizeof(ns_status))
  unity_native_settled_query(ns_settled_snapshot*, sizeof(ns_settled_snapshot))
The latter is synchronous, owner-thread-only and requires native quiescence,
settled Unity geometry, valid birth generations and no boundary poison. It
returns bounded mapped-window/view arrays containing logical allocation, cached
scale and backing dimensions. A rejected/partial sample is cleared. It creates
no timer, pumps no events, calls no setter and makes no presentation/GPU claim.
Optional UNITY_EDITOR_SCALING_RECEIPT records launch policy and existing native
trace events to an exclusive PID/start-time-suffixed owner file; it no longer
starts an automatic sampling timer.

Offline verification (never starts Unity):
  python3 native/product/check.py --library FRESH_BUILT_LIBRARY
  python3 native/product/constructor_check.py --library FRESH_BUILT_LIBRARY
  python3 native/product/launcher_check.py
  python3 native/product/repaint_check.py
check.py covers1212 input payloads and110 authoritative policy cases. Constructor
checks exercise the actual artifact in inert hosts, including helper/foreign
host restoration, metadata refusal and unavailable settled-query rejection.
launcher_check.py tests relocation, argv/environment and activation refusal
using inert ELF fixtures with a test-copy-only original digest substitution;
production artifacts contain no digest override. Repaint checks retain real
GObject signals and mocked native callees for queueing, retirement, birth reuse
and weak widget lifetime. These checks do not prove actual Unity presentation.

native/legacy-launcher-v1.c preserves the prior launcher solely for legacy
migration fixtures; it is not the product-profile-v2 shipped launcher.
