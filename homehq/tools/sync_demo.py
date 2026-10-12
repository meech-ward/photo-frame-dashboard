#!/usr/bin/env python3
"""Keep the native, web and SQL sample projections equal to the authored fixture."""
import argparse
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fixture = json.loads((ROOT / "fixtures/demo.json").read_text())
    compact = json.dumps(fixture, separators=(",", ":"), ensure_ascii=False)
    python = ROOT / "badge/homehq/demo.py"
    sql = ROOT / "supabase/schemas/demo.sql"
    web = ROOT / "web/src/demo-fixture.json"
    native_source = python.read_text()
    sql_source = sql.read_text()
    if "$fixture$" in compact:
        raise SystemExit("fixture contains the SQL literal delimiter")
    native = next(node.value.value for node in ast.parse(native_source).body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_DATA" for t in node.targets))
    match = re.search(r"\$fixture\$(.*?)\$fixture\$::jsonb", sql_source, re.S)
    if not match:
        raise SystemExit("SQL fixture seam is missing")
    if args.check:
        if json.loads(native) != fixture or json.loads(match.group(1)) != fixture or json.loads(web.read_text()) != fixture:
            raise SystemExit("Sample drift: run homehq/tools/sync_demo.py and regenerate the declarative migration")
        print("Native/web/SQL sample parity: PASS")
    else:
        native_source = re.sub(r"^_DATA = .*?$", lambda _: "_DATA = " + repr(compact), native_source, count=1, flags=re.M)
        sql_source = sql_source[:match.start(1)] + compact + sql_source[match.end(1):]
        python.write_text(native_source)
        sql.write_text(sql_source)
        web.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
        print("Sample projections synchronized. Regenerate a migration for any SQL change.")


if __name__ == "__main__":
    main()
