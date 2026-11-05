"""Training panel images (Korean, Malgun Gothic): the training display / tutorial panel picture (1024 x 640) per phase,
and one HUD line (1024 x 72, green on black = transparent on the HUD). Written to sim/out/ (rotating names), read by
Unreal (import_file_as_texture2d) and served to the browser.
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
os.makedirs(OUT, exist_ok=True)
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"
W, H = 1024, 640
BG, EDGE = (6, 12, 18), (60, 200, 110)
GREEN, WHITE, GREY, YELLOW, ORANGE, RED, BLUE = (120, 255, 160), (235, 240, 245), (170, 185, 200), (255, 225, 120), (255, 150, 80), (255, 90, 80), (165, 200, 240)
# type scale (readability pass 11-05: the cockpit display is ~18 deg wide in the headset, so nothing below 26 px)
XL, LG, MD, SM = 42, 34, 30, 26
CRASH_BG = (150, 16, 16)
CRASH_BTN = dict(retry=(60 / 1024, 430 / 640, 492 / 1024, 590 / 640), menu=(532 / 1024, 430 / 640, 964 / 1024, 590 / 640))   # (u0, v0, u1, v1) for clicks      # instruction / title + coach / menu + hint / key line
_F = {}


def F(sz, bold=False):
    k = (sz, bold)
    if k not in _F:
        _F[k] = ImageFont.truetype(FONT_B if bold else FONT, sz)
    return _F[k]


def wrap(g, text, font, width):
    out = []
    for para in str(text).split("\n"):
        cur = ""
        for ch in para:
            if g.textlength(cur + ch, font=font) > width:
                cut = cur.rfind(" ")
                if cut > len(cur) // 2:
                    out.append(cur[:cut]); cur = cur[cut + 1:] + ch
                else:
                    out.append(cur); cur = ch
            else:
                cur += ch
        out.append(cur)
    return out or [""]


def para(g, x, y, text, font, col, width, lh, maxl=99):
    for line in wrap(g, text, font, width)[:maxl]:
        g.text((x, y), line, font=font, fill=col)
        y += lh
    return y


def render_panel(d, ver):
    im = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(im)
    g.rectangle([0, 0, W - 1, H - 1], outline=EDGE, width=4)
    ph = d.get("phase")
    # header: phase badge, title, step, trainee / mode
    badge = d.get("phase_ko") or ""
    bcol = {"solo": (255, 200, 90), "demo": (120, 190, 255), "crash": ORANGE, "debrief": GREEN}.get(ph, (90, 210, 140))
    x = 22
    if badge:
        bw = g.textlength(badge, font=F(30, True)) + 24
        g.rounded_rectangle([x, 16, x + bw, 58], radius=10, fill=bcol)
        g.text((x + 12, 19), badge, font=F(30, True), fill=(10, 14, 18))
        x += bw + 16
    title = d.get("title") or ""
    if d.get("n") and ph not in ("menu", "debrief", "crash"):
        title += "   %d / %d" % (d.get("step", 0), d["n"])
    g.text((x, 16), title, font=F(LG, True), fill=GREEN)
    if ph == "menu":                     # trainee / control mode: only in the menu (rarely needed in flight)
        right = "%s · %s%s" % (d.get("trainee", ""), "조종 장치" if d.get("mode") == "rig" else "키보드", "" if d.get("voice") else " · 음성 꺼짐")
        g.text((W - 22, 26), right, font=F(SM), fill=GREY, anchor="ra")
    y = 76
    rig = d.get("mode") == "rig"
    NK = "트리거" if rig else "N"
    if ph == "menu":
        y = 84
        items = d.get("items") or []
        sel_i = d.get("sel", 0) or 0
        first = max(0, min(sel_i - 3, len(items) - 8))
        if first > 0:
            g.text((W - 30, 80), "▲", font=F(MD), fill=GREY, anchor="ra")
        if first + 8 < len(items):
            g.text((W - 30, H - 96), "▼", font=F(MD), fill=GREY, anchor="ra")
        for i, t in list(enumerate(items))[first:first + 8]:
            sel = i == sel_i
            if sel:
                g.rounded_rectangle([22, y - 4, W - 22, y + 52], radius=8, fill=(30, 70, 50), outline=GREEN, width=2)
            g.text((40, y), ("▶ " if sel else "   ") + t, font=F(LG, sel), fill=WHITE if sel else (210, 220, 230))
            y += 60
        g.text((22, H - 46), ("스틱 앞뒤 = 고르기 · 트리거 = 선택 · 뒤로 버튼 = 뒤로" if rig else "↑↓ = 고르기 · Enter = 선택 · Backspace = 뒤로"), font=F(SM), fill=BLUE)
    elif ph == "brief":
        y = para(g, 30, y + 16, d.get("text", ""), F(XL, True), YELLOW, W - 60, 56, 8)
        if d.get("msg"):
            g.text((22, H - 88), d["msg"], font=F(SM, True), fill=ORANGE)
        g.text((22, H - 46), "%s = 다음 · Z = 다시 듣기 · F1 = 메뉴" % NK, font=F(SM), fill=BLUE)
    elif ph == "demo":
        g.text((30, y + 6), "자동 조종 시범 — 스틱과 스로틀을 보세요", font=F(MD), fill=GREY)
        para(g, 30, y + 56, d.get("text", ""), F(XL, True), (170, 210, 255), W - 60, 56, 7)
        _bar(g, d.get("prog", 0), (120, 190, 255))
        g.text((22, H - 84), d.get("msg") or ("%s = 시범 건너뛰기" % NK), font=F(SM), fill=ORANGE if d.get("msg") else BLUE)
    elif ph in ("practice", "solo", "free"):
        if ph == "free":
            para(g, 30, y + 20, "자유 비행 — 교관 없음. F1 = 메뉴", F(XL, True), WHITE, W - 60, 56)
        else:
            # layout: instruction (<= 3 lines) + coach (<= 2 lines) above y 340; y 344..552 is left free for the live
            # target rows drawn by the cockpit display (hud.py); one bottom row (notice / hint / keys) + progress bar.
            # The grey context line is shown only without an instruction (it repeated the target rows).
            tg = bool(d.get("targets"))
            if d.get("instr"):
                g.rectangle([18, y + 6, 25, y + 50], fill=YELLOW)
                y = para(g, 38, y, d["instr"], F(XL, True), YELLOW, W - 70, 52, 3) + 4
            elif d.get("text"):
                y = para(g, 30, y, d["text"], F(LG), GREY, W - 60, 44, 3) + 4
            if d.get("coach"):
                col = GREEN if d.get("coach_kind") == "good" else ORANGE
                para(g, 30, max(y, 248), "교관: " + d["coach"], F(LG, True), col, W - 60, 44, 2)
            y_bot = H - 82
            if d.get("msg"):                    # a short notice takes the hint row for 3 s (never both: they overlapped)
                _fit(g, 22, y_bot, d["msg"], MD, True, ORANGE)
            elif d.get("hint") and ph == "practice":
                hl = wrap(g, "힌트: " + d["hint"], F(MD), W - 44)
                if len(hl) > 1 and not tg:      # room for two lines when there are no target rows
                    g.text((22, y_bot - 40), hl[0], font=F(MD), fill=BLUE)
                    g.text((22, y_bot), hl[1] + ("…" if len(hl) > 2 else ""), font=F(MD), fill=BLUE)
                else:
                    _fit(g, 22, y_bot, "힌트: " + d["hint"], MD, False, BLUE)
            elif ph == "solo":
                _fit(g, 22, y_bot, "단독 점검 — 교관은 조용히 봐요 · 점수 %s" % (d.get("live_score") if d.get("live_score") is not None else "-"),
                     MD, False, (255, 200, 90))
            else:
                g.text((22, y_bot), "%s = 건너뛰기 · Z = 다시 듣기 · F1 = 메뉴" % NK, font=F(SM), fill=BLUE)
            _bar(g, d.get("prog", 0), (60, 200, 110))
    elif ph == "debrief":
        db = d.get("debrief") or {}
        ok = db.get("passed")
        g.text((30, 80), ("통과!" if ok else "아직이에요"), font=F(54, True), fill=GREEN if ok else ORANGE)
        if db.get("pass_score"):
            g.text((W - 30, 80), "%d 점  %s" % (db.get("score", 0), db.get("grade") or ""), font=F(54, True), fill=WHITE, anchor="ra")
            g.text((W - 30, 146), "통과 기준 %d 점%s" % (db["pass_score"], " · 쉬운 모드" if db.get("assist") else ""), font=F(SM), fill=GREY, anchor="ra")
        y = 172
        gw = W - 60 if not db.get("graph") else 560
        for t in db.get("good", [])[:2]:
            y = para(g, 30, y, "＋ " + t, F(MD), GREEN, gw, 40, 2) + 4
        for t in db.get("fix", [])[:3]:
            if y > H - 130:
                break
            y = para(g, 30, y, "－ " + t, F(MD), ORANGE, gw, 40, 2) + 4
        if db.get("graph"):
            _graph(g, 610, 222, 390, 270, db)
        if not db.get("pass_score"):            # lesson without a solo check (0. orientation)
            nxt = "%s = 다음 강의 · M = 이 강의 다시 · F1 = 메뉴" % NK
        else:
            nxt = ("%s = 다음 강의 · M = 단독 점검 다시 · F1 = 메뉴" % NK) if ok else ("%s / M = 단독 점검 다시 · F1 = 메뉴 · Z = 다시 듣기" % NK)
        g.text((22, H - 46), nxt, font=F(SM), fill=BLUE)
    elif ph == "crash":
        # red crash screen (11-05): Unreal shows this picture full screen (monitor + VR), the browser its own overlay
        c = d.get("crash") or {}
        g.rectangle([0, 0, W - 1, H - 1], fill=CRASH_BG)
        g.text((W / 2, 112), "추락", font=F(120, True), fill=WHITE, anchor="mm")
        _fit_c(g, W / 2, 228, c.get("short") or c.get("why", ""), 48, True, (255, 236, 160))
        ly = 286
        for t in wrap(g, c.get("say", ""), F(SM), W - 120)[:2]:
            g.text((W / 2, ly), t, font=F(SM), fill=(255, 215, 215), anchor="mt")
            ly += 36
        for x0, x1, big, small, filled in ((60, 492, "다시하기", "트리거" if rig else "Enter · R · 클릭", True),
                                           (532, 964, "메뉴", "두 번째 버튼" if rig else "F1", False)):
            if filled:
                g.rounded_rectangle([x0, 430, x1, 590], radius=18, fill=WHITE)
            else:
                g.rounded_rectangle([x0, 430, x1, 590], radius=18, outline=WHITE, width=5)
            col = CRASH_BG if filled else WHITE
            g.text(((x0 + x1) / 2, 492), big, font=F(56, True), fill=col, anchor="mm")
            g.text(((x0 + x1) / 2, 556), small, font=F(SM, True), fill=col, anchor="mm")
    path = os.path.join(OUT, "tut_panel_%d.png" % (ver % 4))
    im.save(path + ".tmp.png")
    os.replace(path + ".tmp.png", path)
    # HUD line: coaching if recent, else the instruction. Bold 44 px, up to 2 lines (shrinks to 36 before cutting),
    # cropped to the text: the HUD draws it 1:1 (~1 deg letters) on a dark plate of the same size.
    line = d.get("coach") or d.get("instr") or (d.get("text") if ph in ("brief", "demo", "crash") else "") or ""
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    sz = 44
    lines = wrap(tmp, line, F(sz, True), 960) if line else []
    while len(lines) > 2 and sz > 36:
        sz -= 4
        lines = wrap(tmp, line, F(sz, True), 960)
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1][:-1] + "…"
    lh = sz + 14
    lw = int(max([tmp.textlength(t, font=F(sz, True)) for t in lines] or [0])) + 36
    li = Image.new("RGB", (max(16, lw), lh * max(1, len(lines)) + 12), (0, 0, 0))
    gl = ImageDraw.Draw(li)
    for i, t in enumerate(lines):
        gl.text((li.width / 2, 6 + lh * i + lh / 2), t, font=F(sz, True), fill=(110, 255, 140), anchor="mm")
    lpath = os.path.join(OUT, "tut_line_%d.png" % (ver % 4))
    li.save(lpath + ".tmp.png")
    os.replace(lpath + ".tmp.png", lpath)
    return path.replace("\\", "/"), lpath.replace("\\", "/")


def _fit(g, x, y, text, sz, bold, col, width=W - 44, smin=24):
    """one line: shrink to fit (down to smin), then cut with an ellipsis."""
    while sz > smin and g.textlength(text, font=F(sz, bold)) > width:
        sz -= 2
    if g.textlength(text, font=F(sz, bold)) > width:
        while text and g.textlength(text + "…", font=F(sz, bold)) > width:
            text = text[:-1]
        text += "…"
    g.text((x, y), text, font=F(sz, bold), fill=col)


def _fit_c(g, x, y, text, sz, bold, col, width=W - 80, smin=28):
    while sz > smin and g.textlength(text, font=F(sz, bold)) > width:
        sz -= 2
    g.text((x, y), text, font=F(sz, bold), fill=col, anchor="mm")


def _bar(g, p, col):
    g.rectangle([22, H - 36, W - 22, H - 16], outline=(90, 110, 130), width=2)
    g.rectangle([24, H - 34, 24 + int((W - 48) * max(0.0, min(1.0, p or 0))), H - 18], fill=col)


def _graph(g, x0, y0, w, h, db):
    """key metric deviation over the solo check with the tolerance band."""
    pts, tol = db["graph"], db.get("tol") or 1.0
    g.rectangle([x0, y0, x0 + w, y0 + h], outline=(70, 90, 110), width=2)
    g.text((x0, y0 - 36), "%s 차이 (단독 점검)" % db.get("key_ko", ""), font=F(SM, True), fill=WHITE)
    if not pts:
        return
    t1 = max(p[0] for p in pts) or 1.0
    m = max(tol * 3, max(abs(p[1]) for p in pts))
    Y = lambda v: y0 + h / 2 - (v / m) * (h / 2 - 6)
    X = lambda t: x0 + 4 + (t / t1) * (w - 8)
    g.rectangle([x0 + 2, Y(tol), x0 + w - 2, Y(-tol)], fill=(20, 60, 36))
    g.line([(x0, Y(0)), (x0 + w, Y(0))], fill=(70, 110, 90), width=1)
    xy = [(X(t), Y(max(-m, min(m, v)))) for t, v in pts]
    if len(xy) > 1:
        g.line(xy, fill=YELLOW, width=3)
    g.text((x0 + w - 6, Y(tol) - 2), "+%g" % tol, font=F(22), fill=GREEN, anchor="rb")
    g.text((x0 + 6, y0 + h + 6), "초록 = 허용 범위", font=F(22), fill=GREY)
