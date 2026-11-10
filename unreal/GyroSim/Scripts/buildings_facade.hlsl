// Procedural facades for the local 3D buildings (sim/buildings_build.py glb tiles), body of the Custom node in
// /Game/Buildings/M_GyroBuilding (Scripts/buildings_material.py pastes this file in). v3 (11-10): building-type detail.
// The 11-10 v2 body is kept in buildings_facade_v2.hlsl (asset M_GyroBuilding_v2, GYROSIM_BLDG_V3=0).
// Inputs:  UV (walls: u = bays along the footprint ring, v = floors counted down from the roof line, v < 0 = parapet;
//              apartment gables: u = 8192 + 64 x bays of the edge + bays along it; props: metres; roofs: photo atlas),
//          VC (vertex colour: rgb = wall tint, a = 128 + 64 * gable flag + seed 0..63; props: 128 + 16 x kind + seed 0..15),
//          R (glTF roughnessFactor = 0.60 + 0.01 * style; 0.95 = roof, 0.8 = walls of tiles before 11-09),
//          Tex (baseColorTexture * factor), TexObj (the same texture as an object: roof sharpening / atlas size),
//          N (vertex normal, world), V (camera vector, world, surface -> eye), P (camera-relative world position, cm),
//          L (direction to the sun, SkyAtmosphereLightDirection), A (ArtFix: 1 = 11-10 art pass wall paint, 0 = before),
//          RP (RoofPhoto: 0 = procedural roofs with the photo as a low-frequency tint (round 2 default), 1 = the photo)
// Outputs: return = base colour; Rough, Metal, Spec, NormalWS (world space: the material has tangent space normals off)
// Styles: 0 plain, 1 house, 2 apartment (balcony glazing + railing, stair cores, AC louvres / units, gable dong number),
//         3 shopfront (signs), 4 punched windows (half stone clad), 5 factory, 6 office curtain wall, 7 glass tower,
//         8 ribbon windows, 9 rooftop prop (water tank FRP / steel, lift machine room, laundry), 10 villa (빌라, brick / tile,
//         small balconies), 11 pilotis / lobby ground floor
// Depth, all analytic per pixel (no parallax loop): every opening is a box recess of depth dR behind the wall plane.
// The view ray decides glass vs reveal (jamb / sill / head): reveals get their own world normal (lit correctly by the
// engine) and a sun shadow test (ray from the hit point back to the wall plane toward the sun: blocked = in shadow).
// Behind the glass: interior mapping (J. van Dongen, "Interior Mapping", CGI 2008) - a box room per bay x floor.

Rough = saturate(R); Metal = 0.0; Spec = 0.5; NormalWS = N;
float a255 = round(VC.a * 255.0);
float3 Nn = normalize(N);
float3 up = float3(0, 0, 1);
#define HSH(x) frac(sin((x) * 12.9898 + 4.1414) * 43758.5453)
#define PULSE(x, a, b, w) saturate((min((x) + (w) * 0.5, (b)) - max((x) - (w) * 0.5, (a))) / max((w), 1e-4))
#define INSIDE(p, W) (step((W).x, (p).x) * step((p).x, (W).y) * step((W).z, (p).y) * step((p).y, (W).w))

// ================================ roofs: the photo, sharpened + procedural grain at render time ===========================
// (nothing stored: V-World terms forbid modified copies, so the tile keeps the plain photo cut and this only changes pixels)
if (R > 0.9)
{
    float tw = 1.0, th = 1.0;
    TexObj.GetDimensions(tw, th);
    float2 ts = float2(1.0 / tw, 1.0 / th);
    float2 tpp = max(abs(ddx(UV)) + abs(ddy(UV)), 1e-7) * float2(tw, th);       // atlas texels per pixel
    float mag = saturate(1.6 - max(tpp.x, tpp.y));                                // 1 = texels bigger than pixels (low, close)
    // value noise in atlas texels (~0.5 m): grain (0.25 m), stains (1.5 m), patches (6 m); fades out when minified
    float2 ap = UV * float2(tw, th);
    float n1, n2, n3;
    {
        float2 q = ap * 2.0; float2 i = floor(q); float2 fq = frac(q); fq = fq * fq * (3.0 - 2.0 * fq);
        n1 = lerp(lerp(HSH(dot(i, float2(1, 57))), HSH(dot(i + float2(1, 0), float2(1, 57))), fq.x),
                  lerp(HSH(dot(i + float2(0, 1), float2(1, 57))), HSH(dot(i + float2(1, 1), float2(1, 57))), fq.x), fq.y);
        q = ap * 0.33; i = floor(q); fq = frac(q); fq = fq * fq * (3.0 - 2.0 * fq);
        n2 = lerp(lerp(HSH(dot(i, float2(1, 57)) + 3.0), HSH(dot(i + float2(1, 0), float2(1, 57)) + 3.0), fq.x),
                  lerp(HSH(dot(i + float2(0, 1), float2(1, 57)) + 3.0), HSH(dot(i + float2(1, 1), float2(1, 57)) + 3.0), fq.x), fq.y);
        q = ap * 0.08; i = floor(q); fq = frac(q); fq = fq * fq * (3.0 - 2.0 * fq);
        n3 = lerp(lerp(HSH(dot(i, float2(1, 57)) + 7.0), HSH(dot(i + float2(1, 0), float2(1, 57)) + 7.0), fq.x),
                  lerp(HSH(dot(i + float2(0, 1), float2(1, 57)) + 7.0), HSH(dot(i + float2(1, 1), float2(1, 57)) + 7.0), fq.x), fq.y);
    }
    float dg = saturate(1.4 - 0.35 * max(tpp.x, tpp.y));
    float ra = round(VC.a * 255.0);
    if (RP > 0.5 || ra >= 254.5)                                                  // photo roof (old tiles / GYROSIM_BLDG_ROOF_PHOTO=1)
    {
        float3 c0 = Tex;
        float3 bl = 0.25 * (Texture2DSample(TexObj, TexObjSampler, UV + float2(ts.x, 0)).rgb + Texture2DSample(TexObj, TexObjSampler, UV - float2(ts.x, 0)).rgb
                          + Texture2DSample(TexObj, TexObjSampler, UV + float2(0, ts.y)).rgb + Texture2DSample(TexObj, TexObjSampler, UV - float2(0, ts.y)).rgb);
        float3 bl2 = 0.25 * (Texture2DSample(TexObj, TexObjSampler, UV + float2(2.5 * ts.x, 1.0 * ts.y)).rgb + Texture2DSample(TexObj, TexObjSampler, UV - float2(2.5 * ts.x, 1.0 * ts.y)).rgb
                           + Texture2DSample(TexObj, TexObjSampler, UV + float2(-1.0 * ts.x, 2.5 * ts.y)).rgb + Texture2DSample(TexObj, TexObjSampler, UV - float2(-1.0 * ts.x, 2.5 * ts.y)).rgb);
        // round 3: unsharp at 1 texel (1.2) + local contrast at ~2.5 texels (0.5), clamped against halos
        float3 c = c0 + mag * (1.2 * (c0 - bl) + 0.5 * (bl - bl2));
        c = clamp(c, min(c0, bl) * 0.75, max(c0, bl) * 1.25 + 0.02);
        float green = saturate((c.g - max(c.r, c.b)) * 10.0);                     // green urethane waterproofing paint
        c *= 1.0 + dg * (0.16 * (n1 - 0.5) * (1.0 - 0.4 * green) + 0.10 * (n2 - 0.5)) + 0.06 * (n3 - 0.5);
        Rough = lerp(0.9, 0.55, green) + 0.08 * (n2 - 0.5);
        Spec = 0.4;
        NormalWS = normalize(Nn + float3(n1 - n2, n2 - n3, 0.0) * 0.06 * dg * mag);
        return c * VC.rgb;
    }
    // round 2 (11-10): procedural roof by default. The ortho photo of a roof is smeared (building lean: walls, cars and the
    // neighbours land on it), so it is only a low-frequency tint (mip ~4 m) here; the surface is drawn: green urethane paint
    // (per building flag in the vertex alpha: 128 + 64 x green + seed) or grey concrete with stains, joints and patches.
    float rs = fmod(ra, 64.0);
    bool gpaint = ra >= 191.5;
    float3 low = Texture2DSampleLevel(TexObj, TexObjSampler, UV, 3.0).rgb;
    float lowL = dot(low, float3(0.3, 0.59, 0.11));
    float3 base;
    if (gpaint)
    {
        // round 3: faded urethane greens (sRGB ~ (0.42, 0.53, 0.48) .. (0.48, 0.56, 0.54): grey-teal, low chroma), patchy re-coats
        float3 gp[4] = { float3(0.16, 0.23, 0.20), float3(0.19, 0.25, 0.23), float3(0.14, 0.20, 0.18), float3(0.20, 0.26, 0.21) };
        base = gp[(int)fmod(rs, 4.0)];
        float2 rc = floor(ap * (0.04 + 0.02 * frac(rs * 0.29)) + rs);
        float recoat = step(0.55, HSH(dot(rc, float2(1, 57)) + rs * 3.1));
        base = lerp(base, gp[(int)fmod(rs + 1.0, 4.0)] * 1.08, recoat * 0.8);
        float worn = smoothstep(0.55 + 0.2 * frac(rs * 0.37), 0.85, n2 * 0.5 + n3 * 0.5);   // worn patches, amount per building
        base = lerp(base, float3(0.32, 0.31, 0.29), worn * (0.3 + 0.4 * frac(rs * 0.61)));
        Rough = lerp(0.5, 0.85, worn);
    }
    else
    {
        float3 cp[3] = { float3(0.30, 0.29, 0.27), float3(0.24, 0.24, 0.24), float3(0.34, 0.32, 0.29) };
        base = cp[(int)fmod(rs, 3.0)];
        Rough = 0.9;
    }
    // photo as a low-frequency tint only: relative brightness and a little of its hue (no detail)
    float3 tintP = low / max(lowL, 0.02);
    base *= lerp(1.0.xxx, clamp(tintP, 0.6, 1.5), 0.45) * clamp(lerp(1.0, lowL / 0.35, 0.45), 0.7, 1.3);
    // stains / puddle marks / grain, expansion joints (~6 m), patch repairs
    float st = smoothstep(0.6, 0.9, n2) * 0.15 + smoothstep(0.65, 0.95, n3) * 0.12;
    base *= 1.0 - st;
    base *= 1.0 + dg * 0.10 * (n1 - 0.5);
    float2 jq = ap * 0.08 + rs * 0.37;                                            // ~1 joint per 12 atlas texels
    float2 jfw = max(abs(ddx(jq)) + abs(ddy(jq)), 1e-5);
    float joint = max(PULSE(frac(jq.x), 0.0, 0.02, jfw.x), PULSE(frac(jq.y), 0.0, 0.02, jfw.y)) * dg * (gpaint ? 0.5 : 1.0);
    base *= 1.0 - 0.25 * joint;
    float patchR = step(0.82, HSH(dot(floor(ap * 0.12), float2(1, 57)) + rs)) * dg;
    base = lerp(base, base * (gpaint ? float3(1.15, 1.05, 1.1) : 1.18.xxx), patchR * 0.6);
    Rough += 0.05 * (n2 - 0.5);
    Spec = 0.4;
    NormalWS = normalize(Nn + float3(n1 - 0.5, n2 - 0.5, 0.0) * 0.04 * dg);
    return base * VC.rgb;
}
bool isNew = (R > 0.595) && (R < 0.795);
if (!isNew)
{
    return Tex * VC.rgb;                                    // tiles from before the facade styles
}
int style = (int)round((R - 0.60) * 100.0);

// ================================ rooftop props (metres UV) =============================================================
if (style == 9)
{
    float kind = floor((a255 - 128.0) / 16.0);
    float ps = fmod(a255 - 128.0, 16.0);
    float2 m = UV;
    float2 fwm = max(abs(ddx(m)) + abs(ddy(m)), 1e-4);
    bool topF = Nn.z > 0.5;
    float3 Tp = normalize(cross(up, Nn) + float3(1e-4, 0, 0));
    float3 c = VC.rgb;
    float nearP = 1.0 - saturate((max(fwm.x, fwm.y) - 0.15) / 0.3);
    if (kind == 0.0 || kind == 3.0)                         // panel water tank: 1 m FRP / steel panels, bolted ribs
    {
        float2 g = frac(m);
        float rib = max(PULSE(g.x, 0.0, 0.05, fwm.x), PULSE(g.y, 0.0, 0.05, fwm.y)) * nearP;
        c = lerp(dot(c, float3(0.3, 0.59, 0.11)).xxx, c, (kind == 0.0) ? 0.55 : 0.2) * 0.78;   // round 3: weathered, dull (not toy blue)
        c *= 1.0 - 0.3 * rib;
        float2 b = (g - 0.5) * nearP;
        NormalWS = topF ? Nn : normalize(Nn + Tp * b.x * 0.25 - up * b.y * 0.25);
        Rough = (kind == 3.0) ? 0.35 : 0.5; Metal = (kind == 3.0) ? 0.7 : 0.0; Spec = 0.5;
        c *= 0.92 + 0.16 * HSH(floor(m.x) * 3.1 + floor(m.y) * 7.7 + ps);
        if (!topF) c *= 1.0 - 0.35 * saturate(m.y * 0.6 - 0.2) * 0.4;           // grime toward the bottom
    }
    else if (kind == 4.0)                                   // 옥탑방: rooftop room, door + window, corrugated roof
    {
        Rough = 0.85;
        if (topF) { c = lerp(float3(0.30, 0.32, 0.34), float3(0.15, 0.30, 0.50), step(8.0, ps)); c *= 1.0 - 0.15 * PULSE(frac(m.x * 5.0), 0.0, 0.4, fwm.x * 5.0) * nearP; Metal = 0.3; }
        else
        {
            float door = PULSE(m.x, 0.6, 1.5, fwm.x) * PULSE(m.y, 0.25, 99.0, fwm.y) * nearP;
            float wnd = PULSE(frac(m.x / 5.8), 0.45, 0.72, fwm.x / 5.8) * PULSE(m.y, 0.5, 1.4, fwm.y) * nearP;
            c *= 1.0 - 0.15 * HSH(floor(m.x * 3.0) + ps) * saturate(1.0 - m.y * 0.6) * nearP;
            c = lerp(c, float3(0.20, 0.26, 0.30), door);
            c = lerp(c, float3(0.06, 0.08, 0.09), wnd * (1.0 - door));
            Rough = lerp(0.85, 0.2, wnd);
        }
    }
    else if (kind == 5.0)                                   // blue tarp, wrinkled, tyres / bricks holding it down
    {
        float wr_ = HSH(floor(m.x * 2.5) * 3.3 + floor(m.y * 2.5) * 7.1 + ps);
        c *= 0.8 + 0.35 * wr_ * nearP;
        float wt = step(0.88, HSH(floor(m.x * 1.2) + floor(m.y * 1.2) * 9.0 + ps)) * nearP;
        c = lerp(c, float3(0.04, 0.04, 0.04), wt);
        Rough = 0.55;
        NormalWS = normalize(Nn + float3(wr_ - 0.5, HSH(wr_ * 9.1) - 0.5, 0.0) * 0.4 * nearP);
    }
    else if (kind == 6.0)                                   // solar panels: dark blue cells, silver frames
    {
        float2 g = frac(m / float2(1.0, 1.65));
        float fr = max(PULSE(g.x, 0.0, 0.04, fwm.x), PULSE(g.y, 0.0, 0.03, fwm.y / 1.65)) * nearP;
        c = lerp(float3(0.02, 0.03, 0.08), float3(0.55, 0.56, 0.58), fr);
        Rough = lerp(0.15, 0.4, fr); Metal = lerp(0.3, 0.9, fr); Spec = 0.6;
    }
    else if (kind == 2.0)                                   // lift machine room / stair house: door, louvre, drip stains
    {
        Rough = 0.85;
        if (topF) { c *= 0.78; }
        else
        {
            float door = PULSE(m.x, 1.0, 1.9, fwm.x) * PULSE(m.y, 1.4, 99.0, fwm.y) * nearP;
            float louv = PULSE(m.x, 3.0, 4.2, fwm.x) * PULSE(m.y, 0.5, 1.2, fwm.y) * nearP;
            float slat = PULSE(frac(m.y * 10.0), 0.0, 0.45, fwm.y * 10.0);
            float drip = HSH(floor(m.x * 4.0) + ps) * saturate(1.0 - m.y * 0.5);
            c *= 1.0 - 0.18 * drip * nearP;
            c = lerp(c, float3(0.30, 0.32, 0.33), door);
            c = lerp(c, lerp(float3(0.42, 0.43, 0.44), float3(0.12, 0.12, 0.12), slat), louv);
            Metal = 0.4 * max(door, louv); Rough = lerp(0.85, 0.5, max(door, louv));
        }
    }
    else                                                    // laundry: clothes hanging from a rack, gaps between
    {
        float seg = floor(m.x / 0.45);
        float hs = HSH(seg * 1.7 + ps * 5.3);
        float len = 0.35 + 0.6 * HSH(seg * 3.3 + ps);
        float cloth = step(m.y, len) * step(0.12, frac(m.x / 0.45)) * step(0.28, hs);
        float3 pal[6] = { float3(0.80, 0.80, 0.78), float3(0.15, 0.22, 0.45), float3(0.60, 0.15, 0.12),
                          float3(0.75, 0.62, 0.35), float3(0.25, 0.25, 0.27), float3(0.55, 0.70, 0.80) };
        float3 cc = pal[(int)min(HSH(seg * 9.1 + ps) * 6.0, 5.0)];
        float bar = PULSE(m.y, 0.0, 0.05, fwm.y);
        c = lerp(float3(0.10, 0.10, 0.10), cc, cloth);    // gaps = shadowed rack / roof behind (opaque material)
        c = lerp(c, float3(0.55, 0.56, 0.57), max(bar, topF ? 1.0 : 0.0));
        Rough = 0.9;
    }
    return c;
}

float endw = (a255 >= 192.0) ? 1.0 : 0.0;
float seed = fmod(a255, 64.0);
float3 wall = VC.rgb * float3(1.05, 1.0, 0.92);             // warmer: the photo-derived tints read lavender under the blue sky light
// art pass 11-10 (A): per-building paint from a small palette of the colours seen on Busan apartment / office walls
// (white, cream, pale grey, beige, salmon, grey-blue), +-6 % brightness, a bit darker overall; the per-building tint stays the base.
if (A > 0.5)
{
    // round 2: 8 paints (white, cream, pale grey, beige, salmon, grey-blue, mid grey, warm tan), +-15 % brightness
    float3 pal[8] = { float3(1.00, 1.00, 1.00), float3(1.00, 0.96, 0.88), float3(0.90, 0.91, 0.92),
                      float3(0.96, 0.90, 0.80), float3(1.00, 0.86, 0.80), float3(0.86, 0.90, 0.96),
                      float3(0.74, 0.74, 0.74), float3(0.90, 0.78, 0.66) };
    float pk = frac(sin(seed * 3.731 + 1.7) * 43758.5453);
    float3 paint = pal[(int)min(pk * 8.0, 7.0)];
    float pb = 0.85 + 0.30 * frac(sin(seed * 9.17 + 4.3) * 24634.6345);
    wall = VC.rgb * float3(0.97, 0.98, 1.0) * lerp(1.0.xxx, paint, 0.6) * pb * 0.86;
}

#define H1(x) frac(sin((x) * 12.9898 + seed * 78.233) * 43758.5453)

// gable u (apartments): 8192 + 64 x bays of the edge + bays along it
float2 uvF = UV;
float nbE = 0.0;
if (endw > 0.5 && UV.x > 8000.0)
{
    nbE = floor((UV.x - 8192.0) / 64.0 + 1e-3);
    uvF.x = UV.x - 8192.0 - 64.0 * nbE;
}
float kb = 1.0;                                             // round 2: per-building bay width 0.8 .. 1.25 x (not on gables)
if (nbE == 0.0 && style != 9) { kb = 0.8 + 0.45 * frac(sin(seed * 5.77 + 0.3) * 31718.927); uvF.x *= kb; }
float2 cell = floor(uvF);
float2 f = frac(uvF);
f.y = 1.0 - f.y;                                            // y up inside a floor (0 = floor slab, 1 = ceiling)
float2 fw = max(abs(ddx(UV)) + abs(ddy(UV)), 1e-4) * float2(kb, 1.0);   // cells per pixel
float far = saturate((max(fw.x, fw.y) - 0.18) / 0.3);       // 0 near .. 1 = sub-pixel cells: use the average look
float nearD = 1.0 - far;
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
float railGlass = 0.0;                                      // 1 = glass balustrade (see-through tint), 0 = solid / frosted
float grille = 0.0;                                         // security bars on the glass (houses)
float openRoom = 0.0;                                       // pilotis: an open dark space, no glass
float core = 0.0;                                           // apartment stair core bay
float louvre = 0.0;                                         // AC louvre panel width at the left of the bay (cell units)
float acUnit = 0.0;                                         // AC outdoor unit hung in front of this bay
float stone = 0.0;                                          // stone cladding with panel joints
float brick = 0.0;
float tile = 0.0;                                           // small ceramic tiles (villas, small offices)
float conc = 0.0;                                           // exposed / stained concrete with formwork seams
float awning = 0.0;
float podium = 0.0;
float spand = 0.0;                                          // coloured metal spandrel panels between window bands
float vsign = 0.0;                                          // vertical sign column (commercial blocks)
float cbay = 0.0;                                           // coloured bay panel (low / mid-rise accents)
float3 tints[6] = { float3(0.36, 0.50, 0.56), float3(0.44, 0.52, 0.60), float3(0.42, 0.36, 0.28),
                    float3(0.34, 0.38, 0.42), float3(0.32, 0.46, 0.40), float3(0.26, 0.36, 0.52) };
float3 accents[6] = { float3(0.05, 0.16, 0.45), float3(0.02, 0.30, 0.30), float3(0.40, 0.08, 0.05),
                      float3(0.08, 0.30, 0.10), float3(0.03, 0.06, 0.20), float3(0.60, 0.22, 0.03) };
float3 gtint = tints[(int)fmod(seed, 6.0)];
float3 acc = accents[(int)fmod(floor(seed / 6.0), 6.0)];
float3 accC = (A > 0.5) ? lerp(dot(acc, float3(0.3, 0.59, 0.11)).xxx, acc, 0.6) : acc;   // muted brand-free colours
float bayM = 300.0, floorM = 290.0;
float older = (fmod(seed, 3.0) < 1.0) ? 1.0 : 0.0;          // a third of the blocks: older type (AC units on the rails)

if (style == 1 || style == 10)                              // house / villa
{
    float vv = fmod(seed, 20.0);
    brick = (vv < 9.0) ? 1.0 : 0.0;                          // round 3: red brick 45 %, tile 35 % (villas) / 30 % (houses), paint
    tile = (brick < 0.5 && vv < ((style == 10) ? 16.0 : 15.0)) ? 1.0 : 0.0;
    if (style == 1) { win = float4(0.27, 0.73, 0.30, 0.76); mull = 1.0; bayM = 360.0; dR = 18.0; grille = (bayH < 0.5) ? 1.0 : 0.0; }
    else
    {
        bayM = 300.0; dR = 22.0; mull = 2.0;
        win = (fmod(cell.x, 2.0) < 1.0) ? float4(0.12, 0.88, 0.22, 0.80) : float4(0.30, 0.70, 0.42, 0.78);
        grille = (fmod(cell.x, 2.0) >= 1.0 && bayH < 0.6) ? 1.0 : 0.0;
        rail = (fmod(cell.x, 2.0) < 1.0) ? 0.30 : 0.0;
    }
    acUnit = (bayH2 < 0.18) ? 1.0 : 0.0;
}
else if (style == 2)
{
    bayM = 300.0; dR = 45.0;                                 // enclosed balcony: glazing set back from the slab edge
    win = float4(0.04, 0.96, 0.13, 0.90); mull = 2.0;
    rail = (fmod(seed, 3.0) < 2.0) ? 0.40 : 0.30;            // railing panel on the lower glass
    railGlass = (fmod(floor(seed / 3.0), 2.0) < 1.0) ? 1.0 : 0.0;
    float K = 4.0 + fmod(floor(seed / 7.0), 3.0);            // a stair / lift core every 4-6 bays (계단실형)
    core = (endw < 0.5 && fmod(cell.x + floor(seed / 2.0), K) == 0.0) ? 1.0 : 0.0;
    if (core > 0.5) { win = float4(0.36, 0.64, 0.50, 0.92); rail = 0.0; dR = 15.0; mull = 1.0; }
    else if (older < 0.5 && bayH2 < 0.35) { louvre = 0.24; win.x = 0.30; }   // AC louvre room beside the glazing
    acUnit = (older > 0.5 && core < 0.5 && bayH2 < 0.30) ? 1.0 : 0.0;
    if (endw > 0.5)                                          // gable wall: a column of small windows near each end, else plain
    {
        bool edgeBay = (cell.x < 1.0) || (cell.x >= nbE - 1.0);
        win = (edgeBay && nbE >= 3.0) ? float4(0.30, 0.70, 0.35, 0.72) : float4(0, 0, 0, 0);
        rail = 0.0; dR = 18.0; louvre = 0.0; acUnit = 0.0;
    }
    // gable colour band: top 3 floors, outer bays only (the dong number sits on the plain wall between)
    accent = (endw > 0.5 && cell.y < 3.0 && fmod(seed, 3.0) < 1.0 && (cell.x < 1.0 || cell.x >= nbE - 1.0)) ? 1.0 : 0.0;
    accent = max(accent, (cell.y < 1.5 && fmod(seed, 2.0) < 1.0) ? 0.8 : 0.0);
}
else if (style == 3)     { win = float4(0.03, 0.97, 0.05, 0.70); mull = 2.0; bayM = 400.0; floorM = 360.0; wallRough = 0.6; dR = 25.0;
                           awning = (bayH2 < 0.35) ? 1.0 : 0.0; }
else if (style == 12)                                        // 근생 podium floors 2..4: windows half hidden by sign boards
{
    win = float4(0.10, 0.90, 0.25, 0.80); mull = 2.0; bayM = 400.0; floorM = 340.0; dR = 20.0; podium = 1.0;
}
else if (style == 4)
{
    win = float4(0.08, 0.44, 0.30, 0.76); win2 = float4(0.56, 0.92, 0.30, 0.76); bayM = 320.0; floorM = 340.0; dR = 22.0;
    float v4 = fmod(seed, 6.0);                              // stone / stained concrete / tile / brick / spandrel / paint
    stone = (v4 < 1.0) ? 1.0 : 0.0; conc = (v4 == 1.0) ? 1.0 : 0.0; tile = (v4 == 2.0) ? 1.0 : 0.0; brick = (v4 == 3.0) ? 1.0 : 0.0;
    if (v4 == 4.0) { win = float4(0.03, 0.97, 0.32, 0.86); win2 = float4(0, 0, 0, 0); mull = 3.0; spand = 1.0; }   // office band glazing
    vsign = (fmod(floor(seed / 6.0), 3.0) < 1.0 && fmod(cell.x + seed, 4.0) == 0.0) ? 1.0 : 0.0;           // big vertical sign column
    acUnit = (stone < 0.5 && bayH2 < 0.12) ? 1.0 : 0.0;
}
else if (style == 5)     { win = float4(0.06, 0.94, 0.78, 0.90); mull = 4.0; bayM = 600.0; floorM = 600.0; wallRough = 0.5; wallMetal = 0.35; dR = 8.0; }
else if (style == 6)
{
    // round 3: curtain glass as a dark dielectric (F0 0.08, Fresnel to the sky at grazing view) with a light metallic coat;
    // as a tinted metal (0.85) it reflected only ~30 % of the sky everywhere and read as flat cardboard at 300 m
    bayM = 320.0; floorM = 360.0; glassMetal = 0.85; glassRough = 0.02; tint = gtint * 0.8; wallMetal = 0.7; wallRough = 0.2;
    bool fins = fmod(seed, 2.0) < 1.0;                       // half of the office towers: deep vertical fins at each bay edge
    win = fins ? float4(0.035, 0.965, 0.16, 0.99) : float4(0.015, 0.985, 0.16, 0.985);
    mull = fins ? 1.0 : 2.0; dR = fins ? 60.0 : 10.0;
}
else if (style == 7)                                         // Marine City / Haeundae residential towers: light blue / silver glass
{
    win = float4(0.02, 0.98, 0.12, 0.93); mull = 2.0; bayM = 300.0; floorM = 300.0; glassMetal = 0.6; glassRough = 0.02; wallRough = 0.25; wallMetal = 0.5; dR = 15.0;
    gtint = (fmod(seed, 3.0) < 1.0) ? float3(0.44, 0.54, 0.62) : ((fmod(seed, 3.0) < 2.0) ? float3(0.38, 0.52, 0.60) : float3(0.50, 0.56, 0.60));
    tint = gtint * 1.2;
}
else if (style == 8)
{
    win = float4(0.0, 1.0, 0.36, 0.80); mull = 2.0; bayM = 320.0; floorM = 360.0; glassMetal = 0.25; tint = gtint * 0.7; dR = 25.0;
    stone = (fmod(seed, 4.0) < 1.0) ? 1.0 : 0.0; tile = (fmod(seed, 4.0) == 1.0) ? 1.0 : 0.0; conc = (fmod(seed, 4.0) == 2.0) ? 1.0 : 0.0;
}
else if (style == 11)                                        // ground floor of apartments / villas: pilotis or lobby
{
    bool pil = fmod(seed, 2.0) < 1.0 || bayH < 0.25;
    if (pil) { win = float4(0.07, 0.93, 0.0, 0.88); openRoom = 1.0; dR = 500.0; }
    else
    {
        stone = 1.0;
        win = (fmod(cell.x + seed, 5.0) == 2.0) ? float4(0.10, 0.90, 0.0, 0.80) : float4(0.30, 0.70, 0.35, 0.75);
        mull = 2.0; dR = 25.0;
    }
}
if ((style == 1 || style == 10 || style == 4 || style == 8) && fmod(floor(seed / 9.0), 3.0) < 1.0)
    cbay = (fmod(cell.x + floor(seed / 5.0), 3.0) == 0.0) ? 1.0 : 0.0;    // round 3: every 3rd bay a coloured panel band
if (style == 12) vsign = (fmod(cell.x + seed, 3.0) == 0.0) ? 1.0 : 0.0;
if (parapet > 0.5) { win = float4(0, 0, 0, 0); win2 = win; accent = 0.0; louvre = 0.0; acUnit = 0.0; core = 0.0; awning = 0.0; vsign = 0.0; cbay = 0.0; }
if (style == 1 || style == 4 || style == 8 || style == 10)  // per-building sill / head height (round 2)
{
    float jz = (frac(sin(seed * 2.17 + 0.9) * 9631.7) - 0.5) * 0.12, jw = (frac(sin(seed * 6.31 + 2.2) * 7351.3) - 0.5) * 0.10;
    win.z = (win.z > 0.0) ? win.z + jz : win.z; win.w = (win.w > 0.0) ? win.w + jw : win.w;
    win2.z = (win2.z > 0.0) ? win2.z + jz : win2.z; win2.w = (win2.w > 0.0) ? win2.w + jw : win2.w;
}
bayM /= kb;
float4 W = (win2.y > 0.0 && f.x > 0.5) ? win2 : win;

// --- tangent frame: T along +u (sign from screen derivatives: glTF -> Unreal flips handedness) -------------------------------
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
float transom = (style == 2 && core < 0.5) ? PULSE(pg.y, W.w - 0.17, W.w - 0.15, fw.y) : 0.0;   // fixed top light of the balcony sash
frame = max(frame, transom);
float3 frameCol = (style == 6 || style == 7) ? gtint * 0.5 : ((fmod(seed, 4.0) < 1.0) ? float3(0.36, 0.30, 0.25) : float3(0.75, 0.75, 0.73));
float railP = (rail > 0.0) ? step(pg.y, W.z + rail) : 0.0;                          // balcony balustrade panel
float3 railCol = (fmod(seed, 3.0) < 1.0) ? wall * 0.95 : float3(0.55, 0.62, 0.64);  // solid (wall colour) or frosted glass
railCol = (railGlass > 0.5) ? lerp(glass, float3(0.30, 0.42, 0.42), 0.35) : railCol; // clear glass balustrade: greenish edge tint
glass = lerp(glass, railCol, railP);
gRough = lerp(gRough, (railGlass > 0.5) ? 0.08 : 0.35, railP);
gMetal = lerp(gMetal, 0.0, railP);
float bars = (grille > 0.5) ? PULSE(frac(pg.x * 7.0), 0.0, 0.18, fw.x * 7.0) * nearD : 0.0;   // 방범창 bars
glass = lerp(glass, float3(0.18, 0.18, 0.19), bars);
glass = lerp(glass, frameCol, frame);
gRough = lerp(gRough, 0.4, max(frame, bars));
gMetal = lerp(gMetal, (style == 6 || style == 7) ? 0.6 : 0.2, frame);
gN = normalize(lerp(gN, Nn, max(max(frame, bars), railP * (1.0 - railGlass))));
float bar = (rail > 0.0) ? PULSE(pg.y, W.z + rail, W.z + rail + 0.025, fw.y) : 0.0;   // rail top bar (catches the sky)
glass = lerp(glass, float3(0.8, 0.8, 0.78), bar);
if (openRoom > 0.5)                                          // pilotis: open dark parking with a lit floor and a car or two
{
    float car = step(h.y, 0.30) * step(0.35, H1(cell.x * 2.3 + 1.1)) * step(0.15, h.x) * step(h.x, 0.85);
    float3 carC = lerp(float3(0.75, 0.75, 0.76), float3(0.10, 0.10, 0.12), step(0.5, H1(cell.x * 4.7)));
    glass = lerp(float3(0.07, 0.07, 0.075) * lerp(1.0, 0.5, h.z), carC * 0.45, car);
    gRough = 0.8; gMetal = 0.0; gN = Nn;
}
glass *= lerp(0.45, 1.0, lit);                               // head / jamb shadow on the glass and the room

// --- reveal (jamb / sill / head) ----------------------------------------------------------------------------------------------
float3 rev = wall * 0.9 * revAO * lerp(0.35, 1.0, lit);
if (style == 6 && dR > 30.0) rev = lerp(wall, gtint, 0.3) * 0.8 * revAO * lerp(0.35, 1.0, lit);   // aluminium fins

// --- wall finish: material, accents, slab bands, weathering, patching -----------------------------------------------------------
float3 w = wall;
float wr = wallRough;
float ST_SIGN = 0.0;                                         // podium sign board coverage (drawn over the windows too)
float3 SIGNC = float3(0, 0, 0);
if (brick > 0.5)                                             // red / brown brick, running bond (fades to its mean colour far)
{
    float3 bcs[3] = { float3(0.42, 0.20, 0.14), float3(0.48, 0.28, 0.20), float3(0.36, 0.22, 0.17) };
    float3 bc = bcs[(int)fmod(floor(seed / 5.0), 3.0)];
    float by = uvF.y * floorM / 7.5;                          // 7.5 cm courses (bays / floors in cm)
    float bx = uvF.x * bayM / 22.0 + 0.5 * fmod(floor(by), 2.0);
    float2 fwb = fw * float2(bayM / 22.0, floorM / 7.5);
    float mort = max(PULSE(frac(by), 0.0, 0.14, fwb.y), PULSE(frac(bx), 0.0, 0.05, fwb.x));
    float bfade = saturate(1.5 - max(fwb.x, fwb.y));
    float bv = H1(floor(bx) * 1.3 + floor(by) * 7.1);
    w = lerp(bc * (0.9 + 0.2 * (bv - 0.5) * bfade), float3(0.55, 0.53, 0.50), mort * bfade * 0.6 + 0.08 * (1.0 - bfade));
    w *= 0.9 + 0.2 * H1(17.0);                                // per-building brick batch
    w *= clamp(dot(VC.rgb, float3(0.3, 0.59, 0.11)) / 0.55, 0.35, 1.15);   // keeps the vertex colour's foot shadow
    wr = 0.9;
}
if (stone > 0.5)                                             // granite / stone panels with joints
{
    float3 scs[3] = { float3(0.60, 0.57, 0.54), float3(0.42, 0.42, 0.43), float3(0.68, 0.64, 0.58) };
    w = lerp(wall, scs[(int)fmod(floor(seed / 4.0), 3.0)] * clamp(dot(VC.rgb, float3(0.3, 0.59, 0.11)) / 0.55, 0.35, 1.15), 0.75);
    float jx = frac(uvF.x * 3.0), jy = frac(uvF.y * 3.0);
    float joint = max(PULSE(jx, 0.0, 0.025, fw.x * 3.0), PULSE(jy, 0.0, 0.025, fw.y * 3.0)) * nearD;
    w *= (1.0 - 0.18 * joint) * (0.95 + 0.1 * H1(floor(uvF.x * 3.0) * 2.1 + floor(uvF.y * 3.0) * 5.9));
    wr = 0.55;
}
float vcl = clamp(dot(VC.rgb, float3(0.3, 0.59, 0.11)) / 0.55, 0.35, 1.15);
if (tile > 0.5)                                              // ceramic tiles ~15 cm (beige / brown / white / grey-green)
{
    float3 tcs[4] = { float3(0.62, 0.52, 0.40), float3(0.40, 0.28, 0.20), float3(0.80, 0.78, 0.72), float3(0.48, 0.52, 0.47) };
    float3 tc = tcs[(int)fmod(floor(seed / 3.0), 4.0)];
    float2 tq = uvF * float2(bayM, floorM) / 15.0;
    float2 tfw = fw * float2(bayM, floorM) / 15.0;
    float tfade = saturate(1.5 - max(tfw.x, tfw.y));
    float tj = max(PULSE(frac(tq.x), 0.0, 0.08, tfw.x), PULSE(frac(tq.y), 0.0, 0.08, tfw.y));
    w = tc * vcl * (0.93 + 0.14 * H1(floor(tq.x) * 1.7 + floor(tq.y) * 3.3) * tfade) * (1.0 - 0.12 * tj * tfade);
    wr = 0.45;
}
if (conc > 0.5)                                              // exposed concrete: formwork panels (bay / 2 x floor / 2), tie holes, stains
{
    w = lerp(w, float3(0.36, 0.36, 0.35) * vcl, 0.7);
    float2 cq = uvF * 2.0;
    float seam = max(PULSE(frac(cq.x), 0.0, 0.02, fw.x * 2.0), PULSE(frac(cq.y), 0.0, 0.02, fw.y * 2.0)) * nearD;
    float2 hq = frac(cq * 3.0) - 0.5;
    float tie = (1.0 - smoothstep(0.04, 0.08, length(hq))) * saturate(1.5 - fw.x * 12.0);
    w *= (1.0 - 0.15 * seam) * (1.0 - 0.3 * tie) * (0.9 + 0.2 * H1(floor(cq.x) * 1.1 + floor(cq.y) * 2.3));
    wr = 0.9;
}
if (spand > 0.5)
{
    float3 spc[4] = { float3(0.20, 0.22, 0.24), float3(0.35, 0.33, 0.30), float3(0.10, 0.16, 0.22), float3(0.42, 0.40, 0.38) };
    w = spc[(int)fmod(floor(seed / 7.0), 4.0)] * vcl;
    wr = 0.35; wallMetal = 0.6;
}
if (cbay > 0.5)
{
    float3 cbc[5] = { float3(0.45, 0.16, 0.10), float3(0.10, 0.28, 0.30), float3(0.30, 0.32, 0.40), float3(0.55, 0.42, 0.20), float3(0.22, 0.30, 0.18) };
    w = lerp(w, cbc[(int)fmod(floor(seed / 3.0), 5.0)] * vcl, 0.85);
}
if (style == 6 || style == 7) w = lerp(wall, gtint * 0.9, 0.45);   // spandrel panels between the glass bands
if (core > 0.5) w = lerp(w, accC, 0.18);                            // stair core column: a slightly different colour
w = lerp(w, accC, saturate(accent) * (1.0 - open));
float slab = PULSE(f.y, 0.0, 0.05, fw.y) * nearD * (1.0 - core);
w *= 1.0 - 0.08 * slab;
float under = (style == 2 && endw < 0.5 && core < 0.5) ? nearD * PULSE(f.y, 0.92, 1.0, fw.y) : 0.0;   // underside of the slab above
w *= 1.0 - 0.25 * under;
float streak = nearD * step(W.x, f.x) * step(f.x, W.y) * saturate((W.z - f.y) / max(W.z, 1e-3)) * (0.5 + 0.5 * bayH);
w *= 1.0 - 0.12 * streak;
// round 2: dirt runs from the sill ends (two thin dark streaks fading down to the next head)
float sillRun = (PULSE(f.x, W.x - 0.01, W.x + 0.04, fw.x) + PULSE(f.x, W.y - 0.04, W.y + 0.01, fw.x)) * step(f.y, W.z) * saturate(f.y / max(W.z, 1e-3));
w *= 1.0 - (0.28 + 0.2 * conc) * sillRun * nearD * step(0.3, bayH2) * step(0.01, W.y - W.x);
float grime = H1(floor(uvF.x * 0.5) * 0.71 + 5.3);            // a few bays wide stains, stronger low on the band of each floor
w *= 1.0 - 0.06 * grime * (1.0 - f.y) * nearD;
w *= 0.96 + 0.08 * H1(cell.y * 0.37 + 9.1) * nearD;          // per-floor repaint
// rain streaks down from the roof line / parapet (strongest in the top floors, thin vertical runs)
float runs = H1(floor(uvF.x * 9.0) * 0.37 + 2.2);
float wet = (0.3 + 0.7 * fmod(seed * 0.618, 1.0)) * exp(-max(UV.y, 0.0) * 0.7) * smoothstep(0.55, 1.0, runs);
w *= 1.0 - 0.22 * wet * saturate(1.5 - fw.x * 9.0);
if (style == 3 || (style == 11 && stone < 0.5 && openRoom < 0.5))
{
    // shop signs: a board per bay (white / red / blue / yellow / green / dark), light glyph blocks, no brands
    float sb = PULSE(f.y, 0.70, 0.95, fw.y) * nearD;                  // sign board (taller: thin lines read as trim, review 11-10)
    float3 sp[6] = { float3(0.85, 0.85, 0.82), float3(0.62, 0.10, 0.08), float3(0.08, 0.20, 0.50),
                     float3(0.85, 0.65, 0.10), float3(0.10, 0.40, 0.20), float3(0.12, 0.12, 0.13) };
    float si = H1(cell.x + 1.3);
    float3 sc = sp[(int)min(si * 6.0, 5.0)];
    float gx = f.x * 9.0, gy = (f.y - 0.74) / 0.17;
    float glyph = step(0.12, frac(gx)) * step(frac(gx), 0.88) * step(0.0, gy) * step(gy, 1.0)
                * step(0.3, H1(floor(gx) * 3.7 + cell.x * 11.0)) * step(0.15, f.x) * step(f.x, 0.85);
    float3 gc = (dot(sc, 0.333.xxx) > 0.5) ? float3(0.10, 0.10, 0.12) : float3(0.95, 0.93, 0.85);
    sc = lerp(sc, gc, glyph * saturate(1.5 - fw.x * 9.0));
    w = lerp(w, sc, sb * step(0.25, bayH));
    wr = lerp(wr, 0.35, sb * step(0.25, bayH));
}
if (podium > 0.5)
{
    // sign boards over the podium windows (one per bay, most bays): coloured board, light glyph blocks, no brands
    float has = step(0.45, bayH) * step(0.3, H1(cell.y * 2.9 + 1.7));   // fewer boards, not on every floor
    float vert = step(0.8, bayH2);                           // a few tall vertical boards at the bay edge
    float sbx0 = vert > 0.5 ? 0.02 : 0.06, sbx1 = vert > 0.5 ? 0.22 : 0.94;
    float sby0 = vert > 0.5 ? 0.08 : 0.48, sby1 = 0.92;
    float sbm = PULSE(f.x, sbx0, sbx1, fw.x) * PULSE(f.y, sby0, sby1, fw.y) * has;
    float3 sp2[6] = { float3(0.85, 0.85, 0.82), float3(0.62, 0.10, 0.08), float3(0.08, 0.20, 0.50),
                      float3(0.85, 0.65, 0.10), float3(0.10, 0.40, 0.20), float3(0.55, 0.12, 0.40) };
    float3 scl = sp2[(int)min(H1(cell.x * 1.9 + cell.y * 7.3) * 6.0, 5.0)];
    float2 gq = float2((f.x - sbx0) / max(sbx1 - sbx0, 0.01), (f.y - sby0) / max(sby1 - sby0, 0.01));
    float2 gn = vert > 0.5 ? float2(1.0, 5.0) : float2(7.0, 1.0);
    float2 gc = gq * gn;
    float glyph = step(0.15, frac(gc.x)) * step(frac(gc.x), 0.85) * step(0.18, frac(gc.y)) * step(frac(gc.y), 0.82)
                * step(0.3, H1(floor(gc.x) * 3.7 + floor(gc.y) * 5.1 + cell.x * 11.0 + cell.y * 3.0));
    float3 gcol = (dot(scl, 0.333.xxx) > 0.5) ? float3(0.10, 0.10, 0.12) : float3(0.95, 0.93, 0.85);
    scl = lerp(dot(scl, 0.333.xxx).xxx, scl, 0.75);          // a bit less candy
    scl = lerp(scl, gcol, glyph * saturate(1.5 - fw.x * 7.0));
    ST_SIGN = sbm * nearD + sbm * far * 0.6;
    SIGNC = scl;
    w *= 0.85;
}
if (style == 3) w *= 0.72;                                   // darker ground floor (shopfront frames, dirt)
if (style == 5)
{
    float rib = frac(f.x * 12.0);
    w *= 1.0 - 0.12 * PULSE(rib, 0.0, 0.15, fw.x * 12.0) * nearD;
}
// AC louvre room (newer apartments): horizontal slats in a recessed panel at the left of the bay
if (louvre > 0.0)
{
    float lv = PULSE(f.x, 0.04, 0.04 + louvre, fw.x) * PULSE(f.y, W.z, W.w, fw.y);
    float sl = PULSE(frac(f.y * 22.0), 0.0, 0.5, fw.y * 22.0);
    w = lerp(w, lerp(float3(0.20, 0.21, 0.22), float3(0.62, 0.63, 0.62), sl) * lerp(0.5, 1.0, lit), lv * nearD);
    w = lerp(w, w * 0.8, lv * far);
}
if (parapet > 0.5) w *= 0.92;
// slab edge bevel: top of the band catches the sky, the bottom edge faces down
float3 wN = Nn;
float bev = nearD * (1.0 - core) * (PULSE(f.y, 0.045, 0.06, fw.y) - PULSE(f.y, 0.0, 0.012, fw.y));
wN = normalize(Nn + up * 0.5 * bev);

// --- dong number painted on apartment gables (generic 101..112, 5 x 7 bitmap digits, no brand / logo) -----------------
if (style == 2 && endw > 0.5 && nbE >= 2.0)
{
    static const uint FONT[70] = { 14, 17, 19, 21, 25, 17, 14,   4, 12, 4, 4, 4, 4, 14,   14, 17, 1, 2, 4, 8, 31,
                                   31, 2, 4, 2, 1, 17, 14,   2, 6, 10, 18, 31, 2, 2,   31, 16, 30, 1, 1, 17, 14,
                                   6, 8, 16, 30, 17, 17, 14,   31, 1, 2, 4, 8, 8, 8,   14, 17, 17, 14, 17, 17, 14,
                                   14, 17, 17, 15, 1, 2, 12 };
    float num = 101.0 + fmod(seed, 12.0);
    float gwM = nbE * bayM / 100.0;                              // gable width, m
    float Hm = min(6.5, 0.92 * gwM / (3.0 * 1.25 * 5.0 / 7.0));   // digit height, m
    float gW = Hm * 5.0 / 7.0;
    float xm = (uvF.x - nbE * 0.5) * bayM / 100.0 + 1.5 * 1.25 * gW;   // from the left edge of the number
    float ym = (UV.y - 0.5) * floorM / 100.0;                      // down from the top of the number
    float gi = floor(xm / (1.25 * gW));
    float gx = (xm - gi * 1.25 * gW) / gW * 5.0;
    float gy = ym / Hm * 7.0;
    float dgt = (gi == 0.0) ? 1.0 : ((gi == 1.0) ? floor((num - 100.0) / 10.0) : fmod(num, 10.0));
    float ink = 0.0;
    if (gi >= 0.0 && gi <= 2.0 && gx >= 0.0 && gx < 5.0 && gy >= 0.0 && gy < 7.0)
    {
        uint rowb = FONT[(int)dgt * 7 + (int)gy];
        ink = (float)((rowb >> (4 - (uint)gx)) & 1u);
    }
    float inBox = step(0.0, xm) * step(xm, 3.0 * 1.25 * gW) * step(0.0, ym) * step(ym, Hm);
    float ppc = gW / 5.0 / (bayM / 100.0) / fw.x;                  // screen pixels per bitmap cell
    ink = lerp(0.4 * inBox, ink, saturate(ppc - 0.5));             // far: the number's mean coverage
    float3 inkC = (fmod(seed, 4.0) < 2.0) ? float3(0.10, 0.13, 0.22) : lerp(accC, float3(0.15, 0.15, 0.17), 0.4);
    w = lerp(w, inkC, ink * (1.0 - open));
}

// --- combine --------------------------------------------------------------------------------------------------------------------
float3 insC = onGlass ? glass : rev;
float insR = onGlass ? gRough : 0.8;
float insM = onGlass ? gMetal : 0.0;
float3 insN = onGlass ? gN : nRev;
// far away: average of glass and reveal, flat normal
float3 avgIn = lerp(glass, rev, 0.25);
insC = lerp(insC, avgIn, far);
insN = normalize(lerp(insN, Nn, far));
insR = lerp(insR, lerp(gRough, 0.8, 0.25 * (1.0 - glassMetal)), far);   // round 2: far glass keeps its gloss (was matte where reveals won)
insM = lerp(insM, gMetal, far);
float m = lerp(open, area, far);
float3 col = lerp(w, insC, m);
Rough = lerp(wr, insR, m);
Metal = lerp(wallMetal, insM, m);
Spec = lerp(0.35, 0.5, m);   // round 3 tried glass F0 0.08 (dielectric): blind review preferred the round-2 metallic glass (2 of 2 glass views)
NormalWS = normalize(lerp(wN, insN, m));
if (ST_SIGN > 0.0)
{
    col = lerp(col, SIGNC, saturate(ST_SIGN));
    Rough = lerp(Rough, 0.35, saturate(ST_SIGN)); Metal = lerp(Metal, 0.0, saturate(ST_SIGN));
    NormalWS = normalize(lerp(NormalWS, Nn, saturate(ST_SIGN)));
}
if (vsign > 0.5)
{
    // tall vertical signboard on the bay edge: one store per floor (colour block + stacked glyphs), sticks out of the wall
    float vx = PULSE(f.x, 0.02, 0.30, fw.x);
    float3 vp[6] = { float3(0.80, 0.80, 0.76), float3(0.55, 0.08, 0.06), float3(0.06, 0.16, 0.42), float3(0.75, 0.55, 0.08),
                     float3(0.08, 0.32, 0.16), float3(0.12, 0.12, 0.13) };
    float3 vc = vp[(int)min(H1(cell.x * 2.1 + cell.y * 5.3 + 0.4) * 6.0, 5.0)];
    vc = lerp(dot(vc, 0.333.xxx).xxx, vc, 0.8);
    float gy2 = f.y * 4.0;
    float vgl = step(0.2, frac(gy2)) * step(frac(gy2), 0.8) * PULSE(f.x, 0.07, 0.25, fw.x) * step(0.25, H1(floor(gy2) + cell.y * 7.0 + cell.x));
    float3 vg = (dot(vc, 0.333.xxx) > 0.5) ? float3(0.10, 0.10, 0.12) : float3(0.95, 0.93, 0.85);
    vc = lerp(vc, vg, vgl * saturate(1.5 - fw.y * 4.0));
    float frameV = 1.0 - PULSE(f.y, 0.04, 0.96, fw.y);
    vc = lerp(vc, float3(0.25, 0.25, 0.26), frameV);
    col = lerp(col, vc, vx * (nearD + far * 0.5));
    Rough = lerp(Rough, 0.4, vx); Metal = lerp(Metal, 0.0, vx); NormalWS = normalize(lerp(NormalWS, Nn, vx));
}
if (awning > 0.5 && parapet < 0.5)                           // striped awning over the shop window, its shadow below
{
    float aw = PULSE(f.y, 0.58, 0.70, fw.y) * PULSE(f.x, 0.02, 0.98, fw.x);
    float3 ac2[4] = { float3(0.55, 0.08, 0.06), float3(0.06, 0.25, 0.12), float3(0.06, 0.15, 0.40), float3(0.55, 0.40, 0.06) };
    float3 awc = lerp(ac2[(int)min(H1(cell.x * 4.4) * 4.0, 3.0)], float3(0.80, 0.80, 0.76), step(0.5, frac(f.x * 8.0)) * nearD);
    float ash = PULSE(f.y, 0.44, 0.58, fw.y) * PULSE(f.x, 0.02, 0.98, fw.x) * (sunFront ? 1.0 : 0.6);
    col *= 1.0 - 0.45 * ash;
    col = lerp(col, awc, aw);
    Rough = lerp(Rough, 0.7, aw); Metal = lerp(Metal, 0.0, aw);
    NormalWS = normalize(lerp(NormalWS, normalize(Nn * 0.6 - up * 0.8), aw * nearD));
}
// AC outdoor unit hung in front of the bay (in front of everything: older apartments on the rail, houses / shops under a
// window): light grey box with a dark round fan grille, its shadow on the wall below
if (acUnit > 0.5 && parapet < 0.5)
{
    float ax0 = (style == 2) ? 0.08 : 0.58, ax1 = ax0 + 0.26;
    float ay0 = (style == 2) ? W.z + 0.02 : 0.06, ay1 = ay0 + 0.20;
    float box = PULSE(f.x, ax0, ax1, fw.x) * PULSE(f.y, ay0, ay1, fw.y);
    float2 fc = float2((f.x - (ax0 + 0.62 * (ax1 - ax0))) * bayM, (f.y - (ay0 + ay1) * 0.5) * floorM);
    float fan = 1.0 - smoothstep(0.75, 1.0, length(fc) / ((ay1 - ay0) * floorM * 0.36));
    float3 acC = lerp(float3(0.70, 0.70, 0.69), float3(0.38, 0.38, 0.39), fan * nearD);   // grille: low contrast (dark dots read as eyes)
    float shd = PULSE(f.x, ax0, ax1, fw.x) * PULSE(f.y, ay0 - 0.10, ay0, fw.y) * (sunFront ? 1.0 : 0.5);
    col *= 1.0 - 0.35 * shd * nearD;
    col = lerp(col, acC, box * nearD);
    Rough = lerp(Rough, 0.5, box * nearD); Metal = lerp(Metal, 0.0, box * nearD);
    NormalWS = normalize(lerp(NormalWS, Nn + up * 0.15 * (f.y - ay0) / (ay1 - ay0), box * nearD));
    col = lerp(col, col * 0.97 + 0.03, box * far * 0.3);
}
return col;
