"""print part of a --trace log: python trace.py logs/good_L9.json <phase|*> <step|-1> [t0 t1]"""
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
c = r["trace_cols"]
ph, st = sys.argv[2], int(sys.argv[3])
t0, t1 = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (-1, 1e9)
for row in r["trace"]:
    d = dict(zip(c, row))
    if (ph == "*" or d["phase"] == ph) and (st < 0 or d["step"] == st) and t0 <= d["t"] <= t1:
        print("%6.1f %-8s %d agl %5.0f kt %5.1f th %5.1f phi %5.1f vs %6.0f nz %4.1f x %6.1f al %7.0f el %5.2f ai %5.2f thr %4.2f" % (
            d["t"], d["phase"], d["step"], d["agl_m"] / 0.3048, d["kts"], d["theta"], d["phi"], d["vs_fpm"], d["nz"], d["cross_m"], d["along_m"],
            d["elev"], d["ail"], d["thr"]))
