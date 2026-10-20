#!/bin/zsh
# usage: F=page.html [D=2] [L=zh-CN] [RM=1] dev/shot.sh <hash> <out.png> [width] [height]
# Takes a still of a local page with Playwright's chrome-headless-shell, which does not make the
# app clones that headless Google Chrome leaves behind on macOS. Set CH to use another binary.
# The page's CSS transitions are not frozen by #t=; RM=1 asks for reduced motion, which turns them off (use it for the drawer).
setopt null_glob
if [[ -z "$CH" ]]; then
  for c in ~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell \
           ~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell; do CH=$c; done
fi
[[ -x "$CH" ]] || { echo "no chrome-headless-shell; run: npx playwright install chromium-headless-shell, or set CH" >&2; exit 1; }
P="$PWD/${F:?set F to the page to capture}"
OUT="$PWD/${2:?out.png}"; rm -f "$OUT"
PROF=$(mktemp -d "${TMPDIR:-/tmp}/treesight-shot.XXXXXX")
"$CH" --hide-scrollbars --force-device-scale-factor=${D:-1} --user-data-dir="$PROF" \
  ${RM:+--force-prefers-reduced-motion} --lang=${L:-en-US} --window-size=${3:-1280},${4:-1500} --screenshot="$OUT" "file://$P#$1" >/dev/null 2>&1
rm -rf "$PROF"
ls -la "$OUT" | awk '{print $5, $NF}'
