#!/bin/sh
# speak.sh - launcher for the self-contained Speak EPUB CLI (macOS / Linux).
#
# 1. a cached Python runtime (downloaded once) is used when present
# 2. otherwise any system python3 starts speak.py, which fetches the runtime
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
RUNTIME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/speak-epub/runtime"

if [ ! -f "$HERE/runtime.json" ]; then
  echo "Missing $HERE/runtime.json - this is not a Speak EPUB CLI package." >&2
  exit 1
fi

read_hash() {
  python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('hash',''))" "$HERE/runtime.json" 2>/dev/null \
    || sed -n 's/.*"hash"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$HERE/runtime.json" | head -n 1
}

HASH=$(read_hash)
CACHED="$RUNTIME_DIR/$HASH/python/bin/python3"

if [ -x "$CACHED" ]; then
  exec "$CACHED" "$HERE/speak.py" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$HERE/speak.py" "$@"
fi

echo "No Python found - download the Speak EPUB runtime manually to $CACHED" >&2
exit 1
