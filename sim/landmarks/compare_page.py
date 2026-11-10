r"""Local comparison page: reference photo | before (GIS box) | after (landmark model) for each view of views.json, from the
offscreen shots (C:\GyroSimTiles\shots\landmarks) and the local reference photos. Output folder is given on the command
line (outside git: the page holds third-party photos and V-World imagery).
    python -I sim/landmarks/compare_page.py <out dir> [shots dir]
"""
import html, json, os, sys, time
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REFS = r"C:\GyroSimTiles\landmarks\refs"


def jpg(src, dst, w=760):
    im = Image.open(src).convert("RGB")
    im.thumbnail((w, w))
    im.save(dst, quality=82)


def main(out, shots=r"C:\GyroSimTiles\shots\landmarks"):
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    views = json.load(open(os.path.join(HERE, "views.json"), encoding="utf-8"))["views"]
    sj = json.load(open(os.path.join(shots, "shots.json"), encoding="utf-8")) if os.path.isfile(os.path.join(shots, "shots.json")) else {}
    rep = json.load(open(r"C:\GyroSimTiles\landmarks\build_report.json", encoding="utf-8"))
    rows = []
    for v in views:
        name, ref = v[0], v[7]
        cells = []
        if ref and os.path.isfile(os.path.join(REFS, ref)):
            d = "img/%s_ref.jpg" % name
            jpg(os.path.join(REFS, ref), os.path.join(out, d))
            key, fn = ref.split("/", 1)
            src = json.load(open(os.path.join(REFS, key, "sources.json"), encoding="utf-8")).get(fn, {})
            cap = '<a href="%s">%s</a> (%s)' % (html.escape(src.get("page") or ""), html.escape(fn), html.escape(src.get("licence") or "?"))
            cells.append((d, "reference photo: " + cap))
        else:
            cells.append((None, "no reference photo at this angle"))
        for st, lab in (("before", "before: GIS box"), ("after", "after: landmark model")):
            p = os.path.join(shots, "%s_%s.png" % (name, st))
            if os.path.isfile(p):
                d = "img/%s_%s.jpg" % (name, st)
                jpg(p, os.path.join(out, d))
                cells.append((d, lab))
            else:
                cells.append((None, lab + " (missing)"))
        rows.append((name, cells))
    gpu = sj.get("gpu", [])
    lm = rep.get("landmarks", [])
    H = ['<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>Busan landmarks</title><style>',
         ':root{--bg:#fff;--fg:#1b1b1b;--mut:#666;--line:#ddd}@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--mut:#aaa;--line:#333}}',
         'body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1600px;padding:16px}',
         'table{border-collapse:collapse;width:100%;margin:8px 0 20px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top;font-size:13px}',
         '.row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:6px 0 22px}.row img{width:100%;display:block;border-radius:4px}',
         '.cap{font-size:12px;color:var(--mut)}h2{margin:18px 0 4px;font-size:17px}a{color:inherit}</style></head><body>',
         '<h1>부산 랜드마크 3D 모델 — 사진 vs 렌더</h1>',
         '<p>만든 시각 %s · 렌더 %s (언리얼 오프스크린, 서버 없이, 로컬 지형·캐시 사진). 왼쪽 = 참고 사진(같은 건물, 비슷한 방향 — 시점·렌즈·날씨는 다름), 가운데 = 지금(GIS 상자), 오른쪽 = 랜드마크 모델.</p>'
         % (time.strftime("%Y-%m-%d %H:%M"), html.escape(sj.get("made", "?"))),
         '<h2>모델 목록</h2><table><tr><th>key</th><th>이름</th><th>높이 m</th><th>삼각형</th><th>glb KB</th><th>바닥 출처</th><th>대체한 GIS 수</th></tr>']
    for r in lm:
        H.append("<tr><td>%s</td><td>%s</td><td>%.1f</td><td>%d</td><td>%d</td><td>%s</td><td>%d</td></tr>" % (
            r["key"], html.escape(r["name"]), r["top_m"], r["triangles"], r["glb_kb"], html.escape(", ".join(f.split(":")[0] for f in r["foot"])), len(r["replaced"])))
    H.append("</table>")
    if gpu:
        H.append("<h2>GPU (1080p 화소 환산)</h2><table><tr><th>view</th><th>state</th><th>GPU ms</th></tr>")
        for g in gpu:
            H.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (g["view"], g["state"], g.get("gpu_ms")))
        H.append("</table>")
    for name, cells in rows:
        H.append("<h2>%s</h2><div class='row'>" % html.escape(name))
        for d, cap in cells:
            H.append("<div>%s<div class='cap'>%s</div></div>" % ('<img loading="lazy" src="%s">' % d if d else "<div class='cap'>—</div>", cap))
        H.append("</div>")
    H.append("</body></html>")
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write("\n".join(H))
    print("page ->", os.path.join(out, "index.html"))


if __name__ == "__main__":
    main(*sys.argv[1:])
