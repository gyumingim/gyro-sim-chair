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
GREEN, WHITE, GREY, YELLOW, ORANGE, RED, BLUE = (120, 255, 160), (235, 240, 245), (150, 165, 180), (255, 225, 120), (255, 150, 80), (255, 90, 80), (150, 190, 230)
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
    g.text((x, 16), title, font=F(34, True), fill=GREEN)
    right = "%s · %s%s" % (d.get("trainee", ""), "조종 장치" if d.get("mode") == "rig" else "키보드", "" if d.get("voice") else " · 음성 꺼짐")
    g.text((W - 22, 30), right, font=F(20), fill=GREY, anchor="ra")
    y = 76
    rig = d.get("mode") == "rig"
    NK = "트리거" if rig else "N"
    if ph == "menu":
        y = 84
        items = d.get("items") or []
        sel_i = d.get("sel", 0) or 0
        first = max(0, min(sel_i - 4, len(items) - 9))
        if first > 0:
            g.text((W - 30, 80), "▲", font=F(24), fill=GREY, anchor="ra")
        if first + 9 < len(items):
            g.text((W - 30, H - 84), "▼", font=F(24), fill=GREY, anchor="ra")
        for i, t in list(enumerate(items))[first:first + 9]:
            sel = i == sel_i
            if sel:
                g.rounded_rectangle([22, y - 4, W - 22, y + 46], radius=8, fill=(30, 70, 50), outline=GREEN, width=2)
            g.text((40, y), ("▶ " if sel else "   ") + t, font=F(30, sel), fill=WHITE if sel else (200, 210, 220))
            y += 54
        g.text((22, H - 44), ("스틱 앞뒤 = 고르기 · 트리거 = 선택 · 뒤로 버튼 = 뒤로" if rig else "↑↓ = 고르기 · Enter = 선택 · Backspace = 뒤로"), font=F(24), fill=BLUE)
    elif ph == "brief":
        y = para(g, 30, y + 20, d.get("text", ""), F(38, True), YELLOW, W - 60, 54)
        if d.get("msg"):
            g.text((22, H - 84), d["msg"], font=F(24, True), fill=ORANGE)
        g.text((22, H - 44), "%s = 다음 · Z = 다시 듣기 · F1 = 메뉴" % NK, font=F(26), fill=BLUE)
    elif ph == "demo":
        g.text((30, y + 10), "자동 조종이 보여 줘요 — 스틱과 스로틀을 보세요", font=F(26), fill=GREY)
        para(g, 30, y + 56, d.get("text", ""), F(38, True), (170, 210, 255), W - 60, 54)
        _bar(g, d.get("prog", 0), (120, 190, 255))
        g.text((22, H - 80), d.get("msg") or ("%s = 시범 건너뛰기" % NK), font=F(24), fill=ORANGE if d.get("msg") else BLUE)
    elif ph in ("practice", "solo", "free"):
        if ph == "free":
            para(g, 30, y + 20, "자유 비행 — 교관 없음. F1 = 메뉴", F(34, True), WHITE, W - 60, 50)
        else:
            # layout: context (2 lines) + instruction (3 lines) + coach (2 lines) above y 376; y 380..540 is left free for
            # the live target bars drawn by the cockpit display (hud.py); hint / keys / progress below
            y = para(g, 30, y, d.get("text", ""), F(24), GREY, W - 60, 31, 2) + 4
            if d.get("instr"):
                g.rectangle([18, y + 2, 25, y + 44], fill=YELLOW)
                y = para(g, 38, y, d["instr"], F(36, True), YELLOW, W - 70, 46, 3) + 2
            if d.get("coach"):
                col = GREEN if d.get("coach_kind") == "good" else ORANGE
                para(g, 30, max(y, 296), "교관: " + d["coach"], F(29, True), col, W - 60, 38, 2)
            if d.get("targets"):
                g.text((W - 26, 392), "목표와 차이 ↓", font=F(20), fill=GREY, anchor="ra")
            if d.get("msg"):                    # a short notice takes the hint row for 3 s (never both: they overlapped)
                g.text((22, H - 100), d["msg"], font=F(23, True), fill=ORANGE)
            elif d.get("hint") and ph == "practice":
                g.text((22, H - 100), "힌트: " + wrap(g, d["hint"], F(23), W - 60)[0], font=F(23), fill=BLUE)
            if ph == "solo":
                g.text((22, H - 70), "단독 점검 — 교관은 조용히 봐요 · 점수 %s" % (d.get("live_score") if d.get("live_score") is not None else "-"),
                       font=F(23), fill=(255, 200, 90))
            else:
                g.text((22, H - 70), "%s = 건너뛰기 · Z = 다시 듣기 · P = 멈춤 · F1 = 메뉴" % NK, font=F(23), fill=BLUE)
            _bar(g, d.get("prog", 0), (60, 200, 110))
    elif ph == "debrief":
        db = d.get("debrief") or {}
        ok = db.get("passed")
        g.text((30, 86), ("통과!" if ok else "아직이에요"), font=F(54, True), fill=GREEN if ok else ORANGE)
        if db.get("pass_score"):
            g.text((W - 30, 86), "%d 점  %s" % (db.get("score", 0), db.get("grade") or ""), font=F(54, True), fill=WHITE, anchor="ra")
            g.text((W - 30, 152), "통과 기준 %d 점%s" % (db["pass_score"], " · 쉬운 모드" if db.get("assist") else ""), font=F(22), fill=GREY, anchor="ra")
        y = 168
        for t in db.get("good", [])[:3]:
            y = para(g, 30, y, "＋ " + t, F(25), GREEN, W - 60 if not db.get("graph") else 560, 33, 2)
        for t in db.get("fix", [])[:3]:
            y = para(g, 30, y, "－ " + t, F(25), ORANGE, W - 60 if not db.get("graph") else 560, 33, 2)
        if db.get("graph"):
            _graph(g, 610, 190, 390, 300, db)
        if not db.get("pass_score"):            # lesson without a solo check (0. orientation)
            nxt = "%s = 다음 강의 · M = 이 강의 다시 · F1 = 메뉴" % NK
        else:
            nxt = ("%s = 다음 강의 · M = 단독 점검 다시 · F1 = 메뉴" % NK) if ok else ("%s / M = 단독 점검 다시 · F1 = 메뉴 · Z = 다시 듣기" % NK)
        g.text((22, H - 44), nxt, font=F(26), fill=BLUE)
    elif ph == "crash":
        c = d.get("crash") or {}
        g.text((30, 100), c.get("why", ""), font=F(46, True), fill=ORANGE)
        para(g, 30, 180, c.get("say", ""), F(34), WHITE, W - 60, 48)
        if d.get("msg"):
            g.text((22, H - 84), d["msg"], font=F(24, True), fill=ORANGE)
        g.text((22, H - 44), "M 또는 %s = 이 단계 다시 · F1 = 메뉴 · Z = 다시 듣기" % NK, font=F(26), fill=BLUE)
    path = os.path.join(OUT, "tut_panel_%d.png" % (ver % 4))
    im.save(path + ".tmp.png")
    os.replace(path + ".tmp.png", path)
    # HUD line: coaching if recent, else the instruction
    line = d.get("coach") or d.get("instr") or (d.get("text") if ph in ("brief", "demo", "crash") else "") or ""
    li = Image.new("RGB", (1024, 72), (0, 0, 0))
    gl = ImageDraw.Draw(li)
    sz = 34
    while line and sz > 20 and gl.textlength(line, font=F(sz, True)) > 1000:     # shrink to fit one line
        sz -= 2
    t = wrap(gl, line, F(sz, True), 1000)[0] if line else ""
    gl.text((512, 36), t, font=F(sz, True), fill=(110, 255, 140), anchor="mm")
    lpath = os.path.join(OUT, "tut_line_%d.png" % (ver % 4))
    li.save(lpath + ".tmp.png")
    os.replace(lpath + ".tmp.png", lpath)
    return path.replace("\\", "/"), lpath.replace("\\", "/")


def _bar(g, p, col):
    g.rectangle([22, H - 36, W - 22, H - 16], outline=(90, 110, 130), width=2)
    g.rectangle([24, H - 34, 24 + int((W - 48) * max(0.0, min(1.0, p or 0))), H - 18], fill=col)


def _graph(g, x0, y0, w, h, db):
    """key metric deviation over the solo check with the tolerance band."""
    pts, tol = db["graph"], db.get("tol") or 1.0
    g.rectangle([x0, y0, x0 + w, y0 + h], outline=(70, 90, 110), width=2)
    g.text((x0, y0 - 34), "%s 차이 (단독 점검)" % db.get("key_ko", ""), font=F(24, True), fill=WHITE)
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
    g.text((x0 + w - 6, Y(tol) - 2), "+%g" % tol, font=F(18), fill=GREEN, anchor="rb")
    g.text((x0 + 6, y0 + h + 6), "초록 = 허용 범위", font=F(18), fill=GREY)
