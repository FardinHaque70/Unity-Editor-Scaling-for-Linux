Native startup scaling source package — 0.3.0.dev1
================================================

This package implements immutable per-process scaling for the exact Linux x64
Unity 6000.3.27f2 executable with SHA-256:
d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec

See the top-level README.md for installation changes, the scaling mechanism,
supported environment, scoped runtime evidence, restoration, and limitations.
The installer verifies source-manifest.json before building. This distribution
retains the audited runtime source bytes and omits historical build outputs and
investigation receipts. Source-manifest.json records the upstream package pin.

Build only (does not launch or modify Unity):
  python3 build.py --editor-source ORIGINAL --target-exe PRESERVED_ELF \
    --public-editor CANONICAL_PUBLIC_EDITOR --settings ABSOLUTE_SETTINGS_JSON \
    --output FRESH_LIBRARY

The output is bound to the exact preserved executable, public profile identity,
and settings path. A library built for a temporary test path is not portable to
an installed Editor. The normal installer performs this build and delivery.

The product-profile-v1 constructor reads schema-2 settings once. Missing settings
or a missing profile selects Default. Custom admits integer percentages100..200;
this parser range does not establish runtime correctness for every percentage.
Malformed or unsafe settings refuse custom installation rather than becoming a
successful Default selection.

The launcher passes UNITY_EDITOR_SCALING_SETTINGS and
UNITY_EDITOR_SCALING_PUBLIC_EDITOR as identity metadata only. It captures the
original GDK_SCALE/GDK_DPI_SCALE/GDK_BACKEND values in the strict ABI-1
UNITY_EDITOR_SCALING_HOST_ENV JSON envelope. Child/helper/Default paths restore
those original values before choosing their own policy. Default retains the
neutral library but installs no scaling hooks. Helpers remove only the owned
preload entry; foreign entries are preserved and refuse Custom composition.

Custom is restricted to KDE Wayland with DISPLAY and the tested X11 GTK/OpenGL
route. The constructor checks the original ELF hash, instruction bytes, startup
role, thread state, and hook boundaries before installation. It then normalizes
process-local GTK/GDK scaling; no global preload or desktop setting is changed.
Failures after native patch commit terminate126 instead of continuing with a
partially installed backend. There is no live scale setter.

Optional diagnostics: UNITY_EDITOR_SCALING_RECEIPT is an absolute file prefix in
an owned directory that is not group/other writable. A fresh PID/start-time
suffixed file records policy, installation, repaint requests, and bounded
owner-thread GTK/Gfx samples. UNITY_EDITOR_SCALING_DIAGNOSTIC_SAMPLES accepts
integer1..120 (default16); UNITY_EDITOR_SCALING_DIAGNOSTICS=0 disables sampling.
No receipt means no diagnostic sampling timer. Queue acceptance, installation
status, and matching sampled buffers do not prove compositor presentation.

Offline checks (never launch Unity):
  python3 check.py --library FRESH_BUILT_LIBRARY
  python3 constructor_check.py --editor-source ORIGINAL
  python3 repaint_check.py

check.py needs the corresponding .build outputs and a fresh checks directory.
It tests generated input payloads and policy with mocked native/GTK operations.
constructor_check.py uses a tiny compiled host that intentionally cannot pass
Unity's hash; it checks neutral and refusal paths only. repaint_check.py uses
real GObject signals with fake GTK/native callees to check queueing and lifetime
guards. None of these checks establishes actual Unity rendering/input behavior.
