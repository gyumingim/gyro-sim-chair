"""Photo relief worker (11-11, docs/photo-relief-busan.md): a small height field made from the V-World ortho photo at
render time, for the ground material's lighting (normals) and height-field shadows. RAM only - nothing derived from the
photo is ever written to disk (V-World terms 13-10 / 19-4 / 19-6: no changed or stored copies; see the doc).

Runs in its own Python with torch (a venv outside the repo, e.g. C:/Users/a3162/venvs/photodepth), started by
unreal/GyroSim/Content/Python/photo_relief.py at Play and exiting with it:
    <venv>/python.exe -I sim/photo_relief.py --port <p> --photo "<url template>" --parent-pid <pid>

GET /relief/{x}/{y}.png   z18 tile x / y (Google rows) -> 512 x 512 16-bit greyscale PNG at z19 pixel size (~0.24 m):
    height above the local ground / H_MAX (0..H_MAX m), forest luminance detail folded in (LUM_AMT); 0 on the 3D building
    footprints of the building tiles (+ MARGIN_M, soft edge). One channel keeps the PNG small (UE imports it on the game
    thread).
GET /status               counters, timings (JSON)

Height = max(AI, objects):
  AI       Depth Anything V2 Small (Apache-2.0, Hugging Face depth-anything/Depth-Anything-V2-Small-hf, local files only)
           on a 768 px window (the tile + 128 px of context on every side: no seams), relative depth minus a local
           grey-opening baseline (OPEN_M): things narrower than OPEN_M (trees, walls, sheds, small houses) stand out, a
           road or a plaza stays at 0; x GAIN (m per model unit, assumed), minus a DEAD_M dead zone (no asphalt noise).
           The model does not see cars or beach umbrellas at 0.24 m / px (measured 11-11), hence:
  objects  compact blobs that differ from the local median photo brightness (|L - median 9 m| > OBJ_T), opened by a
           1.2 m square (lane lines, crosswalk stripes out), 2..OBJ_AMAX m2, not on vegetation and not on AI relief
           -> OBJ_H m (cars, umbrellas, kiosks).
Inside the building tiles' footprints (GIS _merged arrays, the same source as sim/buildings_build.py tiles) the relief is
0 (A = 0) so a 3D building never rises twice; buildings missing from the tiles keep their AI relief.
"""
import argparse, io, json, math, os, sys, threading, time, urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

H_MAX = 32.0                 # m, R channel range
L_MAX = 1.0                  # m, G channel range (signed)
GAIN = float(os.environ.get("GYROSIM_RELIEF_GAIN", "20"))     # m per model unit (user 11-11: 20 = x4 of the first 5; no metric scale -> assumed)
OPEN_M = 12.0                # m, baseline opening width
DEAD_M = 0.025 * GAIN        # m, dead zone (flat asphalt / sand stays flat); same floor in model units at any gain (0.5 m at 20)
OBJ_T, OBJ_AMIN, OBJ_AMAX, OBJ_H = 0.12, 2.0, 40.0, 1.5
LUM_VEG = 4.0                # m per unit of luminance detail on vegetation
LUM_AMT = float(os.environ.get("GYROSIM_RELIEF_LUM", "0.5"))   # x of that added to the height (forest crowns)
MARGIN_M = 1.5               # m around 3D building footprints
BLDG = os.environ.get("GYROSIM_BLDG_MERGED", r"C:\GyroSimTiles\buildings\work\_merged")
MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
TILE, CTX = 512, 128         # z19 px per z18 tile, context px
WIN = TILE + 2 * CTX
INFER = 770                  # model input (multiple of 14)


def tile_px_m(y18):
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y18 + 0.5) / 2 ** 18))))
    return 40075016.686 * math.cos(math.radians(lat)) / 2 ** 19 / 256


class Footprints:
    """outer rings of the building tiles' footprints, lon / lat bbox per polygon (numpy, memory-mapped arrays)."""

    def __init__(self, d=BLDG):
        import numpy as np
        self.ok = False
        try:
            L = lambda k: np.load(os.path.join(d, k + ".npy"), mmap_mode="r")
            lon, lat, nring, rop = L("lon"), L("lat"), np.asarray(L("nring")), np.asarray(L("ring_of_poly"))
        except Exception as e:
            print("photo_relief: no footprints (%r) - no building mask" % (e,), flush=True)
            return
        start = np.concatenate(([0], np.cumsum(nring)[:-1]))
        first = np.ones(len(rop), bool)
        first[1:] = rop[1:] != rop[:-1]                     # first ring of each polygon = outer ring
        self.s, self.n = start[first], nring[first]
        self.lon, self.lat = np.asarray(lon), np.asarray(lat)
        self.x0 = np.minimum.reduceat(self.lon, start)[first]; self.x1 = np.maximum.reduceat(self.lon, start)[first]
        self.y0 = np.minimum.reduceat(self.lat, start)[first]; self.y1 = np.maximum.reduceat(self.lat, start)[first]
        self.ok = True
        print("photo_relief: %d footprints" % len(self.s), flush=True)

    def mask(self, px0, py0, size, z=19):
        """uint8 size x size, 1 inside a footprint; window origin = global z19 pixel (px0, py0)."""
        import numpy as np
        from PIL import Image, ImageDraw
        im = Image.new("L", (size, size), 0)
        if not self.ok:
            return np.zeros((size, size), np.uint8)
        n2 = 2 ** z * 256
        lon0, lon1 = px0 / n2 * 360 - 180, (px0 + size) / n2 * 360 - 180
        lat = lambda py: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n2))))
        lat1, lat0 = lat(py0), lat(py0 + size)
        sel = np.nonzero((self.x1 >= lon0) & (self.x0 <= lon1) & (self.y1 >= lat0) & (self.y0 <= lat1))[0]
        dr = ImageDraw.Draw(im)
        for i in sel:
            a, b = self.s[i], self.s[i] + self.n[i]
            lo, la = self.lon[a:b], self.lat[a:b]
            x = (lo + 180) / 360 * n2 - px0
            y = (1 - np.arcsinh(np.tan(np.radians(la))) / np.pi) / 2 * n2 - py0
            if len(x) >= 3:
                dr.polygon(list(zip(x.tolist(), y.tolist())), fill=1)
        return np.asarray(im, np.uint8)


class Relief:
    def __init__(self, photo, lru=96):
        import torch
        from transformers import AutoModelForDepthEstimation
        self.torch = torch
        self.photo = photo
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        dt = torch.float16 if self.dev == "cuda" else torch.float32
        self.model = AutoModelForDepthEstimation.from_pretrained(MODEL, dtype=dt, local_files_only=True).to(self.dev).eval()
        self.dt = dt
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.dev).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.dev).view(1, 3, 1, 1)
        self.fp = Footprints()
        self.gpu = threading.Lock()
        self.cache, self.lru = OrderedDict(), lru           # result PNG bytes (RAM)
        self.ph, self.ph_lru = OrderedDict(), 256           # decoded photo tiles (RAM)
        self.stats = dict(served=0, made=0, ms_total=0.0, ms_infer=0.0, ms_last=None, photo_miss=0, err=0)

    # ---- photo (RAM only) --------------------------------------------------------------------------------------
    def _tile(self, z, x, y):
        import numpy as np
        from PIL import Image
        k = (z, x, y)
        if k in self.ph:
            self.ph.move_to_end(k)
            return self.ph[k]
        url = self.photo.replace("{z}", str(z)).replace("{x}", str(x)).replace("{reverseY}", str(y)).replace("{y}", str(y))
        a = None
        try:
            if url.startswith("file:///"):
                with open(url[8:], "rb") as f:
                    b = f.read()
            else:
                with urllib.request.urlopen(url, timeout=10) as r:
                    b = r.read()
            a = np.asarray(Image.open(io.BytesIO(b)).convert("RGB"), np.uint8)
            if a.shape[:2] != (256, 256):
                a = np.asarray(Image.fromarray(a).resize((256, 256)), np.uint8)
        except Exception:
            self.stats["photo_miss"] += 1
        self.ph[k] = a
        if len(self.ph) > self.ph_lru:
            self.ph.popitem(last=False)
        return a

    def window(self, x18, y18):
        import numpy as np
        big = np.zeros((1024, 1024, 3), np.uint8)
        have = np.zeros((1024, 1024), bool)
        for j in range(4):
            for i in range(4):
                a = self._tile(19, 2 * x18 - 1 + i, 2 * y18 - 1 + j)
                if a is not None:
                    big[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = a
                    have[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = True
        c = slice(CTX, CTX + WIN)
        return big[c, c], have[c, c]

    # ---- height -------------------------------------------------------------------------------------------------
    def height(self, img, pxm):
        """img uint8 WIN x WIN x 3 -> (h_ai+objects m, lum detail m) float32 WIN x WIN (GPU except the blob labels)"""
        import numpy as np
        from scipy import ndimage as ndi
        torch = self.torch
        F = torch.nn.functional
        mp = lambda x, k: F.max_pool2d(F.pad(x, (k // 2,) * 4, mode="replicate"), k, 1)      # dilation, k odd
        t0 = time.perf_counter()
        a = torch.from_numpy(img).to(self.dev).permute(2, 0, 1)[None].float() / 255
        x = F.interpolate(a, (INFER, INFER), mode="bicubic", align_corners=False)
        with torch.no_grad():
            d = self.model(pixel_values=((x - self.mean) / self.std).to(self.dt)).predicted_depth[:, None].float()
        d = F.interpolate(d, (WIN, WIN), mode="bilinear", align_corners=False)
        k = int(OPEN_M / pxm) | 1
        base = F.avg_pool2d(F.pad(mp(-mp(-d, k), k), (4,) * 4, mode="replicate"), 9, 1)      # grey opening, smoothed
        h = (((d - base).clamp(min=0) * GAIN) - DEAD_M).clamp(min=0)
        L = (a * torch.tensor([0.2126, 0.7152, 0.0722], device=self.dev).view(1, 3, 1, 1)).sum(1, keepdim=True)
        # objects (cars, umbrellas): compact blobs off the local median brightness (~9 m), on flat non-vegetation ground
        Ls = F.avg_pool2d(L, 4)
        km = max(3, int(9.0 / (4 * pxm)) | 1)
        med = F.unfold(F.pad(Ls, (km // 2,) * 4, mode="replicate"), km).median(1)[0].view(Ls.shape)
        bg = F.avg_pool2d(F.pad(F.interpolate(med, scale_factor=4, mode="nearest"), (2,) * 4, mode="replicate"), 5, 1)
        raw = ((L - bg).abs() > OBJ_T).float()
        raw = mp(-mp(-raw, 5), 5)                                                            # opening 5 x 5 (~1.2 m)
        mx, mn = a.max(1, keepdim=True)[0], a.min(1, keepdim=True)[0]
        veg = (((a[:, 1:2] - torch.maximum(a[:, 0:1], a[:, 2:3]) - 0.015) * 25).clamp(0, 1)
               * (((mx - mn) / mx.clamp(min=1e-3) - 0.08) * 6).clamp(0, 1))
        ld = ((L - F.avg_pool2d(F.pad(L, (3,) * 4, mode="replicate"), 7, 1)) * LUM_VEG * veg).clamp(-L_MAX, L_MAX)
        gate = (1 - h.clamp(0, 1)) * (1 - veg)
        rn = raw[0, 0].to(torch.uint8).cpu().numpy()
        if self.dev == "cuda":
            torch.cuda.synchronize()
        self.stats["ms_infer"] += (time.perf_counter() - t0) * 1000
        lab, n = ndi.label(rn)
        if n:
            area = np.bincount(lab.ravel(), minlength=n + 1).astype(np.float32) * pxm * pxm
            keep = (area >= OBJ_AMIN) & (area <= OBJ_AMAX)
            keep[0] = False
            mo = torch.from_numpy(keep[lab].astype(np.float32)).to(self.dev)[None, None]
            mo = F.avg_pool2d(F.pad(mo * gate, (1,) * 4, mode="replicate"), 3, 1)
            h = torch.maximum(h, mo * OBJ_H)
        return h[0, 0].cpu().numpy(), ld[0, 0].cpu().numpy()

    def make(self, x18, y18):
        import numpy as np
        from PIL import Image
        from scipy import ndimage as ndi
        k = (x18, y18)
        if k in self.cache:
            self.cache.move_to_end(k)
            self.stats["served"] += 1
            return self.cache[k]
        t0 = time.perf_counter()
        img, have = self.window(x18, y18)
        pxm = tile_px_m(y18)
        with self.gpu:
            if have.any():
                h, ld = self.height(img, pxm)
            else:
                h = ld = np.zeros((WIN, WIN), np.float32)
        c = slice(CTX, CTX + TILE)
        h, ld, hv = h[c, c], ld[c, c], have[c, c]
        fm = self.fp.mask(x18 * TILE, y18 * TILE, TILE)
        r = max(1, int(round(MARGIN_M / pxm)))
        fm = ndi.maximum_filter(fm, size=2 * r + 1) > 0                       # + MARGIN_M (separable)
        allow = ndi.uniform_filter((~fm & hv).astype(np.float32), 3)
        h = np.maximum(h, h + LUM_AMT * ld)           # forest crowns (bright = up); no dips below the ground
        h = h * allow                                 # 0 on a 3D building (its edges would rise twice), soft edge
        png = _png16(np.clip(h / H_MAX * 65535, 0, 65535).astype(np.uint16))
        self.cache[k] = png
        if len(self.cache) > self.lru:
            self.cache.popitem(last=False)
        ms = (time.perf_counter() - t0) * 1000
        self.stats.update(made=self.stats["made"] + 1, served=self.stats["served"] + 1, ms_total=self.stats["ms_total"] + ms,
                          ms_last=round(ms, 1))
        return png


def _png16(g):
    """16-bit greyscale PNG bytes (filter 0; UE imports it as G16 = linear, no sRGB step)."""
    import struct, zlib
    import numpy as np
    h, w = g.shape
    raw = np.zeros((h, 1 + w * 2), np.uint8)
    raw[:, 1:] = g.astype(">u2").view(np.uint8).reshape(h, w * 2)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6)) + chunk(b"IEND", b""))


def serve(port, photo, parent):
    R = Relief(photo)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?", 1)[0].strip("/").split("/")
            try:
                if len(p) == 3 and p[0] == "relief" and p[2].endswith(".png"):
                    return self._send(200, R.make(int(p[1]), int(p[2][:-4])), "image/png")
                if p == ["status"]:
                    s = dict(R.stats, cache=len(R.cache), device=R.dev, footprints=R.fp.ok, gain=GAIN)
                    return self._send(200, json.dumps(s).encode(), "application/json")
            except Exception as e:
                R.stats["err"] += 1
                return self._send(500, repr(e).encode(), "text/plain")
            self._send(404, b"not found", "text/plain")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    if parent:
        def watch():
            import ctypes
            while True:
                time.sleep(2.0)
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, parent) if sys.platform == "win32" else 1
                alive = False
                if h:
                    code = ctypes.c_ulong()
                    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
                    ctypes.windll.kernel32.CloseHandle(h)
                    alive = code.value == 259
                if not alive:
                    os._exit(0)
        threading.Thread(target=watch, daemon=True).start()
    print("photo_relief: serving on 127.0.0.1:%d (%s)" % (port, R.dev), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8782)
    ap.add_argument("--photo", default="http://127.0.0.1:8790/vworld/sat/{z}/{reverseY}/{x}.jpg")
    ap.add_argument("--parent-pid", type=int, default=0)
    a = ap.parse_args()
    serve(a.port, a.photo, a.parent_pid)
