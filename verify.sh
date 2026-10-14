#!/bin/sh
# Run from any directory. The tests use a synthetic service, never live BKW data.
set -eu
cd "$(dirname "$0")"
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    PY=python3
fi
"$PY" - <<'PYCHECK'
import ast
import json
import pathlib

root = pathlib.Path("custom_components/bkw")
for path in root.rglob("*.py"):
    ast.parse(path.read_text())
manifest = json.loads((root / "manifest.json").read_text())
required = {"domain", "name", "version", "documentation", "codeowners", "iot_class"}
missing = required - set(manifest)
if missing:
    raise SystemExit(f"manifest.json is missing: {sorted(missing)}")
if manifest["domain"] != root.name:
    raise SystemExit("manifest domain does not match the directory name")
print("static checks ok")
PYCHECK
"$PY" -m unittest tests.test_api -v
"$PY" -m pytest tests/test_integration.py tests/test_statistics.py -q
