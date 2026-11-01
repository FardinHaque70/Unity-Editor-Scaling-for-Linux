#!/usr/bin/env bash
set -euo pipefail
task_app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_source_dir="$task_app_dir/bridge/unity-scaling-xwayland-satellite-v5.2"
export RUSTFLAGS="${RUSTFLAGS:--C target-cpu=x86-64}"
cd -- "$task_source_dir"
cargo build --locked --release
cargo test --locked --lib
install -Dm755 target/release/xwayland-satellite "$task_app_dir/libexec/xwayland-satellite"
