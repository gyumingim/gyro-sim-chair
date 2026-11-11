"""Building-grounding study: preview page (local only, images stay outside git: they show V-World imagery).

    python sim/grounding/build_page.py ROOT PAGE_DIR [UE_AB.json]

ROOT = the render folder (metrics.json, summary.json, png/), PAGE_DIR = .../page/today/busan_grounding_study.
UE_AB.json (optional, ue_ab.py): in-game A/B shots + GPU numbers for GYROSIM_BLDG_CONTACT.
"""
import html, json, os, shutil, sys, time
import numpy as np

SCANS = [
    ("tum", "TUM Downtown Campus (뮌헨, UAV 사진측량 메시)", "https://zenodo.org/records/15282970", "CC BY 4.0",
     "TUM2TWIN / Technical University of Munich, 2024-12-17 촬영 (겨울 낮은 해: 텍스처에 긴 그림자가 구워져 있음)"),
    ("avenue", "Avenue Rd - Drone Photogrammetry (영국 주택가 블록)", "https://zenodo.org/records/10324567", "CC BY 4.0",
     "continuumtoon (Sketchfab, Objaverse 미러), RealityCapture 128장. 단위 = 원본 좌표를 m 로 가정 (층 높이로 보아 맞음, 추정)"),
]
NAMES = {
    "full": "스캔 그대로 (Cycles: 하늘 가림 + 반사광 + 해 그림자)",
    "ao_off": "AO 끔 (하늘빛 안 가림, 반사광 없음 = UE Lumen 이 Cesium 건물을 못 볼 때와 같은 빛)",
    "shadow_off": "해 그림자 끔",
    "ground_flat": "땅 텍스처를 한 가지 색으로 (텍스처에 구워진 발밑 어둠 제거)",
    "ortho_swap": "땅 텍스처를 '정사가 아닌 사진' 으로 (12° 기울여 위에서 찍은 자기 사진: 지붕·벽이 옆 땅에 그려짐)",
    "ourcase": "AO 끔 + 정사 아닌 사진 = 스캔으로 만든 '우리 상황'",
    "base": "지금 우리 (UE 식 빛 + 지금의 벽 발밑 어둡게 f3)",
    "rt": "참고: 우리 장면에 진짜 GI (Lumen 이 건물을 본다면)",
    "fa": "(a) 발자국+2 m+기울기 구역의 사진을 평평한 그늘색으로 덮음",
    "fam": "(a') 같은 구역의 사진을 ×0.5 어둡게 (무늬 유지)",
    "fb": "(b) 접지 띠 1 − 0.4·exp(−d / 3 m)",
    "fb_s": "(b) 접지 띠 강하게 1 − 0.55·exp(−d / 6 m)",
    "fc": "(c) 벽 발밑 더 어둡게 1 − 0.45·exp(−z / 4 m)",
    "fd": "(d) a + b + c",
    "fab": "a + b", "fabm": "a' + b", "fabm_s": "a' + b(0.5, 5 m)", "fabm_s2": "a'(×0.4) + b(0.55, 6 m)",
    "fabmc_s": "a' + b(0.5, 5 m) + c",
    "fabmc_s2": "추천: a'(×0.4) + b(0.55, 6 m) + c",
}
COLS = [("gap", "차이 점수"), ("ground_contact", "땅 접지 대비"), ("ground_contact_lit", "땅 접지 (해 비치는 곳)"),
        ("ground_contact_alb", "땅 접지 (텍스처만)"), ("facade_foot", "벽 발밑"), ("base_step", "벽발밑−옆땅"),
        ("chroma_diff", "색 차이"), ("ghost", "옆땅 무늬")]


def fmt(x, k):
    if x is None or not np.isfinite(x):
        return "-"
    return "%.2f" % x


def main(root, page, ue=None):
    os.makedirs(os.path.join(page, "img"), exist_ok=True)
    S = json.load(open(os.path.join(root, "summary.json"), encoding="utf-8"))
    T = S["table"]
    pngs = os.path.join(root, "png")

    def img(name, cap):
        src = os.path.join(pngs, name)
        if not os.path.exists(src):
            return ""
        shutil.copyfile(src, os.path.join(page, "img", name))
        return "<figure><img loading='lazy' src='img/%s'><figcaption>%s</figcaption></figure>" % (name, html.escape(cap))

    def mean_gap(k):
        return float(np.mean(T[k]["gap_each"])) if k in T else float("nan")
    bg, best = mean_gap("busan|base"), mean_gap("busan|fabmc_s2")
    H = []
    H.append("""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>건물 접지 연구</title><style>
:root{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--good:#1a7f37;--bad:#c62828}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--good:#5fd38a;--bad:#ff8a80}}
:root[data-theme=dark]{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--good:#5fd38a;--bad:#ff8a80}
body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;margin:0 auto;padding:0 16px 40px;max-width:900px}
img{width:100%;height:auto;display:block;border-radius:6px}figure{margin:8px 0 14px}figcaption{color:var(--mut);font-size:14px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:right;white-space:nowrap}
td:first-child,th:first-child{text-align:left;white-space:normal}h2{margin-top:32px;border-top:1px solid var(--line);padding-top:16px}
.box{background:rgba(127,127,127,.1);padding:10px 14px;border-radius:8px}.g{color:var(--good)}.b{color:var(--bad)}
</style></head><body>""")
    H.append("<h1>건물이 땅에 붙어 보이게 하는 것: 사진측량 스캔 vs 부산</h1>")
    H.append("<p style='color:var(--mut)'>%s · Blender 4.5 Cycles (헤드리스), 해 고도 42°·방위 215°, 카메라 3방향 (해 등지고 / 옆 / 45° 역광), 1280×720</p>" % time.strftime("%Y-%m-%d %H:%M"))
    H.append("""<div class='box'><b>결론</b><ol>
<li>스캔에서 건물 옆 땅이 어두운 이유는 두 가지다. <b>(1) 해 그림자</b>: 끄면 땅 접지 대비 (발자국 1–2.5 m ÷ 15–30 m) 가 −3.05 → −1.51 (TUM), −2.25 → −1.19 (Avenue) stop. <b>(2) 텍스처에 구워진 어둠</b>: 건물 옆 땅의 텍스처 자체가 먼 땅보다 1.4 stop 어둡다 (두 스캔 모두). 해 비치는 땅만 보면 이것이 전부다 (땅을 한 색으로 바꾸면 −1.68 → −0.10, −0.81 → 0.00). 단 TUM 은 12월 촬영이라 이 '구운 어둠' 의 상당 부분이 찍을 때의 긴 그림자일 수 있음 (추정).</li>
<li><b>AO (하늘 가림 + 반사광)</b> 은 장면에 따라 다르다: TUM (좁은 안뜰) −3.05 → −2.28, Avenue (낮은 주택) −2.25 → −2.29. 해 비치는 땅에서는 0.1 stop 안팎.</li>
<li>우리 사진: 서면은 건물 옆 땅이 먼 땅보다 <b>밝다</b> (해 비치는 곳 +0.23 ~ +0.28, 3장), 광안은 약간 어둡다 (−0.3 / −0.6). 스캔은 −0.8 ~ −1.7. 정사가 아닌 사진이라 건물 자기 지붕·벽이 옆 땅에 그려지는 탓으로 보인다: 스캔 (TUM, 높은 건물) 에 같은 종류의 사진을 넣으면 −1.68 → −0.59 로 무너진다. 낮은 Avenue 에서는 변화 없음 (−0.81 → −0.81) — 높은 건물에서만 생기는 문제.</li>
<li>가장 잘 듣는 고침 = <b>땅 + 벽 같이</b>: 발자국 + 2 m + 기울기 구역의 사진을 ×0.4 어둡게 (무늬 유지) + 접지 띠 1 − 0.55·exp(−d/6 m) + 벽 발밑 1 − 0.45·exp(−z/4 m). 스캔과의 차이 점수 %.2f → %.2f (%.0f %%, 6장 평균, 6장 모두 좋아짐). 하나만으로는 땅 사진 어둡게 (a') 와 강한 접지 띠 (b) 가 비슷하고 (%.2f / %.2f), 벽 발밑만 (c) 은 1.80: 벽 발밑은 스캔 쪽으로 가지만 벽과 옆 땅의 단차가 커져 상쇄된다 → 땅을 같이 어둡게 해야 한다.</li>
<li>참고: Lumen 이 건물을 보게 해도 (진짜 GI) %.2f → %.2f. 땅 고침 하나와 비슷한 크기다.</li>
</ol></div>""" % (bg, best, 100 * (best - bg) / bg, mean_gap("busan|fam"), mean_gap("busan|fb_s"), bg, mean_gap("busan|rt")))
    if ue:
        H.append("<h2>UE 적용 (GYROSIM_BLDG_CONTACT)</h2>")
        H.append("<div class='box'>%s</div>" % ue.get("summary_html", ""))
        if ue.get("gpu"):
            H.append("<div class='tw'><table><tr><th>장면</th><th>끔 (ms)</th><th>켬 (ms)</th><th>차이</th></tr>")
            for r in ue["gpu"]:
                H.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % tuple(html.escape(str(x)) for x in r))
            H.append("</table></div>")
        for s in ue.get("shots", []):
            nm = os.path.basename(s["path"])
            shutil.copyfile(s["path"], os.path.join(page, "img", nm))
            H.append("<figure><img loading='lazy' src='img/%s'><figcaption>%s</figcaption></figure>" % (nm, html.escape(s["cap"])))
    H.append("<h2>쓴 스캔 (내려받기·로그인 없음)</h2><div class='tw'><table><tr><th>스캔</th><th>라이선스</th><th>출처</th></tr>")
    for k, nm, url, lic, note in SCANS:
        H.append("<tr><td>%s<br><span style='color:var(--mut)'>%s</span></td><td>%s</td><td><a href='%s'>%s</a></td></tr>" % (html.escape(nm), html.escape(note), lic, url, url.split("//")[1]))
    H.append("</table></div><p style='color:var(--mut)'>검토 후 안 씀: Helsinki Kalasatama (Zenodo 7599228, CC BY 4.0) = 6 GB zip 안에 3천만 면 OBJ 하나 (이 PC 로 다루기 무거움). Sketchfab 직접 = 로그인 필요. Google 3D Tiles = 약관상 추출 금지. 스캔 파일: C:/GyroSimTiles/refs/scan3d/ (git 밖)</p>")
    H.append("<h2>무엇을 쟀나</h2><p>모든 장면 (스캔·부산) 을 같은 방법으로: 위에서 0.5 m 간격으로 광선을 쏴 표면 높이를 만들고, 땅 높이 (스캔은 점진 형태학 필터, 부산은 지형 메시) 와 건물 마스크를 정한 뒤 픽셀마다 땅 위 높이·발자국까지 거리를 렌더 패스로 뽑았다. 밝기는 모두 stop (log2 중앙값) 이라 노출과 무관.</p>")
    H.append("<ul><li><b>땅 접지 대비</b>: 발자국에서 1–2.5 m 땅 ÷ 15–30 m 땅 (건물 마스크를 1 m 넓혀서 실제 1 m 부터). (해 비치는 곳만 / 텍스처만 따로)</li><li><b>벽 발밑</b>: 벽 0–3 m ÷ 6–20 m</li><li><b>벽발밑−옆땅</b>: 벽 0–2 m ÷ 땅 1–2 m (경계의 단차, 0 = 이어짐)</li><li><b>색 차이</b>: 벽 발밑과 옆 땅의 색도 거리 ×100</li><li><b>옆땅 무늬</b>: 땅 0–6 m 의 잔무늬 세기 ÷ 먼 땅</li><li><b>차이 점수</b>: 위 항목들이 스캔 6장 중앙값에서 얼마나 먼지 (스캔 사이 퍼짐으로 나눔) 의 평균. 스캔끼리도 0.5–0.7 정도 차이가 남 (목표에 자기 자신이 들어간 값이라 실제 바닥 잡음은 더 클 수 있음).</li></ul>")
    H.append(img("tum__v2__classes.jpg", "분류 확인 (TUM, 옆에서): 빨강 = 벽, 노랑 = 발자국 0–2.5 m 땅, 파랑 = 15–30 m 땅"))
    H.append(img("seomyeon__v2__classes.jpg", "분류 확인 (서면)"))
    # metric table
    H.append("<h2>숫자 (stop, 6장 또는 3장의 중앙값)</h2><div class='tw'><table><tr><th>장면 | 변형</th>" + "".join("<th>%s</th>" % c for _, c in COLS) + "</tr>")
    H.append("<tr><td><b>목표 = 스캔 그대로 6장 중앙값</b></td><td></td>" + "".join("<td>%s</td>" % fmt(S["target"].get(k), k) for k, _ in COLS[1:]) + "</tr>")
    order = [("tum", v) for v in ("full", "ao_off", "shadow_off", "ground_flat", "ortho_swap", "ourcase")] + \
            [("avenue", v) for v in ("full", "ao_off", "shadow_off", "ground_flat", "ortho_swap", "ourcase")] + \
            [("busan", v) for v in ("base", "rt", "fa", "fam", "fb", "fb_s", "fc", "fd", "fabm_s", "fabmc_s", "fabmc_s2")]
    for sc, v in order:
        k = "%s|%s" % (sc, v)
        if k not in T:
            continue
        t = T[k]
        row = ["%.2f" % np.mean(t["gap_each"])] + [fmt(t.get(c), c) for c, _ in COLS[1:]]
        bold = v in ("full", "base", "fabmc_s2")
        H.append("<tr><td>%s%s | %s%s</td>" % ("<b>" if bold else "", sc, html.escape(NAMES.get(v, v)), "</b>" if bold else "") + "".join("<td>%s</td>" % x for x in row) + "</tr>")
    H.append("</table></div><p style='color:var(--mut)'>차이 점수 = 렌더마다 계산한 점수의 평균 (부산 = 광안·서면 × 3방향 = 6장). 반복 렌더 없음 (Cycles 96 샘플 + 디노이즈, 같은 시드라 반복해도 같음). 고침 값 몇 개는 이 점수를 보며 골랐으므로 (8개 조합) 최종 수치는 약간 낙관적일 수 있음 (추정).</p>")
    # scan images
    for sc, nm, *_ in SCANS:
        H.append("<h2>%s</h2>" % html.escape(nm))
        for v in ("v1", "v2", "v3"):
            H.append(img("%s__%s__full.jpg" % (sc, v), "%s %s: 스캔 그대로" % (sc, v)))
        for var in ("ao_off", "shadow_off", "ground_flat", "ortho_swap", "ourcase"):
            H.append(img("%s__v2__%s.jpg" % (sc, var), "%s v2: %s" % (sc, NAMES[var])))
    for sc, nm in (("gwangan", "부산 광안 (n5 사용자 화면 쪽)"), ("seomyeon", "부산 서면")):
        H.append("<h2>%s: 지금 → 고침</h2>" % nm)
        for v in ("v2", "v1", "v3"):
            for var in ("base", "fabmc_s2") if v != "v2" else ("base", "rt", "fa", "fam", "fb_s", "fc", "fd", "fabmc_s2"):
                H.append(img("%s__%s__%s.jpg" % (sc, v, var), "%s %s: %s" % (sc, v, NAMES.get(var, var))))
    H.append("""<h2>한계 · 가정</h2><ul>
<li>고친 버그 (11-12 08:00): 첫 렌더에서는 땅 고침이 건물 마스크 (발자국보다 1 m 넓음) 밖에만 칠해져 건물 둘레에 고침 안 된 1 m 띠가 밝게 남았다 (감독자 지적). 땅 = '낮고 위를 향한 면' 으로 고쳐 모든 렌더를 다시 돌렸고 이 페이지의 숫자는 다시 돌린 것.</li><li>Blender 의 부산 장면은 UE 와 같지 않다: 벽은 glTF 창문 아틀라스 + 정점색 (UE 의 절차 벽 셰이더 아님), f3 벽 어둡게는 같은 식으로 따라 함, 하늘빛 = 고르게 (UE 하늘 아님). 비교는 '어느 고침이 스캔 쪽으로 가나' 에만 쓴다.</li>
<li>스캔 텍스처에는 찍을 때의 그림자·흐림이 구워져 있다 (TUM = 12월, 해 낮음). 이 '구운 어둠' 이 바로 실사진의 접지감이지만, 해 방향이 우리 해와 다를 수 있다.</li>
<li>스캔 2개뿐 (도심 캠퍼스 1, 주택가 1). 한국 도심 스캔은 무료·무로그인으로 찾지 못함.</li>
<li>'먼 땅 (15–30 m)' 에 넓은 도로가 많으면 접지 대비가 커진다 (도로가 밝음). 스캔·부산 둘 다 같은 자.</li>
<li>점수 상한: 항목마다 3 에서 자름. 색 차이 (부산 4.2 vs 스캔 2.0) 는 벽 셰이더 차이라 고침과 무관한 고정 몫. 광안 v3 는 먼 땅이 적어 일부 항목이 빠짐. 접지 띠 폭 (band_w) 은 스캔이 15 m 안에 회복하지 않아 사실상 이진값.</li>
<li>V-World 사진은 캐시에서 메모리로만 읽었고 저장·커밋하지 않음 (이 페이지의 부산 그림은 미리보기).</li></ul>""")
    H.append("<p style='color:var(--mut)'>스크립트: sim/grounding/ (busan_scene · render_study · classify · analyse · build_page). 렌더·수치: %s</p></body></html>" % html.escape(root))
    open(os.path.join(page, "index.html"), "w", encoding="utf-8").write("\n".join(H))
    print("page", os.path.join(page, "index.html"))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], json.load(open(a[2], encoding="utf-8")) if len(a) > 2 else None)
