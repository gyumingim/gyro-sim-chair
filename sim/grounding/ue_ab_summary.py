"""Building contact UE A/B (ue_contact_ab.ps1) -> UE_AB.json for build_page.py: shots (JPEG copies, 1600 px) + GPU table.

    python sim/grounding/ue_ab_summary.py C:/GyroSimTiles/shots/contact OUT.json
GPU: art_shots 'Average GPU frametime' (startfpschart, 10 s, ~1080p pixels) + frame-time avg / p99 / max of the same 10 s.
'off' and 'off2' are the same setting shot twice (run-to-run noise).
"""
import glob, json, os, sys
from PIL import Image

CAP = {"off": "끔 (지금)", "on": "켬 (Blender 추천값: 사진 ×0.4, 띠 0.55 / 6 m, 벽 0.45 / 4 m)",
       "strong": "켬 강하게 (사진 ×0.3, 띠 0.7 / 8 m, 벽 0.55 / 5 m)", "off2": "끔 (반복)",
       "debug": "확인용 과장 (사진 ×0, 띠 1.0 / 8 m): 고침이 칠해지는 자리 확인"}


def main(d, out):
    js = sorted(glob.glob(os.path.join(d, "shots_*.json")), key=os.path.getmtime)
    S = json.load(open(js[-1], encoding="utf-8"))
    shots = []
    views = []
    for k in S.get("shots", {}):
        v, var = k.rsplit("_", 1)
        if v not in views:
            views.append(v)
    for i, v in enumerate(views):
        for var in ("off", "on", "strong") + (("debug",) if i == 0 else ()):
            k = "%s_%s" % (v, var)
            if k not in S["shots"]:
                continue
            src = S["shots"][k]["file"]
            if not os.path.isabs(src):
                src = os.path.join(d, src)
            if not os.path.exists(src):
                cand = glob.glob(os.path.join(d, "**", os.path.basename(src)), recursive=True)
                if not cand:
                    continue
                src = cand[0]
            dst = os.path.join(os.path.dirname(out), "ue_%s_%s.jpg" % (v, var))
            Image.open(src).convert("RGB").save(dst, quality=88)
            shots.append(dict(path=dst, cap="%s: %s" % (v, CAP.get(var, var))))
    gpu = []
    G = {}
    for r in S.get("gpu", []):
        G.setdefault(r["view"], {})[r["variant"]] = r
    for v, g in G.items():
        def f(var, key="gpu_ms"):
            x = g.get(var, {}).get(key)
            return "-" if x is None else "%.2f" % x
        off = [g[x]["gpu_ms"] for x in ("off", "off2") if x in g and g[x].get("gpu_ms") is not None]
        on = g.get("on", {}).get("gpu_ms")
        st = g.get("strong", {}).get("gpu_ms")
        base = sum(off) / len(off) if off else None
        dif = "-" if base is None or on is None else "%+.2f (반복 차 %.2f)" % (on - base, abs(off[0] - off[-1]) if len(off) > 1 else 0)
        gpu.append([v, "%s / %s" % (f("off"), f("off2")), "%s / 강 %s" % (f("on"), f("strong")), dif])
        gpu.append([v + " 프레임 p99·max", "%s·%s / %s·%s" % (f("off", "p99_ms"), f("off", "max_ms"), f("off2", "p99_ms"), f("off2", "max_ms")),
                    "%s·%s / %s·%s" % (f("on", "p99_ms"), f("on", "max_ms"), f("strong", "p99_ms"), f("strong", "max_ms")), ""])
    json.dump(dict(shots=shots, gpu=gpu, raw=S.get("gpu", []), summary_html=""), open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(out, len(shots), "shots", len(gpu), "gpu rows")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
