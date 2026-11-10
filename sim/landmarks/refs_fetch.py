r"""Reference photos for the Busan landmarks from Wikimedia Commons (search API, no account). Photos are third-party
works under their own licences: they are kept LOCAL ONLY in C:\GyroSimTiles\landmarks\refs\<key>\ (never in git);
refs/<key>/sources.json records file page URL, author, licence for each.
    python -I sim/landmarks/refs_fetch.py <key> "<search words>" [n]
"""
import json, os, sys, time, urllib.parse, urllib.request
OUT = r"C:\GyroSimTiles\landmarks\refs"
UA = "GyroSimLandmarks/0.1 (personal flight-sim research; contact: local user)"
API = "https://commons.wikimedia.org/w/api.php"


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(15 * (i + 1))


def search(q, n):
    p = dict(action="query", format="json", generator="search", gsrsearch="filetype:bitmap " + q, gsrnamespace="6",
             gsrlimit=str(n), prop="imageinfo", iiprop="url|extmetadata|size", iiurlwidth="1280")
    d = json.loads(get(API + "?" + urllib.parse.urlencode(p)))
    pages = sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    return pages


def main(key, q, n=8):
    d = os.path.join(OUT, key)
    os.makedirs(d, exist_ok=True)
    meta_p = os.path.join(d, "sources.json")
    meta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
    for p in search(q, n):
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url:
            continue
        name = p["title"].split(":", 1)[1]
        fn = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:120]
        if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
            fn += ".jpg"
        path = os.path.join(d, fn)
        if not os.path.exists(path):
            try:
                data = get(url)
            except Exception as e:
                print("skip", fn, e)
                time.sleep(10)
                continue
            open(path, "wb").write(data)
            time.sleep(3.0)
        em = ii.get("extmetadata", {})
        meta[fn] = dict(page=ii.get("descriptionurl"), author=(em.get("Artist", {}).get("value", "") or "")[:200],
                        licence=em.get("LicenseShortName", {}).get("value"), date=em.get("DateTimeOriginal", {}).get("value"),
                        query=q, fetched=time.strftime("%Y-%m-%d %H:%M"))
        print(fn, meta[fn]["licence"])
    json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8)
