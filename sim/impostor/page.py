"""Preview page for the impostor trees (11-11): real full-mesh renders vs software impostor renders + game shot + photos.

    python -I sim/impostor/page.py <page dir>
Inputs: C:\\GyroSimTiles\\assets\\trees_impostor\\ (real/*.png from Blender, imp/*.png from pipeline.py --imp, atlases),
C:\\GyroSimTiles\\shots\\trees_near\\hwang_low_blob.png, C:\\GyroSimTiles\\refs\\trees_shape\\ (photos + refs.json).
The page and its pictures stay outside git (photos, screenshots, Fab-derived pictures).
"""
import json, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                      # noqa: E402
import cv2                                                              # noqa: E402
import pipeline as P                                                    # noqa: E402

REFS = r"C:\GyroSimTiles\refs\trees_shape"
GAME_SHOT = r"C:\GyroSimTiles\shots\trees_near\hwang_low_blob.png"
PHOTOS = ["Landscape_of_Busan_from_Hwangryeongsan.jpg", "View_of_Busan_from_Geumjeong_Mountain.jpg",
          "Geumjeong_Mountain_in_Busan_2.jpg", "Pinus_densiflora_forest_in_Seoul__South_Korea.jpg"]


def rgba_on(p, bg=0.55):
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if im is None:
        return np.full((480, 480, 3), 255, np.uint8)
    if im.ndim == 3 and im.shape[2] == 4:
        a = im[..., 3:4].astype(np.float32) / 255
        im = (im[..., :3].astype(np.float32) * a + bg * 255 * (1 - a)).astype(np.uint8)
    return im


def label(im, txt):
    im = im.copy()
    cv2.rectangle(im, (0, 0), (14 + 14 * len(txt), 34), (0, 0, 0), -1)
    cv2.putText(im, txt, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return im


def jpg(im, path, w=None):
    if w and im.shape[1] > w:
        im = cv2.resize(im, (w, int(im.shape[0] * w / im.shape[1])), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path, im, [cv2.IMWRITE_JPEG_QUALITY, 88])


CSS = ("<style>:root{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--box:#f4f4f4}"
       "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--box:#1c1c1c}}"
       ":root[data-theme=dark]{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--box:#1c1c1c}"
       "body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;margin:0 auto;padding:0 16px 60px;max-width:1100px}"
       "img{width:100%;height:auto;display:block;border-radius:6px}figure{margin:8px 0 18px}figcaption{color:var(--mut);font-size:14px}"
       "table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:5px;text-align:left}"
       ".box{background:var(--box);padding:10px 14px;border-radius:8px}.tw{overflow-x:auto}h2{margin-top:34px}.m{color:var(--mut)}</style>")


def build(page):
    img = os.path.join(page, "img"); os.makedirs(img, exist_ok=True)
    OUT = P.OUT
    R_, I_ = os.path.join(OUT, "real"), os.path.join(OUT, "imp")
    metas = {n: P.load_meta(n) for n in P.SPECIES}
    H = []; a = H.append
    a("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>")
    a("<title>부산 나무 임포스터</title>" + CSS + "</head><body>")
    a("<h1>부산 나무 — 받은 실제 모델로 만든 임포스터 (미리보기, 승인 대기)</h1>")
    a("<div class='box'><b>결론</b>: 받은 실제 모델 (Poly Haven 소나무·어린 소나무·전나무, Megascans 참나무·오리나무) 을 "
      "Blender 로 64 방향 (위쪽 반구 8×8) 에서 찍어 그림 묶음 (임포스터) 을 만듦. 굽기는 전체 메시라 잎이 빠지지 않음. "
      "게임에서는 나무 한 그루 = 카메라를 보는 카드 1 장 (삼각형 2 개). 각 항목의 첫 장 = <b>실제 모델</b> (Blender, 전체 메시), "
      "둘째 장 = <b>임포스터</b> (같은 카메라·해, 8비트 그림 묶음만으로 다시 그림). 아직 Unreal 에는 아무것도 안 넣음.</div>")
    a("<p class='m'>임포스터 그림은 Unreal 이 아닌 자체 소프트웨어 렌더 (게임 셰이더와 같은 방식: 가까운 4 방향 그림 섞기 + 깊이로 겹침 + "
      "해 그림자). 투과광·TAA·안개 없음. 실제 모델 그림은 Cycles (간접광 포함) 라 그늘 속이 조금 더 밝음. "
      "Megascans USD 에는 잎 텍스처가 없어 잎 색 = 단색 + 잎마다 무작위 밝기 (제가 넣은 것). Poly Haven 은 원래 텍스처. "
      "임포스터 쪽이 조금 밝고 누렇게 보임: Cycles 는 이웃 나무가 하늘빛을 가리는 것까지 계산하고, 임포스터는 나무 한 그루 안의 AO 만 가짐 "
      "(게임에서는 색·AO 세기로 맞출 부분). "
      "나무 높이는 부산 기준으로 맞춤 (소나무 10–16 m, 참나무 12–16 m, 오리나무 10–13 m).</p>")
    a("<h2>예상 비용 (추정, 아직 측정 안 함)</h2><div class='tw'><table><tr><th>항목</th><th>지금 (덩어리)</th><th>임포스터</th></tr>"
      "<tr><td>나무 1 그루 삼각형</td><td>150–400</td><td><b>2</b> (사각형 1 장)</td></tr>"
      "<tr><td>텍스처 (종류 1 개)</td><td>없음</td><td>2048² × 2 장 (색+투명 / 법선+깊이+AO), BC7+밉 ≈ <b>10.7 MB</b> (1024² 면 2.7 MB)</td></tr>"
      "<tr><td>텍스처 합계 (8 종류)</td><td>-</td><td>≈ 85 MB (2048²) / 21 MB (1024²)</td></tr>"
      "<tr><td>픽셀 비용</td><td>단순</td><td>픽셀마다 그림 4 장 × 텍스처 2 개 = 8 번 읽기 + 마스크 겹침 (낮게 날수록 큼)</td></tr>"
      "<tr><td>GPU ms (1080p)</td><td>hwang_low ≈ 5.0 ms</td><td><b>아직 안 잼</b> — 승인 뒤 측정, 목표 +1 ms 이내</td></tr></table></div>")
    a("<h2>비교용: 지금 게임 화면 · 실제 부산 산 사진</h2>")
    jpg(cv2.imread(GAME_SHOT), os.path.join(img, "game_hwang_low_blob.jpg"), 1280)
    a("<figure><img src='img/game_hwang_low_blob.jpg' loading='lazy'><figcaption>지금 게임 화면 (hwang_low, 덩어리 나무)</figcaption></figure>")
    for r in json.load(open(os.path.join(REFS, "refs.json"), encoding="utf-8")):
        if r["file"] in PHOTOS:
            jpg(cv2.imread(os.path.join(REFS, r["file"])), os.path.join(img, "ref_" + r["file"]), 1280)
            a("<figure><img src='img/ref_%s' loading='lazy'><figcaption>사진: %s — %s, %s (<a href='%s'>출처</a>)</figcaption></figure>"
              % (r["file"], r["place"], r["author"], r["licence"], r["source_page"]))

    def pair(key, cap):
        for kind, d, tag in (("실제 모델", R_, "real"), ("임포스터", I_, "imp")):
            p = os.path.join(d, key + ".png")
            if os.path.exists(p):
                jpg(rgba_on(p), os.path.join(img, "%s_%s.jpg" % (key, tag)), 1280)
                a("<figure><img src='img/%s_%s.jpg' loading='lazy'><figcaption>%s — <b>%s</b></figcaption></figure>" % (key, tag, cap, kind))
    a("<h2>부산 산처럼 섞은 숲 (소나무 70 %, 어린 소나무 10 %, 참나무·오리나무 20 %, 400 그루)</h2>")
    pair("mix_f100", "고도 100 m, 화각 50°")
    pair("mix_f300", "고도 300 m, 화각 25° (망원 = 게임 화면 가운데를 약 2 배 확대한 크기)")
    for gk, (title, mem, sp, lic) in P.GROUPS.items():
        m = metas[mem[0]]
        a("<h2>%s</h2><p class='m'>라이선스 %s · 원본 높이 %.1f m · 원본 삼각형 %s (가지 인스턴스 %d 개, 펼치기 전) · "
          "그림 묶음 %d×%d 방향 × %d px</p>" % (title, lic, m["hi"][2] - m["lo"][2], format(m["proto_tris"], ","),
                                            m["mesh_instances"], m["grid"], m["grid"], m["px"]))
        hp = os.path.join(R_, gk + "_hero.png")
        if os.path.exists(hp):
            jpg(rgba_on(hp), os.path.join(img, gk + "_hero.jpg"), 1000)
            a("<figure><img src='img/%s_hero.jpg' loading='lazy'><figcaption>실제 모델 (Blender Cycles, 전체 메시)</figcaption></figure>" % gk)
        tiles = [[label(rgba_on(os.path.join(d, "%s_ang%d.png" % (gk, i))), "%s %s" % (t, e))
                  for i, e in enumerate(("5deg", "30deg", "60deg", "top"))] for d, t in ((R_, "real"), (I_, "impostor"))]
        grid = np.concatenate([np.concatenate([np.concatenate(t[0:2], 1), np.concatenate(t[2:4], 1)], 0) for t in tiles], 0)
        jpg(grid, os.path.join(img, gk + "_angles.jpg"), 960)
        a("<figure><img src='img/%s_angles.jpg' loading='lazy'><figcaption>여러 각도 (올려 본 높이 5° / 30° / 60° / 바로 위). "
          "위 4 장 = 실제 모델, 아래 4 장 = 임포스터. 이 그림은 나무 1 그루가 화면 약 350 px 인 아주 가까운 거리라 "
          "방향마다 256 px 인 임포스터가 뭉개지고 얇은 줄기가 끊김 — 이 거리는 임포스터가 맡을 범위가 아님 (숲 그림 거리용)</figcaption></figure>" % gk)
        pair(gk + "_g16", "16 그루")
        pair(gk + "_f100", "400 그루 숲, 고도 100 m, 화각 50°")
        pair(gk + "_f300", "400 그루 숲, 고도 300 m, 화각 25° (망원)")
        jpg(rgba_on(os.path.join(OUT, m["textures"][0])), os.path.join(img, gk + "_atlas.jpg"), 900)
        a("<figure><img src='img/%s_atlas.jpg' loading='lazy'><figcaption>그림 묶음 (색, 64 방향): %s</figcaption></figure>"
          % (gk, m["textures"][0]))
    a("<h2>다음 (승인되면)</h2><ul><li>Unreal 에 새 나무 단계로 넣기 (Cesium 타일 나무 또는 인스턴스 카드 중 재서 싼 쪽), "
      "GYROSIM_TREES_IMPOSTOR=0 = 예전 모습</li><li>hwang_low / park_low / jang_mid 렌더, 1080p GPU ms 를 덩어리 (≈5.0 ms) 와 비교 "
      "(목표 +1 ms)</li><li>A/B 고르기 페이지</li></ul>")
    a("<p class='m' style='font-size:13px'>만든 시각 %s · 입력 %s · 스크립트 sim/impostor/ (bake_blender.py, pipeline.py, page.py). "
      "Megascans 에서 만든 그림 묶음은 Fab 라이선스 (UE 전용) 라 git 에 안 올림.</p></body></html>" % (time.strftime("%Y-%m-%d %H:%M"), OUT))
    open(os.path.join(page, "index.html"), "w", encoding="utf-8").write("\n".join(H))
    print("page", page)


if __name__ == "__main__":
    build(sys.argv[1])
