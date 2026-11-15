"""Place-name label atlas for the right MFD moving map (Content/Python/mfd_map.py; the canvas font has no Hangul):
  Art/Cockpit/tex/T_MapNames.png + mapnames.json   white glyphs (alpha = coverage), one height for every name, + the
                                                  V-World credit line. Names / positions = sim/minimap_build.PLACES.
Run (CPython + Pillow):  python make_map_labels.py      (Malgun Gothic bold; only rendered glyphs, no map imagery)
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "Art", "Cockpit", "tex"))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "sim")))
from minimap_build import PLACES      # noqa: E402  (name, lat, lon[, side])
FB = r"C:\Windows\Fonts\malgunbd.ttf"
CREDIT = "지도: 브이월드(V-World), 국토교통부"


def main():
    W, H0 = 1024, 60
    f = ImageFont.truetype(FB, 44)
    tmp = ImageDraw.Draw(Image.new("L", (8, 8)))
    texts = [p[0] for p in PLACES] + [CREDIT]
    rects, x, y, items = {}, 4, 4, []
    for t in texts:
        bb = tmp.textbbox((0, 0), t, font=f)
        w = bb[2] - bb[0] + 12
        if x + w > W - 4:
            x, y = 4, y + H0 + 6
        rects[t] = [x, y, w, H0]
        items.append((t, x, y, bb))
        x += w + 6
    H = 1
    while H < y + H0 + 8:
        H *= 2
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for t, x0, y0, bb in items:
        d.text((x0 + 6 - bb[0], y0 + 30), t, font=f, fill=255, anchor="lm")
    im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    im.putalpha(m)
    im.save(os.path.join(OUT, "T_MapNames.png"), optimize=True)
    json.dump(dict(size=[W, H], rects=rects, places=[[p[0], p[1], p[2]] for p in PLACES], credit=CREDIT),
              open(os.path.join(OUT, "mapnames.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("map names atlas", W, H, len(rects))


if __name__ == "__main__":
    main()
