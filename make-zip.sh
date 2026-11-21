#!/usr/bin/env bash
# Builds dist/mrrpmeowfix-<version>.zip to send to friends.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
version=$(python3 -c 'import mrrpmeowfix; print(mrrpmeowfix.VERSION)')
mkdir -p dist
out="dist/mrrpmeowfix-$version.zip"
python3 - "$out" <<'PY'
import os, sys, zipfile
out = sys.argv[1]
include = ["mrrpmeowfix", "data", "install.sh", "uninstall.sh", "README.md"]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for item in include:
        paths = [item] if os.path.isfile(item) else [
            os.path.join(d, f) for d, dirs, files in os.walk(item)
            if "__pycache__" not in d for f in files]
        for p in sorted(paths):
            info = zipfile.ZipInfo.from_file(p, os.path.join("mrrpmeowfix", p))
            with open(p, "rb") as f:
                z.writestr(info, f.read(), zipfile.ZIP_DEFLATED)
print(out)
PY
