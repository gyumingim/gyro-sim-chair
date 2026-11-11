"""A/B pick page for the leaf-card trees vs the old blob trees (copy of sim/impostor/pick_page.py, same format).

    python -I sim/veg_cards_pick.py <shots dir> <page dir> <key json>
Shots: <view>_blob.png / <view>_cards.png from Scripts/trees_near_shots.py (states blob,cards). Per view: the whole
picture + 2 crops (2x). A/B order random (seed below); the answer key goes to <key json> (outside the served page).
Pictures contain V-World imagery -> page and key stay outside git.
"""
import json, os, random, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
import cv2                                                              # noqa: E402

VIEWS = ["hwang_low", "park_low", "jang_mid"]
CROPS = [(0.20, 0.30, 0.5), (0.45, 0.45, 0.5)]                           # (x0, y0, size) as fractions of the width / height


def main(shots, page, keyf):
    img = os.path.join(page, "img"); os.makedirs(img, exist_ok=True)
    rng = random.Random(1212)
    qs, key = [], {}
    for v in VIEWS:
        pics = {s: cv2.imread(os.path.join(shots, "%s_%s.png" % (v, s))) for s in ("blob", "cards")}
        if any(p is None for p in pics.values()):
            print("missing", v); continue
        variants = [("full", None)] + [("crop%d" % i, c) for i, c in enumerate(CROPS)]
        for nm, c in variants:
            q = "q%02d" % (len(qs) + 1)
            order = ["blob", "cards"]; rng.shuffle(order)
            for lab, s in zip("AB", order):
                p = pics[s]
                if c is not None:
                    H, W = p.shape[:2]
                    x0, y0, sz = int(c[0] * W), int(c[1] * H), c[2]
                    p = cv2.resize(p[y0:y0 + int(sz * H), x0:x0 + int(sz * W)], (W, H), interpolation=cv2.INTER_LANCZOS4)
                cv2.imwrite(os.path.join(img, "%s_%s.jpg" % (q, lab)), p, [cv2.IMWRITE_JPEG_QUALITY, 90])
            key[q] = dict(view=v, part=nm, A=order[0], B=order[1])
            qs.append((q, v, nm))
    n = len(qs)
    H = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>부산 나무 고르기</title><style>",
         ":root{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--btn:#eee;--on:#1a73e8}",
         "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--btn:#222;--on:#5b9cff}}",
         ":root[data-theme=dark]{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--btn:#222;--on:#5b9cff}",
         "body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0 auto;padding:0 16px 60px;max-width:1100px}",
         "img{width:100%;height:auto;display:block;border-radius:6px;margin:6px 0 2px}",
         ".q{border-top:1px solid var(--line);padding-top:12px;margin-top:22px}.lab{font-weight:700;font-size:18px}",
         ".bt{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}button{font:inherit;padding:10px 16px;border-radius:8px;border:1px solid var(--line);background:var(--btn);color:var(--fg);flex:1;min-width:90px}",
         "button.on{background:var(--on);color:#fff;border-color:var(--on)}textarea{width:100%;height:160px;font:14px monospace;background:var(--btn);color:var(--fg)}",
         "</style></head><body><h1>부산 나무: 어느 쪽이 진짜 숲 같나</h1>",
         "<p style='color:var(--mut)'>장면마다 A, B 두 장 (게임 화면, 같은 자리·같은 빛). 어느 쪽 나무가 더 진짜 부산 산 같은지 고르세요. "
         "A/B 순서는 무작위. 확대 장면은 같은 그림의 일부를 2 배로 키운 것. 고른 것은 이 브라우저에 저장됨. 다 고르면 맨 아래 '결과 복사'.</p>"]
    for i, (q, v, nm) in enumerate(qs):
        H.append("<div class='q' id='%s'><div class='lab'>%d / %d</div><div>A</div><img src='img/%s_A.jpg' loading='lazy' alt='A'>"
                 "<div>B</div><img src='img/%s_B.jpg' loading='lazy' alt='B'><div class='bt'><button data-q='%s' data-v='A'>A가 낫다</button>"
                 "<button data-q='%s' data-v='B'>B가 낫다</button><button data-q='%s' data-v='='>같음</button></div></div>" % (q, i + 1, n, q, q, q, q, q))
    H.append("<div class='q'><button id='cp'>결과 복사</button><p id='st' style='color:var(--mut)'></p><textarea id='out' readonly></textarea></div>")
    H.append("<script>\nvar K='busan_pick_trees_cards_v1',P={};try{P=JSON.parse(localStorage.getItem(K)||'{}')}catch(e){}\n"
             "function paint(){document.querySelectorAll('button[data-q]').forEach(function(b){b.classList.toggle('on',P[b.dataset.q]===b.dataset.v)});\n"
             "document.getElementById('st').textContent=Object.keys(P).length+' / %d 고름'}\n"
             "document.querySelectorAll('button[data-q]').forEach(function(b){b.onclick=function(){P[b.dataset.q]=b.dataset.v;try{localStorage.setItem(K,JSON.stringify(P))}catch(e){}paint()}});\n"
             "document.getElementById('cp').onclick=function(){var t='busan_pick_trees_cards: '+Object.keys(P).sort().map(function(k){return k+'='+P[k]}).join(' ');\n"
             "var o=document.getElementById('out');o.value=t;o.select();try{navigator.clipboard.writeText(t)}catch(e){}};paint();\n</script></body></html>" % n)
    open(os.path.join(page, "index.html"), "w", encoding="utf-8").write("\n".join(H))
    os.makedirs(os.path.dirname(keyf), exist_ok=True)
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), shots=shots, page=page, key=key,
                   note="blob = old round tiles (GYROSIM_TREES_CARDS=0), cards = leaf-card trees (tiles_cards + M_GyroTreeCard)"), open(keyf, "w"), indent=1)
    print("page", page, "questions", n, "key", keyf)


if __name__ == "__main__":
    main(*sys.argv[1:4])
