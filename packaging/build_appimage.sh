#!/bin/bash
# Run only in the ephemeral Ubuntu22.04 CI builder. No system changes on end-user PCs.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
work=${RUNNER_TEMP:-${TMPDIR:-/tmp}}/unity-appimage-build
rm -rf -- "$work"
mkdir -p "$work" "$project/dist"
python3 "$project/packaging/fetch_locked.py" "$project/packaging/tools.lock.json" "$work"
appdir="$work/AppDir"
root="$appdir/usr/share/unity-editor-scaling"
mkdir -p "$root" "$appdir/usr/bin" "$appdir/usr/lib/python3.10/site-packages" "$appdir/usr/share/glib-2.0/schemas" "$work/sources"
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$project" log -1 --format=%ct)}
# The only native runtime dependencies deliberately left on the host are those
# already needed by the supported Unity Editor (GTK3/GLib/X11 and base libc).
# Generated best-effort diagnostic writes intentionally ignore short/error returns.
export STATIC_DEPS_CFLAGS='-Wno-error=unused-result'
export STATIC_DEPS_LIBS='-Wl,-Bstatic -ljson-c -lcrypto -Wl,-Bdynamic -ldl -lpthread -lz -lm -Wl,--exclude-libs,ALL'
mkdir -p "$root/native/prebuilt"
python3 "$project/native/product/build.py" --output "$root/native/prebuilt/native-v2.so"
rm -rf "$root/native/prebuilt/native-v2.so.build"
mkdir -p "$root/libexec"
cc -std=gnu11 -O2 -Wall -Wextra -Werror -Wno-misleading-indentation -static "$project/packaging/update_helper.c" -lcrypto -ldl -pthread -o "$root/libexec/unity-scale-update-helper"
# Build the GUI runtime against old glibc; do not copy host CachyOS binaries.
prefix="$appdir/usr"
export PATH="$prefix/bin:$PATH"
export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig:$prefix/share/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export GI_TYPELIB_PATH="$prefix/lib/girepository-1.0"
python3 "$project/packaging/fetch_locked.py" "$project/packaging/sources.lock.json" "$work/sources" --extract

build() { local name=$1; shift; local source; source=$(find "$work/sources" -mindepth 1 -maxdepth 1 -type d -name "$name-*" | head -1); meson setup "$work/build-$name" "$source" --prefix "$prefix" --libdir lib --buildtype release -Ddebug=false "$@"; ninja -C "$work/build-$name" -j2; ninja -C "$work/build-$name" install; }
build glib -Dtests=false -Dinstalled_tests=false -Dgtk_doc=false -Dman=false -Dselinux=disabled -Dlibmount=disabled
build gobject-introspection -Ddoctool=disabled
build gtk -Dintrospection=enabled -Dwayland-backend=false -Dx11-backend=true -Dbroadway-backend=true -Dmedia-gstreamer=disabled -Dprint-cups=disabled -Dvulkan=disabled -Dbuild-tests=false -Dbuild-testsuite=false -Dbuild-examples=false -Dbuild-demos=false -Ddocumentation=false
build libadwaita -Dtests=false -Dexamples=false -Dintrospection=enabled -Dvapi=false
build pygobject -Dtests=false -Dpycairo=enabled
# Use the Ubuntu22 Python ABI and its small GI bindings, against bundled GLib/GI.
cp -L /usr/bin/python3.10 "$appdir/usr/bin/python3.10"
cp -a /usr/lib/python3.10 "$appdir/usr/lib/"
cp -a /usr/lib/python3/dist-packages/cairo "$appdir/usr/lib/python3.10/site-packages/"
rm -rf "$appdir/usr/lib/python3.10"/config-* "$appdir/usr/lib/python3.10/site-packages/cairo/include"
# GIR/typelib dependencies are loaded dynamically and cannot be found by ldd.
for typelib in GdkPixbuf-2.0 Pango-1.0 PangoCairo-1.0 cairo-1.0 freetype2-2.0 HarfBuzz-0.0 Graphene-1.0; do
  cp -L "/usr/lib/x86_64-linux-gnu/girepository-1.0/$typelib.typelib" "$appdir/usr/lib/girepository-1.0/"
done
cp -a "$project/unity_scale" "$root/"
cp -a "$project/resources" "$root/"
cp /etc/ssl/certs/ca-certificates.crt "$root/resources/ca-certificates.crt"
cp "$project/LICENSE" "$project/NOTICE" "$project/README.md" "$root/"
cp "$project/packaging/AppRun" "$appdir/AppRun"
# SVG icons need the installed GdkPixbuf SVG loader and its runtime dependency.
mkdir -p "$appdir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders"
cp -a /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so "$appdir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/"
cp -L /usr/bin/gdk-pixbuf-query-loaders "$appdir/usr/bin/" 2>/dev/null || cp -L /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders "$appdir/usr/bin/"
cp -a /usr/share/glib-2.0/schemas/*.xml "$appdir/usr/share/glib-2.0/schemas/"
# Use matching Fontconfig configuration, while discovering host/user fonts.
# Host distributions can ship syntax newer than Ubuntu22's bundled library.
mkdir -p "$appdir/usr/etc/fonts/conf.d" "$appdir/usr/share/fonts/truetype/dejavu"
cp -L /etc/fonts/fonts.conf "$appdir/usr/etc/fonts/fonts.conf"
cp -L /etc/fonts/conf.d/*.conf "$appdir/usr/etc/fonts/conf.d/"
# Host/user configuration may use newer syntax; host font files remain visible.
rm -f "$appdir/usr/etc/fonts/conf.d/50-user.conf" "$appdir/usr/etc/fonts/conf.d/51-local.conf"
cp /usr/share/fonts/truetype/dejavu/*.ttf "$appdir/usr/share/fonts/truetype/dejavu/"

"$prefix/bin/glib-compile-schemas" "$appdir/usr/share/glib-2.0/schemas"
# Keep runtime entry points only; GNOME code generators and test tools belong
# in the ephemeral builder, not the distributed application.
find "$appdir/usr/bin" -mindepth 1 -maxdepth 1 ! -name python3.10 ! -name gtk4-broadwayd ! -name gdk-pixbuf-query-loaders -delete
rm -rf "$appdir/usr/lib/gobject-introspection" "$appdir/usr/share/gir-1.0"
python3 "$project/packaging/collect_runtime.py" "$appdir"
python3 "$project/packaging/collect_licenses.py" "$appdir" "$work/sources" "$project"
find "$appdir" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$appdir" -type f \( -name '*.a' -o -name '*.la' -o -name '*.pyc' \) -delete
rm -rf "$appdir/usr/include" "$appdir/usr/lib/pkgconfig" "$appdir/usr/share/doc" "$appdir/usr/share/man" "$appdir/usr/lib/python3.10/test" "$appdir/usr/lib/python3.10/idlelib" "$appdir/usr/lib/python3.10/ensurepip" "$appdir/usr/share/gtk-doc"
# Host tooling must not load or rewrite the same bundled libraries it uses.
unset LD_LIBRARY_PATH PKG_CONFIG_PATH GI_TYPELIB_PATH
rm -rf "$appdir/usr/share/gdb" "$appdir/usr/share/glib-2.0/codegen" "$appdir/usr/share/glib-2.0/gettext"
python3 - "$appdir" <<'PYSTRIP'
from pathlib import Path
import subprocess,sys
seen=set()
for path in Path(sys.argv[1]).rglob('*'):
 if not path.is_file() or path.resolve() in seen:continue
 with path.open('rb') as stream:is_elf=stream.read(4)==b'\x7fELF'
 if is_elf:
  seen.add(path.resolve())
  subprocess.run(['strip','--strip-unneeded',str(path)],check=True)
PYSTRIP
cp "$root/resources/io.github.unityscale.UnityScale.svg" "$appdir/io.github.unityscale.UnityScale.svg"
cat > "$appdir/io.github.unityscale.UnityScale.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Unity Editor Scaling for Linux
Exec=unity-scale
Icon=io.github.unityscale.UnityScale
Categories=Development;
Terminal=false
StartupWMClass=io.github.unityscale.UnityScale
EOF

# Native .so and ELF hashes in the prebuilt manifest must describe shipped bytes.
python3 - "$root/native/prebuilt" <<'PY'
from pathlib import Path
import hashlib,json,sys
p=Path(sys.argv[1]);m=json.loads((p/'manifest.json').read_text())
for n in m['files']:m['files'][n]=hashlib.sha256((p/n).read_bytes()).hexdigest()
(p/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
PY
ARCH=x86_64 "$work/appimagetool" --appimage-extract-and-run --runtime-file "$work/runtime-x86_64" --comp zstd "$appdir" "$project/dist/Unity-Editor-Scaling-for-Linux-x86_64.AppImage"
"$project/dist/Unity-Editor-Scaling-for-Linux-x86_64.AppImage" --appimage-extract-and-run --self-test
