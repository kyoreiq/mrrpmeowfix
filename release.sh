#!/usr/bin/env bash
# Publishes a new version to GitHub. Every installed copy picks it up within a few hours.
#   ./release.sh 1.2.0 "What changed"
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

version="${1:-}"
notes="${2:-}"
if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Usage: ./release.sh 1.2.0 \"What changed\""
    exit 1
fi
current=$(python3 -c 'import mrrpmeowfix; print(mrrpmeowfix.VERSION)')
if ! python3 -c "import sys; a, b = (tuple(map(int, v.split('.'))) for v in sys.argv[1:]); sys.exit(a <= b)" "$version" "$current"; then
    echo "Version $version isn't newer than $current."
    exit 1
fi
command -v gh >/dev/null || { echo "Install the GitHub CLI first (sudo pacman -S github-cli), then run: gh auth login"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Log in to GitHub first: gh auth login"; exit 1; }
python3 -m json.tool fixes/community.json >/dev/null || { echo "fixes/community.json isn't valid JSON."; exit 1; }

python3 -m unittest discover -s tests -t . -q
sed -i "s/^VERSION = .*/VERSION = \"$version\"/" mrrpmeowfix/__init__.py
cp fixes/community.json data/community.json
rm -rf dist
./make-zip.sh
(cd dist && sha256sum "mrrpmeowfix-$version.zip" > "mrrpmeowfix-$version.zip.sha256")

git add -A
git commit -q -m "mrrpmeowfix $version"
git tag "v$version"
git push -q origin HEAD "v$version"
gh release create "v$version" "dist/mrrpmeowfix-$version.zip" "dist/mrrpmeowfix-$version.zip.sha256" \
    --title "mrrpmeowfix $version" --notes "${notes:-mrrpmeowfix $version}"
echo "Released $version."
