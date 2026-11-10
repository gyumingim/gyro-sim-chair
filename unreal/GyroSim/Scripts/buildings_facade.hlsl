// Procedural facades for the local 3D buildings (sim/buildings_build.py glb tiles), body of the Custom node in
// /Game/Buildings/M_GyroBuilding (Scripts/buildings_material.py pastes this file in). Material only, no extra geometry.
// Inputs:  UV (u = bays along the footprint ring, v = floors counted down from the roof line; v < 0 = parapet),
//          VC (vertex colour: rgb = wall tint, a = 128 + 64 * end-wall flag + seed 0..63),
//          R (glTF roughnessFactor = 0.60 + 0.01 * style; 0.8 / 0.95 = older tiles), Tex (baseColorTexture * factor:
//          roof photo / stock wall module), N (vertex normal, world), V (camera vector, world, surface -> eye),
//          P (camera-relative world position, cm), L (direction to the sun, SkyAtmosphereLightDirection)
// Outputs: return = base colour; Rough, Metal, Spec, NormalWS (world space: the material has tangent space normals off)
// Styles: 0 plain, 1 house, 2 apartment (balcony glazing + railing panels), 3 shopfront, 4 punched windows,
//         5 factory panels, 6 office curtain wall (half with deep vertical fins), 7 glass residential tower, 8 ribbon windows
// Depth, all analytic per pixel (no parallax loop): every opening is a box recess of depth dR behind the wall plane.
// The view ray decides glass vs reveal (jamb / sill / head): reveals get their own world normal (lit correctly by the
// engine) and a sun shadow test (ray from the hit point back to the wall plane toward the sun: blocked = in shadow).
// Behind the glass: interior mapping (J. van Dongen, "Interior Mapping", CGI 2008) - a box room per bay x floor.

Rough = saturate(R); Metal = 0.0; Spec = 0.5; NormalWS = N;
bool isNew = (R > 0.595) && (R < 0.695);
if (!isNew)
{
    return Tex * VC.rgb;                                    // roofs (photo atlas) and tiles from before the facade styles
}
int style = (int)round((R - 0.60) * 100.0);
float a255 = round(VC.a * 255.0);
float endw = (a255 >= 192.0) ? 1.0 : 0.0;
float seed = fmod(a255, 64.0);
float3 wall = VC.rgb * float3(1.05, 1.0, 0.92);             // warmer: the photo-derived tints read lavender under the blue sky light

#define H1(x) frac(sin((x) * 12.9898 + seed * 78.233) * 43758.5453)
// box-filtered 1D pulse [a, b] in a cell coordinate x with filter width w (anti-aliased edges)
#define PULSE(x, a, b, w) saturate((min((x) + (w) * 0.5, (b)) - max((x) - (w) * 0.5, (a))) / max((w), 1e-4))
#define INSIDE(p, W) (step((W).x, (p).x) * step((p).x, (W).y) * step((W).z, (p).y) * step((p).y, (W).w))

float2 cell = floor(UV);
float2 f = frac(UV);
f.y = 1.0 - f.y;                                            // y up inside a floor (0 = floor slab, 1 = ceiling)
float2 fw = max(abs(ddx(UV)) + abs(ddy(UV)), 1e-4);         // cells per pixel
float far = saturate((max(fw.x, fw.y) - 0.18) / 0.3);       // 0 near .. 1 = sub-pixel cells: use the average look
float bayH = H1(cell.x * 1.7 + cell.y * 31.1);
float bayH2 = H1(cell.x * 5.3 + cell.y * 7.7 + 3.1);
float parapet = (UV.y < 0.0) ? 1.0 : 0.0;

// --- per style ----------------------------------------------------------------------------------------------------------
float4 win = float4(0, 0, 0, 0);
float4 win2 = float4(0, 0, 0, 0);
float glassMetal = 0.0, glassRough = 0.06, wallRough = 0.85, wallMetal = 0.0;
float3 tint = float3(0.08, 0.10, 0.11);
float mull = 0.0;
float accent = 0.0;
float dR = 20.0;                                            // cm, recess of the glass behind the wall plane
float rail = 0.0;                                           // apartment railing / balustrade panel height (cell units) at the glass
float3 tints[6] = { float3(0.36, 0.50, 0.56), float3(0.44, 0.52, 0.60), float3(0.42, 0.36, 0.28),
                    float3(0.34, 0.38, 0.42), float3(0.32, 0.46, 0.40), float3(0.26, 0.36, 0.52) };
float3 accents[6] = { float3(0.05, 0.16, 0.45), float3(0.02, 0.30, 0.30), float3(0.40, 0.08, 0.05),
                      float3(0.08, 0.30, 0.10), float3(0.03, 0.06, 0.20), float3(0.60, 0.22, 0.03) };
float3 gtint = tints[(int)fmod(seed, 6.0)];
float3 acc = accents[(int)fmod(floor(seed / 6.0), 6.0)];
float bayM = 300.0, floorM = 290.0;

if (style == 1)          { win = float4(0.27, 0.73, 0.30, 0.76); mull = 1.0; bayM = 360.0; dR = 18.0; }
else if (style == 2)
{
    bayM = 300.0; dR = 45.0;                                 // enclosed balcony: glazing set back from the slab edge
    win = float4(0.04, 0.96, 0.13, 0.90); mull = 2.0;
    rail = (fmod(seed, 3.0) < 2.0) ? 0.40 : 0.30;            // railing panel (frosted / solid) on the lower glass
    if (endw > 0.5)                                          // gable wall: small windows, brand stripes
    {
        win = (fmod(cell.x, 3.0) == 1.0) ? float4(0.35, 0.65, 0.35, 0.72) : float4(0, 0, 0, 0);
        rail = 0.0; dR = 18.0;
        accent = (fmod(cell.x + floor(seed / 16.0), 4.0) == 0.0) ? 1.0 : 0.0;
    }
    accent = max(accent, (cell.y < 1.5 && fmod(seed, 2.0) < 1.0) ? 0.8 : 0.0);
}
else if (style == 3)     { win = float4(0.03, 0.97, 0.05, 0.70); mull = 2.0; bayM = 400.0; floorM = 360.0; wallRough = 0.6; dR = 25.0; }
else if (style == 4)     { win = float4(0.08, 0.44, 0.30, 0.76); win2 = float4(0.56, 0.92, 0.30, 0.76); bayM = 320.0; floorM = 340.0; dR = 22.0; }
else if (style == 5)     { win = float4(0.06, 0.94, 0.78, 0.90); mull = 4.0; bayM = 600.0; floorM = 600.0; wallRough = 0.5; wallMetal = 0.35; dR = 8.0; }
else if (style == 6)
{
    bayM = 320.0; floorM = 360.0; glassMetal = 0.6; glassRough = 0.05; tint = gtint * 0.8; wallMetal = 0.5; wallRough = 0.3;
    bool fins = fmod(seed, 2.0) < 1.0;                       // half of the office towers: deep vertical fins at each bay edge
    win = fins ? float4(0.035, 0.965, 0.16, 0.99) : float4(0.015, 0.985, 0.16, 0.985);
    mull = fins ? 1.0 : 2.0; dR = fins ? 60.0 : 10.0;
}
else if (style == 7)                                         // Marine City / Haeundae residential towers: light blue / silver glass
{
    win = float4(0.02, 0.98, 0.12, 0.93); mull = 2.0; bayM = 300.0; floorM = 300.0; glassMetal = 0.3; glassRough = 0.04; wallRough = 0.5; dR = 15.0;
    gtint = (fmod(seed, 3.0) < 1.0) ? float3(0.44, 0.54, 0.62) : ((fmod(seed, 3.0) < 2.0) ? float3(0.38, 0.52, 0.60) : float3(0.50, 0.56, 0.60));
    tint = gtint * 1.2;
}
else if (style == 8)     { win = float4(0.0, 1.0, 0.36, 0.80); mull = 2.0; bayM = 320.0; floorM = 360.0; glassMetal = 0.25; tint = gtint * 0.7; dR = 25.0; }
if (parapet > 0.5) { win = float4(0, 0, 0, 0); win2 = win; accent = 0.0; }
float4 W = (win2.y > 0.0 && f.x > 0.5) ? win2 : win;

// --- tangent frame: T along +u (sign from screen derivatives: glTF -> Unreal flips handedness) -------------------------------
float3 Nn = normalize(N);
float3 up = float3(0, 0, 1);
float3 T = cross(up, Nn);
T = (dot(T, T) > 1e-4) ? normalize(T) : float3(1, 0, 0);
float sgn = dot(T, ddx(P)) * ddx(UV).x + dot(T, ddy(P)) * ddy(UV).x;
T *= (sgn < 0.0) ? -1.0 : 1.0;
float3 rd = -normalize(V);
float3 Ls = normalize(L + float3(0, 0, 1e-4));
bool sunFront = dot(Ls, Nn) > 0.02;

// --- opening at the wall plane (anti-aliased) ---------------------------------------------------------------------------------
float open = PULSE(f.x, W.x, W.y, fw.x) * PULSE(f.y, W.z, W.w, fw.y);
float area = (win.y - win.x) * (win.w - win.z) + (win2.y - win2.x) * (win2.w - win2.z);

// --- recess: ray in cell units (x / bay, y / floor, z / recess depth); glass at z = 1 ---------------------------------------
float3 rr = float3(dot(rd, T) / bayM, dot(rd, up) / floorM, max(-dot(rd, Nn), 1e-3) / dR);
float sG = 1.0 / rr.z;
float2 pg = f + rr.xy * sG;                                  // where the ray meets the glass plane
float sx = (rr.x > 0.0 ? (W.y - f.x) : (W.x - f.x)) / (abs(rr.x) > 1e-6 ? rr.x : 1e-6);
float sy = (rr.y > 0.0 ? (W.w - f.y) : (W.z - f.y)) / (abs(rr.y) > 1e-6 ? rr.y : 1e-6);
sx = (sx > 0.0) ? sx : 1e9; sy = (sy > 0.0) ? sy : 1e9;
float sHit = min(sG, min(sx, sy));
bool onGlass = sHit >= sG - 1e-5;
float2 ph = f + rr.xy * sHit;
float zh = rr.z * sHit;                                      // depth of the hit 0..1
float3 nRev = (sx < sy) ? (-sign(rr.x) * T) : (rr.y < 0.0 ? up : -up);   // jamb / sill / head face normal
// sun shadow: from the hit point toward the sun back to the wall plane; leaving the opening there = blocked
float3 lc = float3(dot(Ls, T) / bayM, dot(Ls, up) / floorM, dot(Ls, Nn) / dR);
float2 q = ph + lc.xy * (zh / max(lc.z, 1e-4));
float lit = sunFront ? INSIDE(q, W) : 1.0;
lit = lerp(lit, 1.0, far);
float revAO = lerp(1.0, 0.55, zh);                           // reveals darker deeper in (sky light blocked)

// --- interior behind the glass ----------------------------------------------------------------------------------------------
float dRoom = (style == 3) ? 500.0 : 420.0;
float3 r2 = float3(rr.x, rr.y, rr.z * dR / dRoom);
float3 o = float3(saturate(pg.x), saturate(pg.y), 0.0);
float3 tb = (step(0.0, r2) - o) / r2;
float t = min(min(tb.x, tb.y), tb.z);
float3 h = o + r2 * t;
float rh = H1(cell.x * 3.1 + cell.y * 17.3 + 0.7);
float3 room = lerp(float3(0.30, 0.27, 0.22), float3(0.22, 0.24, 0.27), step(0.5, rh)) * (0.6 + 0.6 * bayH2);
float3 inner;
if (t == tb.z)       inner = room;
else if (t == tb.y)  inner = (r2.y < 0.0) ? room * float3(0.75, 0.6, 0.45) : room * 1.25;
else                 inner = room * 0.8;
inner *= lerp(1.0, 0.45, h.z);
float cur = (bayH < 0.35) ? step(1.0 - 0.5 * bayH2, pg.y) : ((bayH > 0.85) ? 1.0 : 0.0);
inner = lerp(inner, float3(0.55, 0.52, 0.46) * (0.7 + 0.3 * bayH2), cur);
inner *= 0.35;
if (style == 3) inner = lerp(inner, inner * 2.2, step(0.5, bayH));

// --- glass pane (with mullions / railing panel at the glass plane) -----------------------------------------------------------
float3 glass = lerp(inner * (0.6 + tint), tint, glassMetal);
float gRough = glassRough + 0.04 * bayH2;
float gMetal = glassMetal;
float3 gN = normalize(Nn + T * (bayH - 0.5) * 0.035 + up * (bayH2 - 0.5) * 0.035);
float fm = frac(pg.x * max(mull, 1.0));
float frame = (mull > 0.0) ? (1.0 - step(0.03, fm) * step(fm, 0.97)) : 0.0;
float frameH = 1.0 - step(W.z + 0.025, pg.y) * step(pg.y, W.w - 0.025);              // sash at the glass edges
frame = max(frame, frameH);
float3 frameCol = (style == 6 || style == 7) ? gtint * 0.5 : float3(0.75, 0.75, 0.73);
float railP = (rail > 0.0) ? step(pg.y, W.z + rail) : 0.0;                          // balcony balustrade panel
float3 railCol = (fmod(seed, 3.0) < 1.0) ? wall * 0.95 : float3(0.55, 0.62, 0.64);  // solid (wall colour) or frosted glass
glass = lerp(glass, railCol, railP);
gRough = lerp(gRough, 0.35, railP);
gMetal = lerp(gMetal, 0.0, railP);
glass = lerp(glass, frameCol, frame);
gRough = lerp(gRough, 0.4, frame);
gMetal = lerp(gMetal, (style == 6 || style == 7) ? 0.6 : 0.2, frame);
gN = normalize(lerp(gN, Nn, max(frame, railP)));
// rail top bar (lighter, catches the sky)
float bar = (rail > 0.0) ? PULSE(pg.y, W.z + rail, W.z + rail + 0.025, fw.y) : 0.0;
glass = lerp(glass, float3(0.8, 0.8, 0.78), bar);
glass *= lerp(0.45, 1.0, lit);                               // head / jamb shadow on the glass and the room

// --- reveal (jamb / sill / head) ----------------------------------------------------------------------------------------------
float3 rev = wall * 0.9 * revAO * lerp(0.35, 1.0, lit);
if (style == 6 && dR > 30.0) rev = lerp(wall, gtint, 0.3) * 0.8 * revAO * lerp(0.35, 1.0, lit);   // aluminium fins

// --- wall finish: tint, accents, slab bands, weathering streaks, patching -------------------------------------------------------
float3 w = wall;
if (style == 6 || style == 7) w = lerp(wall, gtint * 0.9, 0.45);   // spandrel panels between the glass bands
w = lerp(w, acc, saturate(accent) * (1.0 - open));
float slab = PULSE(f.y, 0.0, 0.05, fw.y) * (1.0 - far);
w *= 1.0 - 0.08 * slab;
float under = (style == 2 && endw < 0.5) ? (1.0 - far) * PULSE(f.y, 0.92, 1.0, fw.y) : 0.0;   // underside of the slab above
w *= 1.0 - 0.25 * under;
float streak = (1.0 - far) * step(W.x, f.x) * step(f.x, W.y) * saturate((W.z - f.y) / max(W.z, 1e-3)) * (0.5 + 0.5 * bayH);
w *= 1.0 - 0.12 * streak;
float grime = H1(floor(UV.x * 0.5) * 0.71 + 5.3);            // a few bays wide stains, stronger low on the band of each floor
w *= 1.0 - 0.06 * grime * (1.0 - f.y) * (1.0 - far);
w *= 0.94 + 0.12 * H1(cell.y * 0.37 + 9.1) * (1.0 - far);
if (style == 3)
{
    float sb = PULSE(f.y, 0.76, 0.94, fw.y) * (1.0 - far);
    float3 sc = float3(H1(cell.x + 1.3), H1(cell.x + 2.9), H1(cell.x + 4.1));
    w = lerp(w, sc * sc * 0.8 + 0.05, sb * step(0.25, bayH));
}
if (style == 5)
{
    float rib = frac(f.x * 12.0);
    w *= 1.0 - 0.12 * PULSE(rib, 0.0, 0.15, fw.x * 12.0) * (1.0 - far);
}
if (parapet > 0.5) w *= 0.92;
// slab edge bevel: top of the band catches the sky, the bottom edge faces down
float3 wN = Nn;
float bev = (1.0 - far) * (PULSE(f.y, 0.045, 0.06, fw.y) - PULSE(f.y, 0.0, 0.012, fw.y));
wN = normalize(Nn + up * 0.5 * bev);

// --- combine --------------------------------------------------------------------------------------------------------------------
float3 insC = onGlass ? glass : rev;
float insR = onGlass ? gRough : 0.8;
float insM = onGlass ? gMetal : 0.0;
float3 insN = onGlass ? gN : nRev;
// far away: average of glass and reveal, flat normal
float3 avgIn = lerp(glass, rev, 0.25);
insC = lerp(insC, avgIn, far);
insN = normalize(lerp(insN, Nn, far));
float m = lerp(open, area, far);
float3 col = lerp(w, insC, m);
Rough = lerp(wallRough, insR, m);
Metal = lerp(wallMetal, insM, m);
Spec = lerp(0.35, 0.5, m);
NormalWS = normalize(lerp(wN, insN, m));
return col;
