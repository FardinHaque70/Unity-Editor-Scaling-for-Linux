#!/bin/bash
# Run only in the ephemeral Ubuntu22.04 CI builder. No system changes on end-user PCs.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
work=${RUNNER_TEMP:-${TMPDIR:-/tmp}}/unity-appimage-build
rm -rf -- "$work"
mkdir -p "$work" "$project/dist"
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
python3 - "$project/packaging/sources.lock.json" "$work/sources" <<'PY'
import hashlib,json,sys,urllib.request,tarfile
from pathlib import Path
items=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2])
for name,entry in items.items():
 target=out/(name+'.tar.xz');urllib.request.urlretrieve(entry['url'],target)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=entry['sha256']:raise SystemExit('Source hash mismatch: '+name)
 with tarfile.open(target) as archive:
  for member in archive.getmembers():
   if member.name.startswith('/') or '..' in Path(member.name).parts:raise SystemExit('Unsafe source archive')
  archive.extractall(out)
PY
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
find "$appdir" -type f -name '*.so*' -exec strip --strip-unneeded {} + || true
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
python3 - "$project/packaging/tools.lock.json" "$work" <<'PY'
import hashlib,json,sys,urllib.request
from pathlib import Path
for name,entry in json.loads(Path(sys.argv[1]).read_text()).items():
 path=Path(sys.argv[2])/name;urllib.request.urlretrieve(entry['url'],path)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise SystemExit('Tool hash mismatch: '+name)
 path.chmod(0o755)
PY
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
