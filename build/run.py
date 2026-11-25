"""Test harness: execute a notebook's SQL cells via snow CLI. usage: run.py <nb> [conn] [skip_names_csv]"""
import json, subprocess, sys, tempfile, os
nb = json.load(open(sys.argv[1]))
conn = sys.argv[2] if len(sys.argv) > 2 else "sfseapac-isuryawinata_aws1"
skip = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else set()
ctx = ""
for c in nb["cells"]:
    if c["cell_type"] != "code": continue
    name = c["metadata"]["name"]
    if name in skip: continue
    src = c["source"].split("\n", 1)[1]
    if name == "set_context": ctx = src
    elif ctx: src = ctx + "\n" + src
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write(src); p = f.name
    r = subprocess.run(["snow", "sql", "-c", conn, "-f", p, "--format", "json"], capture_output=True, text=True)
    os.unlink(p)
    expect_err = name in {"test_no_raw", "test_no_access"}
    ok = (r.returncode == 0) != expect_err
    print(f"[{'OK ' if ok else 'ERR'}] {name}{' (expected error)' if expect_err else ''}")
    if not ok:
        print((r.stderr or r.stdout)[-1500:]); sys.exit(1)
    if "-v" in sys.argv: print(r.stdout[-800:])
