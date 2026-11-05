"""Key guide panel for the Unreal client: renders sim/key_panel.png (Korean, Malgun Gothic) once.

    python sim/key_panel.py

The PNG is committed; run this again only after changing ROWS. sim_client.py loads it with
RenderingLibrary.import_file_as_texture2d onto the KeyPanel plane (right of the forward view, K toggles).
Keys must match sim_client._keyboard (F11 / Esc are the editor's own Play keys).
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "key_panel.png")
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"

# (group, [(keys, action), ...])
ROWS = [
    ("비행", [("← →", "롤"), ("↑ ↓", "피치 (↓ = 당기기)"), ("A D", "러더"), ("W S", "스로틀"), ("B", "브레이크"), ("G", "바퀴")]),
    ("교관", [("F1", "메뉴 (↑↓ Enter)"), ("F2", "강의 끝"), ("N", "다음"), ("M", "다시"), ("Z", "다시 듣기"), ("Y", "음성"), ("L", "초보 설명"), ("I", "안내 방식")]),
    ("시작", [("0~9", "강의"), ("R", "공중 (강의 중엔 두 번)"), ("T", "활주로"), ("P", "멈춤")]),
    ("시점", [("V", "시점 (Shift = 뒤로)"), ("C", "아래"), ("Q E", "좌우·돌기"), ("PgUp Dn", "위아래"), ("+ - 휠", "거리"),
             ("마우스 끌기", "돌기"), ("Home", "처음"), ("F11", "전체")]),
    ("표시", [("U", "HUD"), ("H", "강의판"), ("K", "이 안내판")]),
    ("VR", [("F3", "정면 맞추기"), ("F9", "VR 켜기/끄기"), ("Esc", "끝내기")]),
]

W, H = 1024, 592                 # sim_client sizes the KeyPanel plane to this aspect (was 1024 x 512 = the plane 26 x 13 cm)
# V cycles: 조종석 -> 뒤 (추적) -> 옆 (주위 돌기) -> 지나가기 (앞에 고정점) -> 관제탑 (활주로 옆 고정점) -> 조종석
BG, EDGE, HEAD, GROUP, KEY, TEXT, DOT = (8, 14, 22), (60, 200, 110), (120, 255, 160), (120, 255, 160), (255, 220, 120), (235, 240, 245), (90, 110, 130)


def render(path=OUT):
    im = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(im)
    fh, fg, fk, ft = (ImageFont.truetype(FONT_B, 40), ImageFont.truetype(FONT_B, 31), ImageFont.truetype(FONT_B, 31),
                      ImageFont.truetype(FONT, 31))
    g.rectangle([0, 0, W - 1, H - 1], outline=EDGE, width=4)
    g.text((26, 12), "키 안내", font=fh, fill=HEAD)
    g.text((W - 26, 22), "K = 끄기/켜기", font=ft, fill=DOT, anchor="ra")
    x0, x1, lh = 112, W - 22, 44
    y = 72
    for grp, items in ROWS:
        g.text((26, y), grp, font=fg, fill=GROUP)
        x = x0
        for i, (k, a) in enumerate(items):
            wk, wa = g.textlength(k, font=fk), g.textlength(a, font=ft)
            sep = g.textlength("  ·  ", font=ft) if i else 0
            if x + sep + wk + 8 + wa > x1:          # wrap onto the next line
                y += lh
                x, sep = x0, 0
            if sep:
                g.text((x, y), "  ·  ", font=ft, fill=DOT)
                x += sep
            g.text((x, y), k, font=fk, fill=KEY)
            x += wk + 8
            g.text((x, y), a, font=ft, fill=TEXT)
            x += wa
        y += lh + 10
    if y > H - 6:
        raise SystemExit("key panel text overflows: y=%d > %d" % (y, H))
    tmp = path + ".tmp.png"
    im.save(tmp)
    os.replace(tmp, path)
    return path, y


if __name__ == "__main__":
    print(*render())
