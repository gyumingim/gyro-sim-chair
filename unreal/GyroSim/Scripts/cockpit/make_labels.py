"""Korean label images for beginner mode (Unreal's canvas font has no Hangul, so the labels are pictures):
  Art/Cockpit/tex/T_CkLabels.png + labels.json   atlas of short labels (HUD callouts, display titles, row names),
                                                 drawn by hud.py next to the live numbers (white text, alpha = coverage)
  Art/Cockpit/tex/lbl_<name>.png                 one picture per panel callout (gauges, gear handle), placed as small
                                                 planes on the panel by build_level (tag BeginnerLabel)
Run (CPython + Pillow):  python make_labels.py      (Malgun Gothic; only rendered glyph images end up in the PNGs)
"""
import json, os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "Art", "Cockpit", "tex"))
FB = r"C:\Windows\Fonts\malgunbd.ttf"
FR = r"C:\Windows\Fonts\malgun.ttf"

# key: (text, bold). Drawn white; hud.py tints them (green on the HUD, colours on the displays).
LABELS = {
    # HUD callouts (beginner)
    "hud_spd": ("속도 kt", True), "hud_alt": ("고도 ft", True), "hud_agl": ("R 땅까지 ft", True),
    "hud_g": ("G 몸무게 배수", True), "hud_aoa": ("받음각", True), "hud_mach": ("마하", True),
    "hud_vs": ("상승률 ft/분", True), "hud_thr": ("스로틀 = 엔진 힘", True), "hud_gear": ("바퀴", True), "hud_brake": ("브레이크", True),
    "hud_hdg": ("방위", True), "hud_ladder": ("기수 각도 (5°)", True), "hud_fpm": ("○ 실제로 가는 방향", True),
    "hud_bore": ("— 기수 방향", True), "hud_horizon": ("수평선", True),
    # display titles / one-line explanations
    "pfd_t": ("비행 정보", True), "pfd_d": ("지금 비행기 상태 · 초록 정상 / 노랑 주의 / 빨강 위험", False),
    "train_t": ("훈련 화면", True), "train_d": ("목표와 지금 값의 차이 · 초록 = 범위 안", False),
    "ses_t": ("의자 · 경고", True), "ses_d": ("의자가 기울인 각도와 한계, 지금 켜진 경고", False),
    # row names
    "r_spd": ("속도", True), "r_alt": ("고도", True), "r_agl": ("땅까지", True), "r_vs": ("상승률", True), "r_hdg": ("방위", True),
    "r_g": ("G", True), "r_gmax": ("최대 G", True), "r_aoa": ("받음각", True), "r_mach": ("마하", True), "r_thr": ("스로틀", True),
    "r_gear": ("바퀴", True), "r_brk": ("브레이크", True), "r_time": ("비행 시간", True), "r_croll": ("의자 좌우", True), "r_cpitch": ("의자 앞뒤", True),
    "r_lim": ("한계", False), "r_rate": ("최대 움직임 속도 °/초", False), "r_warn": ("경고", True), "r_score": ("점수", True), "r_intol": ("범위 안", True),
    "r_trend": ("최근 30 초 · 가운데 초록 = 범위 안", False),
    "v_down": ("내려감", True), "v_up": ("올라감", True), "v_transit": ("움직이는 중", True), "v_on": ("걸림", True), "v_off": ("풀림", True),
    "v_high": ("5000 ft 넘음", True), "r_tgt": ("목표", False),
    # target names
    "t_ALT": ("고도", True), "t_HDG": ("방위", True), "t_BANK": ("경사", True), "t_VS": ("상승률", True), "t_SPD": ("속도", True),
    "t_PITCH": ("기수 각도", True), "t_CTR": ("중심선", True), "t_THR": ("스로틀", True), "t_G": ("G", True), "t_AIL": ("스틱 좌우", True),
    "t_ELEV": ("스틱 앞뒤", True), "t_RUD": ("페달", True), "t_BRK": ("브레이크", True),
    # session / warnings
    "s_paused": ("일시 정지 (P)", True), "s_loading": ("불러오는 중", True), "s_demo": ("시범 비행 중 — 자동 조종", True),
    "s_assist": ("쉬운 모드 켬", False), "s_slow": ("느린 시간 0.5배", False), "s_voice": ("교관 음성", False), "s_menu": ("메뉴 (F1)", False),
    "w_pullup": ("PULL UP — 땅이 가까워요, 당기세요!", True), "w_terrain": ("지형에 부딪혔어요", True),
    "w_overg": ("OVER-G — 스틱을 풀어요 (9G 넘음)", True), "w_stall": ("STALL — 실속! 스틱 밀고 스로틀 올려요", True),
    "w_gear": ("GEAR — 낮고 느린데 바퀴가 올라가 있어요", True), "w_none": ("경고 없음", False),
    "mode_beg": ("초보자 설명 켬 (L)", False),
    # readability pass (11-05): display row names carry their unit (no separate small unit text), short warning lines
    "d_spd": ("속도 (kt)", True), "d_alt": ("고도 (ft)", True), "d_vs": ("상승률 (ft/분)", True), "d_hdg": ("방위 (°)", True),
    "d_agl": ("땅까지 (ft)", True), "d_g": ("G (몸무게 배수)", True), "d_thr": ("스로틀", True), "d_gear": ("바퀴", True),
    "d_croll": ("의자 좌우 (°)", True), "d_cpitch": ("의자 앞뒤 (°)", True), "d_time": ("비행 시간", True),
    "wd_pullup": ("땅이 가까워요 — 당기세요!", True), "wd_terrain": ("지형에 부딪혔어요", True),
    "wd_overg": ("G 가 너무 커요 — 스틱을 풀어요", True), "wd_stall": ("실속 — 스틱 밀고 스로틀 올려요", True),
    "wd_gear": ("낮고 느린데 바퀴가 올라가 있어요", True), "wd_none": ("경고 없음", True),
}
# panel callouts (beginner): name -> (text, width cm, height cm)
CALLOUTS = {"adi": ("자세계 — 위 하늘 / 아래 땅, 기울기", 15.0, 1.7), "asi": ("속도계 (kt)", 7.6, 1.6), "alt": ("고도계 — 바다 기준 (ft)", 10.0, 1.6),
            "vsi": ("승강계 — 오르내리는 속도", 11.0, 1.6), "gear": ("↙ 바퀴 손잡이 (G 키)", 7.4, 1.6), "wheels": ("바퀴 등: 초록 = 내려감", 10.0, 1.6),
            "lights": ("상태등: 브레이크·쉬운 모드·느린 시간·음성", 12.0, 2.2), "mfd_l": ("비행 정보 화면", 9.0, 1.6), "mfd_r": ("의자·경고 화면", 9.0, 1.6),
            "mfd_c": ("훈련 화면 — 할 일과 점수", 13.0, 1.6), "mc": ("주의등 = 경고가 있으면 켜짐", 12.0, 1.6)}
PX = 48          # px per cm for the callouts


def atlas():
    W = 2048
    font_b, font_r = ImageFont.truetype(FB, 44), ImageFont.truetype(FR, 44)
    tmp = ImageDraw.Draw(Image.new("L", (8, 8)))
    rects, x, y, rowh = {}, 4, 4, 0
    sized = []
    for k, (t, b) in LABELS.items():
        f = font_b if b else font_r
        bb = tmp.textbbox((0, 0), t, font=f)
        w, h = bb[2] - bb[0] + 12, 60
        if x + w > W - 4:
            x, y = 4, y + rowh + 6
            rowh = 0
        rects[k] = [x, y, w, h]
        sized.append((k, t, f, x, y, bb))
        x += w + 6
        rowh = max(rowh, h)
    H = 1
    while H < y + rowh + 8:
        H *= 2
    im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for k, t, f, x0, y0, bb in sized:
        d.text((x0 + 6 - bb[0], y0 + 30), t, font=f, fill=255, anchor="lm")
    im.putalpha(m)
    im.save(os.path.join(OUT, "T_CkLabels.png"), optimize=True)
    json.dump(dict(size=[W, H], rects=rects), open(os.path.join(OUT, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("labels atlas", W, H, len(rects))


def callouts():
    for k, (t, wcm, hcm) in CALLOUTS.items():
        w, h = int(wcm * PX), int(hcm * PX)
        im = Image.new("RGB", (w, h), (0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([1, 1, w - 2, h - 2], radius=10, outline=(70, 170, 110), width=3)
        size = int(h * 0.55)
        f = ImageFont.truetype(FB, size)
        while d.textlength(t, font=f) > w - 24 and size > 12:
            size -= 2
            f = ImageFont.truetype(FB, size)
        d.text((w / 2, h / 2), t, font=f, fill=(150, 255, 180), anchor="mm")
        im.save(os.path.join(OUT, "lbl_%s.png" % k), optimize=True)
    json.dump({k: dict(text=t, w=w, h=h) for k, (t, w, h) in CALLOUTS.items()}, open(os.path.join(OUT, "callouts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    atlas()
    callouts()
