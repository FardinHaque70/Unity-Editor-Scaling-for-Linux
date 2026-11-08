#!/bin/sh
set -eu
app_entry=$(readlink -f -- "$0")
app_directory=$(dirname -- "$app_entry")
cd -- "$app_directory"
unset UNITY_SCALING_PRIVATE_V4
export PYTHONDONTWRITEBYTECODE=1
exec /usr/bin/python3 "$app_directory/bin/unity-scale" "$@"
