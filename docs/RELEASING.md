# Releasing the KDE beta

1. Run the full Python/GTK tests and locked Rust bridge tests. Update VALIDATION.md
   with observed results and unresolved limits; retain accurate platform scope.
2. Build on Ubuntu24.04 using the supplied CI workflow for an older glibc baseline.
   Verify the actual helper dependency versions and test a fresh KDE machine.
3. Run `python3 packaging/release.py --label linux-x86_64-ubuntu24.04`. Source and
   native payload tarballs, SHA256SUMS and a checksum-pinned local Arch recipe are
   generated in dist/. Test installation/uninstallation from the extracted tarball.
4. Select a public repository/release location and publish reviewed source,
   attribution, build workflow and compatibility scope. No repository/account URL
   is hardcoded or claimed by this local beta. The application ID is provisional.
5. Before AUR submission, replace its local source reference with that release URL
   and keep the exact checksum. No AUR package has been submitted yet.
6. Keep installer, Editor integration ownership and recovery formats compatible.
   Wrapper-template changes currently require disabling/re-enabling integration.
   Do not silently replace an Editor file after Hub updates or restore an old
   binary over an updated version.

Local prebuilt artifacts use a glibc2.43 helper. They are not labelled as universal
Linux binaries. Full source and a local build script are included so another
distribution can build against its own system libraries.

For upstream contributions, consult the upstream repository's current contribution
and AI policies, split general changes into focused commits and get independent
human review. All current source changes were AI-assisted; the local multi-agent
reviews are not represented as independent human review. No issue, PR, public
post or release has been sent by this application or this work session.
