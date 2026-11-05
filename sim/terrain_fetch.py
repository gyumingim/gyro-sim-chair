"""Download the Copernicus DEM GLO-30 tiles that cover South Korea (대한민국) + the EGM2008 geoid window.

    python sim/terrain_fetch.py            download what is missing (resumes), write the manifest
    python sim/terrain_fetch.py --list     print the tile list only (no download)

Source: public AWS bucket (no account) https://copernicus-dem-30m.s3.amazonaws.com/ (Registry of Open Data,
https://registry.opendata.aws/copernicus-dem/). 1 x 1 degree Cloud-Optimized GeoTIFFs, float32 metres,
heights = orthometric (EGM2008 geoid, "MSL"), horizontal WGS84, 1 arc-second grid (3600 x 3600 below 50 deg latitude).
Geoid: EGM2008 2.5' grid from the PROJ data CDN (https://cdn.proj.org/us_nga_egm08_25.tif), only a window around Korea
is read (HTTP range requests through GDAL /vsicurl/) and stored as a small .npy.

Files go to C:\\GyroSimTiles\\terrain\\raw (never into git; set GYROSIM_TERRAIN to move it). Manifest with date, URLs,
sizes and sha256: raw/manifest.json.

Tile list = 1-degree cells (named by their south-west corner) that contain South Korean land: mainland, Jeju, the
western / southern islands, Ulleungdo, Dokdo. Cells that are only North Korea, China, Japan (Tsushima = N34 E129) or
open sea are not downloaded. Border cells (N37 E124-126, N38 E127-128) are kept whole (they include some North Korean
land north of the 1953 line - kept, so the relief does not end in a cliff at the DMZ).

Copernicus licence / attribution (required): "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018
provided under COPERNICUS by the European Union and ESA; all rights reserved" (see unreal/GyroSim/ATTRIBUTION.md).
"""
import hashlib, json, os, sys, time, urllib.request

ROOT = os.environ.get("GYROSIM_TERRAIN", r"C:\GyroSimTiles\terrain")
RAW = os.path.join(ROOT, "raw")
BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
GEOID_URL = "https://cdn.proj.org/us_nga_egm08_25.tif"
GEOID_BOX = (120.0, 29.0, 136.0, 43.0)        # west, south, east, north (deg): Korea + 2-4 deg of sea around it

# (lat, lon) of the south-west corner, with what South Korean land is inside
TILES = [
    (33, 126, "Jeju, Marado, Chujado"),
    (34, 125, "Heuksando, Gageodo, Hongdo"),
    (34, 126, "SW coast: Mokpo, Jindo, Wando"),
    (34, 127, "S coast: Goheung, Yeosu, Geomundo"),
    (34, 128, "S coast: Tongyeong, Geoje, Namhae"),
    (35, 126, "Jeolla west: Gwangju, Gunsan"),
    (35, 127, "Jeonju, Jirisan"),
    (35, 128, "Daegu, Changwon, Gimhae"),
    (35, 129, "Busan, Ulsan, Gyeongju, Pohang"),
    (36, 125, "Eocheongdo, Gyeokryeolbiyeoldo (islets)"),
    (36, 126, "Taean, Boryeong, Seosan"),
    (36, 127, "Cheongju (RKTU), Daejeon, Sokrisan"),
    (36, 128, "Andong, Gumi, Sobaeksan"),
    (36, 129, "E coast: Uljin, Yeongdeok"),
    (37, 124, "Baengnyeongdo, Daecheongdo (border cell)"),
    (37, 125, "Yeonpyeongdo, Ganghwa west (border cell)"),
    (37, 126, "Seoul, Incheon, Gyeonggi (border cell)"),
    (37, 127, "Gyeonggi east, Chuncheon, Wonju"),
    (37, 128, "Gangwon: Seoraksan (S part), Odaesan, Taebaek"),
    (37, 129, "E coast: Gangneung, Donghae, Samcheok"),
    (37, 130, "Ulleungdo"),
    (37, 131, "Dokdo"),
    (38, 127, "Cheorwon, Hwacheon (border cell)"),
    (38, 128, "Seoraksan, Sokcho, Goseong (border cell)"),
]


def tile_name(lat, lon):
    return "Copernicus_DSM_COG_10_%s%02d_00_%s%03d_00_DEM" % ("N" if lat >= 0 else "S", abs(lat), "E" if lon >= 0 else "W", abs(lon))


def tile_url(lat, lon):
    n = tile_name(lat, lon)
    return "%s/%s/%s.tif" % (BUCKET, n, n)


def tile_path(lat, lon):
    return os.path.join(RAW, tile_name(lat, lon) + ".tif")


GEOID_NPY = os.path.join(RAW, "egm2008_25_korea.npy")      # float32 [rows north->south, cols west->east], 2.5' cells
GEOID_META = os.path.join(RAW, "egm2008_25_korea.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(url, path, tries=4):
    tmp = path + ".part"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gyro-sim-chair terrain_fetch"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                n = int(r.headers.get("Content-Length") or 0)
                got = 0
                for b in iter(lambda: r.read(1 << 20), b""):
                    f.write(b)
                    got += len(b)
            if n and got != n:
                raise IOError("short read %d / %d" % (got, n))
            os.replace(tmp, path)
            return got
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):            # tile does not exist in the bucket (ocean)
                return None
            err = e
        except Exception as e:
            err = e
        print("  retry %d: %r" % (i + 1, err), flush=True)
        time.sleep(2 * (i + 1))
    raise RuntimeError("download failed: %s (%r)" % (url, err))


def fetch_geoid():
    """EGM2008 2.5' window around Korea -> .npy (GDAL range reads, a few hundred kB)."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    w, s, e, n = GEOID_BOX
    with rasterio.open("/vsicurl/" + GEOID_URL) as ds:
        win = from_bounds(w, s, e, n, ds.transform).round_offsets().round_lengths()
        a = ds.read(1, window=win).astype("float32")
        t = ds.window_transform(win)
        meta = dict(url=GEOID_URL, crs=str(ds.crs), west=t.c, north=t.f, dx=t.a, dy=t.e, shape=list(a.shape),
                    note="pixel-is-area grid of EGM2008 geoid undulation N (m), h_ellipsoid = H_msl + N; bilinear between cell centres",
                    made=time.strftime("%Y-%m-%d %H:%M:%S"), tags=ds.tags())
    np.save(GEOID_NPY, a)
    with open(GEOID_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return meta


def main():
    if "--list" in sys.argv:
        for lat, lon, what in TILES:
            print(tile_name(lat, lon), "-", what)
        return
    os.makedirs(RAW, exist_ok=True)
    man_path = os.path.join(RAW, "manifest.json")
    try:
        man = json.load(open(man_path, encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    files = man.get("files", {})
    for lat, lon, what in TILES:
        p, url = tile_path(lat, lon), tile_url(lat, lon)
        name = os.path.basename(p)
        if os.path.exists(p) and name in files and files[name].get("bytes") == os.path.getsize(p):
            continue
        t0 = time.time()
        n = download(url, p)
        if n is None:
            print("missing in bucket (sea?):", name, flush=True)
            files[name] = dict(url=url, missing=True, what=what)
            continue
        files[name] = dict(url=url, bytes=n, sha256=sha256(p), what=what, lat=lat, lon=lon, downloaded=time.strftime("%Y-%m-%d %H:%M:%S"))
        print("%-50s %6.1f MB %5.1f s  %s" % (name, n / 1e6, time.time() - t0, what), flush=True)
        man.update(files=files)
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=1, ensure_ascii=False)
    if not os.path.exists(GEOID_NPY):
        g = fetch_geoid()
        print("geoid window", g["shape"], flush=True)
    man.update(source="Copernicus DEM GLO-30 (COG, AWS open data bucket, no account)", bucket=BUCKET,
               registry="https://registry.opendata.aws/copernicus-dem/", heights="orthometric, EGM2008 geoid (MSL), metres",
               geoid=dict(url=GEOID_URL, box=GEOID_BOX, file=os.path.basename(GEOID_NPY)),
               attribution="© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved",
               scope="South Korea only (cells with ROK land; border cells kept whole)",
               updated=time.strftime("%Y-%m-%d %H:%M:%S"), files=files,
               total_bytes=sum(v.get("bytes", 0) for v in files.values()))
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    print("done: %d tiles, %.0f MB -> %s" % (sum(1 for v in files.values() if not v.get("missing")), man["total_bytes"] / 1e6, RAW), flush=True)


if __name__ == "__main__":
    main()
