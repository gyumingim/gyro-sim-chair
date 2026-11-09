// Procedural facades for the local 3D buildings (sim/buildings_build.py glb tiles), body of the Custom node in
// /Game/Buildings/M_GyroBuilding (Scripts/buildings_material.py pastes this file in). Material only, no extra geometry.
// Inputs:  UV (u = bays along the footprint ring, v = floors counted down from the roof line), VC (vertex colour:
//          rgb = wall tint, a = 128 + 64 * end-wall flag + seed 0..63), R (glTF roughnessFactor = 0.60 + 0.01 * style;
//          0.8 / 0.95 = older tiles), Tex (baseColorTexture * baseColorFactor: roof photo / stock wall module),
//          N (vertex normal, world), V (camera vector, world, surface -> eye), P (camera-relative world position, cm)
// Outputs: return = base colour; Rough, Metal, Spec, NormalWS (world-space normal: the material has tangent space normals off)
// Styles: 0 plain, 1 house, 2 apartment (balcony glazing), 3 shopfront, 4 punched windows, 5 factory panels,
//         6 office curtain wall, 7 glass residential tower, 8 office ribbon windows
// Interior mapping: J. van Dongen, "Interior Mapping" (CGI 2008) - a ray from the window into a box room per bay x floor.

Rough = saturate(R); Metal = 0.0; Spec = 0.5; NormalWS = N;
float3 col = Tex;
bool isNew = (R > 0.595) && (R < 0.695);
if (!isNew)
{
    return Tex * VC.rgb;                                    // roofs (photo atlas) and tiles from before the facade styles
}
int style = (int)round((R - 0.60) * 100.0);
float a255 = round(VC.a * 255.0);
float endw = (a255 >= 192.0) ? 1.0 : 0.0;
float seed = fmod(a255, 64.0);
float3 wall = VC.rgb * float3(1.05, 1.0, 0.92);                   // warmer: the photo-derived tints read lavender under the blue sky light

// --- helpers --------------------------------------------------------------------------------------------------------
#define H1(x) frac(sin((x) * 12.9898 + seed * 78.233) * 43758.5453)
// box-filtered 1D pulse [a, b] in a cell coordinate x with filter width w (anti-aliased window edges)
#define PULSE(x, a, b, w) saturate((min((x) + (w) * 0.5, (b)) - max((x) - (w) * 0.5, (a))) / max((w), 1e-4))

float2 cell = floor(UV);
float2 f = frac(UV);
f.y = 1.0 - f.y;                                            // y up inside a floor (0 = floor slab, 1 = ceiling)
float2 fw = max(abs(ddx(UV)) + abs(ddy(UV)), 1e-4);         // cells per pixel
float far = saturate((max(fw.x, fw.y) - 0.18) / 0.3);       // 0 near .. 1 = sub-pixel cells: use the average look
float bayH = H1(cell.x * 1.7 + cell.y * 31.1);              // per window cell
float bayH2 = H1(cell.x * 5.3 + cell.y * 7.7 + 3.1);

// --- per style: window rectangle (x0 x1 y0 y1), glass tint / reflectivity, wall finish ---------------------------------
float4 win = float4(0, 0, 0, 0);
float4 win2 = float4(0, 0, 0, 0);                            // second window in the bay (punched)
float glassMetal = 0.0, glassRough = 0.06, wallRough = 0.85, wallMetal = 0.0;
float3 tint = float3(0.08, 0.10, 0.11);
float mull = 0.0;                                            // mullions per bay (vertical bars)
float accent = 0.0;
// glass tints of office / tower curtain walls, picked per building (blue-green, silver-blue, bronze, grey, green, dark blue)
float3 tints[6] = { float3(0.20, 0.32, 0.36), float3(0.30, 0.36, 0.42), float3(0.30, 0.25, 0.18),
                    float3(0.22, 0.24, 0.26), float3(0.18, 0.30, 0.24), float3(0.12, 0.18, 0.30) };
// Korean apartment brand accent colours (가정: typical blue / teal / red-brown / green / navy / orange)
float3 accents[6] = { float3(0.05, 0.16, 0.45), float3(0.02, 0.30, 0.30), float3(0.40, 0.08, 0.05),
                      float3(0.08, 0.30, 0.10), float3(0.03, 0.06, 0.20), float3(0.60, 0.22, 0.03) };
float3 gtint = tints[(int)fmod(seed, 6.0)];
float3 acc = accents[(int)fmod(floor(seed / 6.0), 6.0)];
float bayM = 300.0, floorM = 290.0;                         // cm, cell size for the interior ray

if (style == 1)          { win = float4(0.27, 0.73, 0.30, 0.76); mull = 1.0; bayM = 360.0; }
else if (style == 2)
{
    bayM = 300.0;
    win = float4(0.05, 0.95, 0.20, 0.86); mull = 2.0;
    if (endw > 0.5)                                          // gable wall: small windows, brand stripes
    {
        win = (fmod(cell.x, 3.0) == 1.0) ? float4(0.35, 0.65, 0.35, 0.72) : float4(0, 0, 0, 0);
        accent = (fmod(cell.x + floor(seed / 16.0), 4.0) == 0.0) ? 1.0 : 0.0;
    }
    accent = max(accent, (cell.y < 1.5 && fmod(seed, 2.0) < 1.0) ? 0.8 * PULSE(f.y, 0.0, 1.0, fw.y) : 0.0);
}
else if (style == 3)     { win = float4(0.03, 0.97, 0.05, 0.70); mull = 2.0; bayM = 400.0; floorM = 360.0; wallRough = 0.6; }
else if (style == 4)     { win = float4(0.08, 0.44, 0.30, 0.76); win2 = float4(0.56, 0.92, 0.30, 0.76); bayM = 320.0; floorM = 340.0; }
else if (style == 5)     { win = float4(0.06, 0.94, 0.78, 0.90); mull = 4.0; bayM = 600.0; floorM = 600.0; wallRough = 0.5; wallMetal = 0.35; }
else if (style == 6)     { win = float4(0.015, 0.985, 0.16, 0.985); mull = 2.0; bayM = 320.0; floorM = 360.0; glassMetal = 0.65; glassRough = 0.05; tint = gtint; wallMetal = 0.5; wallRough = 0.3; }
else if (style == 7)     { win = float4(0.02, 0.98, 0.12, 0.92); mull = 2.0; bayM = 300.0; floorM = 300.0; glassMetal = 0.45; glassRough = 0.05; tint = gtint * 1.2; wallRough = 0.5; }
else if (style == 8)     { win = float4(0.0, 1.0, 0.36, 0.80); mull = 2.0; bayM = 320.0; floorM = 360.0; glassMetal = 0.25; tint = gtint; }

// --- window mask (anti-aliased) ---------------------------------------------------------------------------------------
float m1 = PULSE(f.x, win.x, win.y, fw.x) * PULSE(f.y, win.z, win.w, fw.y);
float m2 = PULSE(f.x, win2.x, win2.y, fw.x) * PULSE(f.y, win2.z, win2.w, fw.y);
float mask = saturate(m1 + m2);
float area = (win.y - win.x) * (win.w - win.z) + (win2.y - win2.x) * (win2.w - win2.z);
if (mull > 0.0)
{
    float fm = frac(f.x * mull);
    float bar = 1.0 - PULSE(fm, 0.025, 0.975, fw.x * mull);          // thin frames between panes
    mask *= 1.0 - bar;
    area *= 0.95;
}
mask = lerp(mask, area, far);

// --- interior: ray into a box room behind the window --------------------------------------------------------------------
float3 Nn = normalize(N);
float3 up = float3(0, 0, 1);
float3 T = cross(up, Nn);
T = (dot(T, T) > 1e-4) ? normalize(T) : float3(1, 0, 0);
// u direction on screen decides the sign (glTF -> Unreal flips handedness)
float2 duvx = ddx(UV), duvy = ddy(UV);
float sgn = dot(T, ddx(P)) * duvx.x + dot(T, ddy(P)) * duvy.x;
T *= (sgn < 0.0) ? -1.0 : 1.0;
float3 rd = -normalize(V);
float depthM = (style == 3) ? 500.0 : 420.0;
float3 r = float3(dot(rd, T) / bayM, dot(rd, up) / floorM, max(-dot(rd, Nn), 1e-3) / depthM);
float3 o = float3(f.x, f.y, 0.0);
float3 tb = (step(0.0, r) - o) / r;                          // distance to the far planes on each axis
float t = min(min(tb.x, tb.y), tb.z);
float3 h = o + r * t;
float rh = H1(cell.x * 3.1 + cell.y * 17.3 + 0.7);
float3 room = lerp(float3(0.30, 0.27, 0.22), float3(0.22, 0.24, 0.27), step(0.5, rh)) * (0.6 + 0.6 * bayH2);
float3 inner;
if (t == tb.z)       inner = room;                            // back wall
else if (t == tb.y)  inner = (r.y < 0.0) ? room * float3(0.75, 0.6, 0.45) : room * 1.25;   // floor / ceiling
else                 inner = room * 0.8;                      // side walls
inner *= lerp(1.0, 0.45, h.z);                               // darker deep in the room
// curtains / blinds on some windows (flat, at the glass)
float cur = (bayH < 0.35) ? step(1.0 - 0.5 * bayH2, f.y) : ((bayH > 0.85) ? 1.0 : 0.0);
inner = lerp(inner, float3(0.55, 0.52, 0.46) * (0.7 + 0.3 * bayH2), cur);
inner *= 0.35;                                               // rooms are darker than the sunlit facade
inner = lerp(inner, float3(0.05, 0.05, 0.05), far);
if (style == 3) inner = lerp(inner, inner * 2.2, step(0.5, bayH));   // lit shop interiors

// --- glass: interior through a tinted pane; office glass is a coloured, partly metallic mirror --------------------------
float3 glass = lerp(inner * (0.6 + tint), tint, glassMetal);
float gRough = glassRough + 0.04 * bayH2 * (1.0 - far);

// --- wall finish: tint, accents, weathering streaks under the windows, slab lines -----------------------------------------
float3 w = wall;
if (style == 6 || style == 7) w = lerp(wall, gtint * 0.8, 0.5);      // spandrel panels between the glass bands
w = lerp(w, acc, saturate(accent));
float slab = PULSE(f.y, 0.0, 0.05, fw.y) * (1.0 - far);
w *= 1.0 - 0.10 * slab;
float streak = (1.0 - far) * step(win.x, f.x) * step(f.x, win.y) * saturate((win.z - f.y) / max(win.z, 1e-3)) * (0.5 + 0.5 * bayH);
w *= 1.0 - 0.10 * streak;
w *= 0.94 + 0.12 * H1(cell.y * 0.37 + 9.1) * (1.0 - far);           // floor-to-floor patching
if (style == 3)                                                     // shop sign band above the shop windows
{
    float sb = PULSE(f.y, 0.76, 0.94, fw.y) * (1.0 - far);
    float3 sc = float3(H1(cell.x + 1.3), H1(cell.x + 2.9), H1(cell.x + 4.1));
    w = lerp(w, sc * sc * 0.8 + 0.05, sb * step(0.25, bayH));
}
if (style == 5)                                                     // corrugated panel ribs
{
    float rib = frac(f.x * 12.0);
    w *= 1.0 - 0.12 * PULSE(rib, 0.0, 0.15, fw.x * 12.0) * (1.0 - far);
}

col = lerp(w, glass, mask);
Rough = lerp(wallRough, gRough, mask);
Metal = lerp(wallMetal, glassMetal, mask);
Spec = lerp(0.35, 0.5, mask);
// slightly different pane angles -> broken-up reflections like real glazing
float2 tilt = (float2(bayH, bayH2) - 0.5) * 0.035 * mask * (1.0 - far);
NormalWS = normalize(Nn + T * tilt.x + up * tilt.y);
return col;
