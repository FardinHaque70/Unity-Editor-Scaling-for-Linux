# Arch source recipe

`PKGBUILD.in` is a template. `packaging/release.py` produces
`dist/arch/PKGBUILD` with the exact generated source archive checksum.
Put that file beside the source archive and run `makepkg -si`.

No public AUR package or repository URL is claimed. Before a public AUR submission,
replace the local-file source with the chosen release URL and retain the checksum.
The source recipe builds the helper against the user's distribution.
