"""A/B pick page for the photo relief (docs/photo-relief-busan.md), same format as sim/impostor/pick_page.py.

    python -I sim/relief_pick_page.py <shots dir> <page dir> <key json>
Shots: <view>_off.png / <view>_on.png + shots.json from Scripts/relief_shots.py. Per view: the whole picture + 2 crops
(2x). A/B order random (seed below); the answer key goes to <key json> (outside the served page). Pictures contain
V-World imagery -> page and key stay outside git. Measurements (GPU, frame time) are listed below the questions.
"""
import json, os, random, sys, time
from PIL import Image

VIEWS = [("road_haeundaero", "해운대 해변로 (차·중앙분리대)"), ("beach_gwangalli", "광안리 해변 (파라솔·모래)"),
         ("houses_nomesh", "기장 주택단지 (3D 건물 없는 곳)"), ("houses_haeundae", "우동 주택가 (3D 건물 많은 곳)")]
CROPS = [(0.25, 0.40, 0.5), (0.50, 0.45, 0.5)]                    # (x0, y0, size) as fractions of the width / height
KEY = "busan_pick_relief_v1"


def main(shots, page, keyf):
    img = os.path.join(page, "img"); os.makedirs(img, exist_ok=True)
    rng = random.Random(1112)
    qs, key = [], {}
    for v, label in VIEWS:
        pics = {}
        for s in ("off", "on"):
            p = os.path.join(shots, "%s_%s.png" % (v, s))
            if os.path.exists(p):
                pics[s] = Image.open(p).convert("RGB")
        if len(pics) < 2:
            print("missing", v); continue
        for nm, c in [("full", None)] + [("crop%d" % i, c) for i, c in enumerate(CROPS)]:
            q = "q%02d" % (len(qs) + 1)
            order = ["off", "on"]; rng.shuffle(order)
            for lab, s in zip("AB", order):
                p = pics[s]
                W, H = p.size
                if c is not None:
                    x0, y0 = int(c[0] * W), int(c[1] * H)
                    p = p.crop((x0, y0, x0 + int(c[2] * W), y0 + int(c[2] * H))).resize((W, H), Image.LANCZOS)
                p.save(os.path.join(img, "%s_%s.jpg" % (q, lab)), quality=88)
            key[q] = dict(view=v, part=nm, A=order[0], B=order[1])
            qs.append((q, label, nm))
    meas = ""
    try:
        r = json.load(open(os.path.join(shots, "shots.json"), encoding="utf-8"))
        rows = ["<tr><td>%s %s</td><td>%s</td></tr>" % (g["view"], g["variant"], g.get("gpu_ms")) for g in r.get("gpu", [])]
        rows += ["<tr><td>비행 80 m/s, 입체 %s</td><td>평균 %s / p95 %s / p99 %s ms (타일 %s장)</td></tr>" %
                 ("켬" if f["variant"] == "on" else "끔", f.get("mean_ms"), f.get("p95_ms"), f.get("p99_ms"), f.get("tiles_drawn")) for f in r.get("fly", [])]
        meas = ("<h2>측정 (같은 PC, 화면 밖 에디터, 1회)</h2><table>%s</table><p class='m'>GPU = fpschart 10 초, 1920x1080 화소. "
                "비행 = 프레임 시간 (게임 스레드 포함), 새 타일 추론·그리기 중.</p>" % "".join(rows))
    except Exception as e:
        print("no shots.json", e)
    n = len(qs)
    H = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>사진 입체 고르기</title><style>",
         ":root{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--btn:#eee;--on:#1a73e8}",
         "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--btn:#222;--on:#5b9cff}}",
         ":root[data-theme=dark]{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--btn:#222;--on:#5b9cff}",
         "body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0 auto;padding:0 16px 60px;max-width:1100px}",
         "img{width:100%;height:auto;display:block;border-radius:6px;margin:6px 0 2px}.m{color:var(--mut);font-size:14px}",
         ".q{border-top:1px solid var(--line);padding-top:12px;margin-top:22px}.lab{font-weight:700;font-size:18px}",
         "table{border-collapse:collapse;width:100%;font-size:14px}td{border-bottom:1px solid var(--line);padding:4px}",
         ".bt{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}button{font:inherit;padding:10px 16px;border-radius:8px;border:1px solid var(--line);background:var(--btn);color:var(--fg);flex:1;min-width:90px}",
         "button.on{background:var(--on);color:#fff;border-color:var(--on)}textarea{width:100%;height:120px;font:14px monospace;background:var(--btn);color:var(--fg)}",
         "</style></head><body><h1>부산 땅 사진 입체: 어느 쪽이 더 진짜 같나</h1>",
         "<p class='m'>장면마다 A, B 두 장 (게임 화면, 같은 자리·같은 빛, 고도 80–190 m). 하나는 위성사진 그대로, 하나는 사진에서 높이를 추정해 "
         "땅에 굴곡·그림자를 넣은 것 (차·파라솔·작은 집·나무). A/B 순서는 무작위. 확대 장면은 같은 그림 일부를 2 배로 키운 것. "
         "고른 것은 이 브라우저에만 저장됨. 다 고르면 맨 아래 '결과 복사'. 그림은 V-World 사진으로 만든 것이라 이 PC 의 임시 폴더에만 있음.</p>"]
    for i, (q, label, nm) in enumerate(qs):
        H.append("<div class='q' id='%s'><div class='lab'>%d / %d · %s%s</div><div>A</div><img src='img/%s_A.jpg' loading='lazy' alt='A'>"
                 "<div>B</div><img src='img/%s_B.jpg' loading='lazy' alt='B'><div class='bt'><button data-q='%s' data-v='A'>A가 낫다</button>"
                 "<button data-q='%s' data-v='B'>B가 낫다</button><button data-q='%s' data-v='='>같음</button></div></div>"
                 % (q, i + 1, n, label, "" if nm == "full" else " (확대)", q, q, q, q, q))
    H.append("<div class='q'><button id='cp'>결과 복사</button><p id='st' class='m'></p><textarea id='out' readonly></textarea></div>")
    H.append(meas)
    H.append("<script>\nvar K='%s',P={};try{P=JSON.parse(localStorage.getItem(K)||'{}')}catch(e){}\n"
             "function paint(){document.querySelectorAll('button[data-q]').forEach(function(b){b.classList.toggle('on',P[b.dataset.q]===b.dataset.v)});\n"
             "document.getElementById('st').textContent=Object.keys(P).length+' / %d 고름'}\n"
             "document.querySelectorAll('button[data-q]').forEach(function(b){b.onclick=function(){P[b.dataset.q]=b.dataset.v;try{localStorage.setItem(K,JSON.stringify(P))}catch(e){}paint()}});\n"
             "document.getElementById('cp').onclick=function(){var t='%s: '+Object.keys(P).sort().map(function(k){return k+'='+P[k]}).join(' ');\n"
             "var o=document.getElementById('out');o.value=t;o.select();try{navigator.clipboard.writeText(t)}catch(e){}};paint();\n</script></body></html>" % (KEY, n, KEY))
    open(os.path.join(page, "index.html"), "w", encoding="utf-8").write("\n".join(H))
    os.makedirs(os.path.dirname(keyf), exist_ok=True)
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), shots=shots, page=page, key=key,
                   note="off = GYROSIM_PHOTO_DEPTH=0 look (RelF.w 0), on = photo relief (default)"), open(keyf, "w"), indent=1)
    print("page", page, "questions", n, "key", keyf)


if __name__ == "__main__":
    main(*sys.argv[1:4])
