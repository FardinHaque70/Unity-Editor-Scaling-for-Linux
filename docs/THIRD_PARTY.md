# Third-party runtime and source provenance

The application's own code is under [MPL 2.0](../LICENSE). The AppImage also redistributes components under their respective licenses; packaging does not change those licenses. The source checkout, build scripts and lockfiles identify the inputs used to produce it. Unity Editor, Unity Hub, GPU drivers and a private Xwayland server are not included.

## Pinned source builds

The exact source URLs and SHA-256 values are recorded in [sources.lock.json](../packaging/sources.lock.json). The linked source archives include their copyright and license notices.

| Component | Version | Corresponding source and license notices |
| --- | --- | --- |
| GLib | 2.78.6 | [Source archive](https://download.gnome.org/sources/glib/2.78/glib-2.78.6.tar.xz); LGPL-2.1-or-later and per-file notices in `LICENSES/` |
| GObject Introspection | 1.78.1 | [Source archive](https://download.gnome.org/sources/gobject-introspection/1.78/gobject-introspection-1.78.1.tar.xz); typelib library LGPL-2.0-or-later, tools and other files as described in `COPYING`, `COPYING.LGPL`, `COPYING.GPL` and file headers |
| GTK | 4.12.5 | [Source archive](https://download.gnome.org/sources/gtk/4.12/gtk-4.12.5.tar.xz); LGPL and per-file notices in `COPYING` and source headers |
| libadwaita | 1.4.6 | [Source archive](https://download.gnome.org/sources/libadwaita/1.4/libadwaita-1.4.6.tar.xz); LGPL-2.1 and applicable source headers |
| PyGObject | 3.46.0 | [Source archive](https://download.gnome.org/sources/pygobject/3.46/pygobject-3.46.0.tar.xz); LGPL-2.1 and applicable source headers |

The builder obtains Python 3.10, Pycairo, Cairo and additional GUI dependencies from Ubuntu 22.04 packages. OpenSSL and json-c are linked into the native components; OpenSSL is also linked into the standalone update helper. Their package copyright files and source-package identities must accompany the artifact's dependency inventory. Python uses the PSF license and notices for incorporated code; Pycairo/Cairo, graphics/text libraries and other transitive dependencies retain their own upstream terms. Refer to the shipped license inventory for the actual collected libraries rather than assuming every package present on the build machine was redistributed.

Ubuntu's corresponding source packages are available through its [source package archive](https://archive.ubuntu.com/ubuntu/pool/) and [Launchpad source package records](https://launchpad.net/ubuntu/+source). The build inventory must record source package names and versions so the matching source can be retrieved. GNOME dependencies built above use the exact upstream archives instead of the Ubuntu versions.

## AppImage tooling

[tools.lock.json](../packaging/tools.lock.json) records the official download URLs and SHA-256 values for both tools. A mutable upstream `continuous` URL is accepted only when its downloaded bytes match the pinned hash.

| Component | Use | Source and notices |
| --- | --- | --- |
| Type-2 runtime | Static runtime prepended to the AppImage | [AppImage/type2-runtime](https://github.com/AppImage/type2-runtime), revision `fedfad51acc2860b2916a1eef32ba4a500ff31ef`; [MIT license and incorporated dependency notice](https://github.com/AppImage/type2-runtime/blob/fedfad51acc2860b2916a1eef32ba4a500ff31ef/LICENSE) |
| appimagetool | Build tool; not installed in the application payload | [AppImage/appimagetool](https://github.com/AppImage/appimagetool), revision `11d54c9acc7f246df1398050a4b880314ac76862`; [license](https://github.com/AppImage/appimagetool/blob/11d54c9acc7f246df1398050a4b880314ac76862/LICENSE) |

The runtime's own notice lists incorporated musl, libfuse, squashfuse, zstd and zlib; its Makefile also links mimalloc. The artifact includes these notices, the top-level MIT license, and the commit-pinned dependency recipe, libfuse patch, Dockerfile and Makefile. The recipe pins libfuse 3.15.0 and squashfuse 0.5.2, but obtains other static libraries from Alpine 3.21 without pinning every transitive package version. The inventory records that upstream provenance limit rather than claiming exact versions that the binary metadata does not establish. License reference URLs and hashes are in [notices.lock.json](../packaging/notices.lock.json).

## Rebuilding or replacing libraries

The AppImage filesystem can be extracted with `--appimage-extract`. The bundled GUI uses shared libraries that can be replaced in an extracted development copy, subject to ABI compatibility. The application's source and CI build recipe are available in the same repository/release. Rebuilding is a developer workflow, not an end-user setup requirement.

A release must retain its license texts, package inventory, source URLs and build revision. A link to this overview alone is not a substitute for shipping required copyright notices or corresponding source/build materials.
