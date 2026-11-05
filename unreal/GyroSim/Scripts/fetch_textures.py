"""Download the CC0 photo textures used by build_level.py from Poly Haven (no login) into ThirdParty/polyhaven/.

  python fetch_textures.py            (2k JPG: colour, DirectX normal, roughness)

Poly Haven assets are CC0 (https://polyhaven.com/license). Source + authors per texture go to
ThirdParty/polyhaven/<asset>/info.json (and unreal/GyroSim/ATTRIBUTION.md).
"""
import json, os, sys, time, urllib.request

ASSETS = {                      # role -> Poly Haven asset id
    "runway": "concrete_pavement",      # RKTU runways are concrete
    "taxiway": "asphalt_02",
    "grass": "leafy_grass",
    "seat_fleece": "curly_teddy_natural",    # cockpit seat cushions (sheepskin-like pad, photo c06) - normal map only, tinted black
    "grip_leather": "fabric_leather_02",     # stick / throttle grips - normal map only
}
MAPS = {"Diffuse": "diff", "nor_dx": "nor", "Rough": "rough"}
RES = "2k"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "ThirdParty", "polyhaven")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GyroSim-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main():
    for role, aid in ASSETS.items():
        d = os.path.join(OUT, aid)
        os.makedirs(d, exist_ok=True)
        files = json.loads(get("https://api.polyhaven.com/files/" + aid))
        info = json.loads(get("https://api.polyhaven.com/info/" + aid))
        out = dict(asset=aid, role=role, page="https://polyhaven.com/a/" + aid, license="CC0 1.0", authors=info.get("authors"),
                   dimensions_mm=info.get("dimensions"), files={}, fetched=time.strftime("%Y-%m-%d %H:%M:%S"))
        for key, short in MAPS.items():
            url = files[key][RES]["jpg"]["url"]
            fn = os.path.join(d, "%s_%s.jpg" % (aid, short))
            if not os.path.exists(fn):
                print("download", url, flush=True)
                with open(fn, "wb") as f:
                    f.write(get(url))
            out["files"][short] = dict(file=os.path.basename(fn), url=url)
        with open(os.path.join(d, "info.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(role, aid, "ok", flush=True)


if __name__ == "__main__":
    sys.exit(main())
