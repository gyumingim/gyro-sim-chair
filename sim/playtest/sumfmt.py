"""compact view of run.py output lines (stdin) or of summary files: python sumfmt.py [summary.json ...]"""
import json, sys


def line(d):
    return "%-3s %-6s L%-2d %s %-5s %-14s cr %-3d %-40s skip %d coach %-3d %5.1f min %s %s" % (
        d["assist"], d["bot"], d["lesson"], "PASS" if d["passed"] else "FAIL", "1st" if d["first_try"] else "", d["scores"], d["crashes"],
        ",".join(d["crash_why"])[:40], d["skips"], d["coach"], d["sim_min"], d.get("touchdown", ""), d["fails"])


if len(sys.argv) > 1:
    for f in sys.argv[1:]:
        for d in json.load(open(f, encoding="utf-8"))["runs"]:
            print(line(d))
else:
    for l in sys.stdin:
        if l.startswith("{"):
            print(line(json.loads(l)), flush=True)
