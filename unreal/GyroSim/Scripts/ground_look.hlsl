// V-World photo ground look (vworld mode): sea surface + photo colour match. Body of the Custom node in
// /Game/Materials/Ground/M_GyroGround (Scripts/ground_material.py pastes this file in, after Cesium's material layers).
// Inputs:  C (layer base colour = V-World photo, linear), Rg / Sp (layer roughness / specular), N (vertex normal, world),
//          P (absolute world position, cm; world frame X north, Y east, Z up, Z 0 = mean sea level at the origin),
//          Q (camera-relative world position, cm), T (time s), WaveTex (+ WaveTexSampler), parameters below.
// Outputs: return = base colour; Rough, Spec, NormalWS (world space: the material has tangent space normals off), Mask.
// Sea mask: the Copernicus DEM has the sea at exactly 0 m MSL (terrain_build.py; the EGM2008 geoid varies only
// 28.99..29.42 m over Busan), so the height above the sea - Z plus the curvature drop X^2/2M + Y^2/2N of the local
// tangent frame - picks the sea (and river surfaces at 0 m). Bright photo pixels (ships, piers, breakwaters) and grey /
// brown ones (rock islets the 30 m DEM flattened to 0 m, quays) and green ones (delta fields 1-3 m up) stay land: sea
// pixels are blue / teal (B > R, B >= ~0.8 G). The height band is wide (the 30 m DEM ramps the coast over ~1 cell).

float3 up = normalize(N);
float dist = length(Q) * 0.01;                                                    // m from the camera
float h = (P.z + P.x * P.x / (2.0 * CurvM) + P.y * P.y / (2.0 * CurvN)) * 0.01;   // m above the sea (approx.)
float lum = dot(C, float3(0.2126, 0.7152, 0.0722));
float mH = 1.0 - smoothstep(SeaH0, SeaH1, h);
float mC = 1.0 - smoothstep(GuardL0, GuardL1, lum);                               // bright = ship / pier / foam -> land
float mB = smoothstep(GuardB0, GuardB1, C.b - C.r)                                 // grey / brown = rock islet, quay -> land
         * smoothstep(0.70, 0.90, C.b / max(C.g, 1e-4));                           // green = low fields / parks -> land
float m = saturate(WaterOn * mH * mC * mB);
Mask = m;

// ---- land: photo colour match (orthophoto tiles are graded brighter / more saturated than the scene light) --------
float3 g = lerp(lum.xxx, C, LandSat);
g = LandMid * pow(max(g, 1e-5) / LandMid, LandContrast);
g *= LandGain * LandTint;

// ---- land micro-texture (11-10, from Scripts/ground_detail.hlsl part B): the 0.24 m photo texel turns to blur below
// ~300 m AGL. Faint luminance-only value noise (mean 1.0) at DetailL1 / DetailL2 m, finer than the photo texel, weighted by
// a land class read from the photo colour (vegetation full, grey ground / roads DetailGrey, bright roofs DetailBright),
// faded out with camera distance (DetailNear..DetailFar m) and per octave when a screen pixel gets too big for it (no
// shimmer). No new structure and the photo itself is not changed (V-World terms: no modified copies) - render-time only.
// Thresholds re-tuned for linear C (the numpy preview worked in sRGB). DetailAmp 0 = off (GYROSIM_GROUND_SHARP=0).
if (DetailAmp > 0.0)
{
    float2 wm = P.xy * 0.01;                                                           // metres
    float foot = max(length(ddx(P.xyz)), length(ddy(P.xyz))) * 0.01;                   // m per screen pixel
    float mx = max(C.r, max(C.g, C.b)), mn = min(C.r, min(C.g, C.b));
    float veg = saturate((C.g - max(C.r, C.b)) * 24.0) * saturate((mx - mn) / max(mx, 1e-4) * 4.0);
    float bright = saturate((lum - 0.25) * 8.0);
    float cls = DetailVeg * veg + DetailGrey * (1.0 - veg) * (1.0 - bright) + DetailBright * bright * (1.0 - veg);
    float dn = 0.0;
    float2 DL = float2(DetailL1, DetailL2), DW = float2(0.6, 0.4);
    [unroll] for (int o = 0; o < 2; o++) {
        float2 q = wm / DL[o], i = floor(q), fr = q - i, u = fr * fr * (3.0 - 2.0 * fr);
        uint2 ii = uint2(int2(i));
        #define GD_H(a) ((float)(((((a).x * 374761393u + (a).y * 668265263u) ^ (((a).x * 374761393u + (a).y * 668265263u) >> 13)) * 1274126177u) ^ (((((a).x * 374761393u + (a).y * 668265263u) ^ (((a).x * 374761393u + (a).y * 668265263u) >> 13)) * 1274126177u) >> 16)) * 2.3283064e-10)
        float v = lerp(lerp(GD_H(ii), GD_H(ii + uint2(1, 0)), u.x), lerp(GD_H(ii + uint2(0, 1)), GD_H(ii + uint2(1, 1)), u.x), u.y);
        #undef GD_H
        dn += DW[o] * saturate(1.0 - (foot / (0.5 * DL[o]) - 0.5)) * (v * 2.0 - 1.0);
    }
    float fadeD = 1.0 - saturate((dist - DetailNear) / max(DetailFar - DetailNear, 1.0));
    g *= 1.0 + DetailAmp * cls * fadeD * (1.0 - m) * dn;
}

// ---- forest canopy (trees v2, 11-10; CanopyAmp 0 = off, GYROSIM_TREES_V2=0): beyond the 3D trees (~2.6 km) the photo
// forest reads as flat green paint. Where the photo is dark vegetation, a crown-sized cellular pattern (jittered crowns
// CanopyM m apart): bright sunlit crown domes, dark gaps between them, and a dome normal so every crown has its own lit /
// shaded side - mountains far away look like textured forest. Faded per pixel footprint (crown >= ~3 px), render-time only.
float3 canN = up;
if (CanopyAmp > 0.0)
{
    float mxc = max(C.r, max(C.g, C.b)), mnc = min(C.r, min(C.g, C.b));
    float vegc = saturate((C.g - max(C.r, C.b)) * 30.0) * saturate((mxc - mnc) / max(mxc, 1e-4) * 4.0) * (1.0 - smoothstep(0.08, 0.16, lum));
    float footc = max(length(ddx(P.xyz)), length(ddy(P.xyz))) * 0.01;
    float wc = vegc * saturate(1.5 - footc / (CanopyM / 3.0)) * (1.0 - m) * CanopyAmp;
    if (wc > 0.001)
    {
        float2 q = P.xy * 0.01 / CanopyM, ci = floor(q);
        float d1 = 9.0, d2 = 9.0; float2 off1 = float2(0.0, 0.0); float s1 = 0.5;
        [unroll] for (int yy = -1; yy <= 1; yy++)
        [unroll] for (int xx = -1; xx <= 1; xx++)
        {
            float2 cc = ci + float2(xx, yy);
            float2 hj = frac(sin(float2(dot(cc, float2(127.1, 311.7)), dot(cc, float2(269.5, 183.3)))) * 43758.5453);
            float2 dv = cc + 0.15 + 0.7 * hj - q;
            float dd = dot(dv, dv);
            if (dd < d1) { d2 = d1; d1 = dd; off1 = dv; s1 = hj.x; }
            else if (dd < d2) { d2 = dd; }
        }
        float edge = sqrt(d2) - sqrt(d1);                                   // 0 on the border between two crowns
        float gapc = 1.0 - smoothstep(0.02, 0.22, edge);
        float dome = saturate(1.0 - sqrt(d1) * 1.35);
        g *= lerp(1.0, (1.0 - CanopyDark * gapc) * (0.86 + 0.28 * s1) * (0.9 + 0.2 * dome), wc);
        float3 txc = normalize(cross(float3(0.0, 1.0, 0.0), up)), tyc = cross(up, txc);
        float3 nd = normalize(up - CanopyBump * (off1.x * txc + off1.y * tyc) * (1.0 - gapc));
        canN = normalize(lerp(up, nd, wc));
    }
}

// ---- sea: dark water body + sky reflection (Fresnel, from the engine's specular), wind waves -------------------------
// water leaving reflectance of coastal sea is only a few percent: the look is mostly the reflected sky (Specular)
float detail = clamp(lum / max(PhotoSeaLum, 1e-4), 0.55, 1.8);                  // keep the photo's own variation (wakes, swell)
float3 desat = lerp(lum.xxx, C, ShallowSat);
float3 body = lerp(DeepColor * detail, desat * ShallowGain, ShallowMix * saturate((lum - PhotoSeaLum) / max(PhotoSeaLum, 1e-4)));
float fade = saturate(dist / WaveFadeM);
// three octaves at unrelated scales / directions (no visible repeat), the small ones fade out with distance (they would
// alias into a grid); far away only the long swell octave and the growing roughness remain
float2 uv1 = P.xy / WaveScale + T * float2(0.013, 0.007);
float2 uv2 = float2(P.x * 0.8 - P.y * 0.6, P.x * 0.6 + P.y * 0.8) / (WaveScale * 0.37) + T * float2(-0.011, 0.017);
float2 uv3 = float2(P.x * 0.94 + P.y * 0.34, -P.x * 0.34 + P.y * 0.94) / (WaveScale * 7.3) + T * float2(0.004, -0.002);
float2 n1 = Texture2DSample(WaveTex, WaveTexSampler, uv1).xy * 2.0 - 1.0;
float2 n2 = Texture2DSample(WaveTex, WaveTexSampler, uv2).xy * 2.0 - 1.0;
float2 n3 = Texture2DSample(WaveTex, WaveTexSampler, uv3).xy * 2.0 - 1.0;
float near = 1.0 - fade;
float macroW = 1.0;
// ---- art pass 11-10 (SeaArt 1; GYROSIM_SEA_ART=0 -> 0 = the sea before): from 100-1000 m the one wave texture repeated
// every ~18 m / 7 m read as a regular waffle grid of the same ripples to the horizon. Real sea from the air: patches of
// rougher and calmer water (wind gusts / slicks, hundreds of m), no visible repeat. (1) a second, rotated / rescaled copy
// of each small octave blended in by a smooth large-scale noise (no repeat at the texture period), (2) wave strength
// modulated by a slower noise (SeaMacroM m, +-SeaMacroAmp), (3) the small octaves fade out by screen footprint (a pixel
// larger than ~1/8 of their wavelength only shows their tiling, not waves).
if (SeaArt > 0.5)
{
    float2 wm2 = P.xy * 0.01;
    #define SA_H(a) frac(sin(dot((a), float2(127.1, 311.7))) * 43758.5453)
    float2 mq = wm2 / SeaMacroM, mi = floor(mq), mf = mq - mi, mu = mf * mf * (3.0 - 2.0 * mf);
    float mv = lerp(lerp(SA_H(mi), SA_H(mi + float2(1, 0)), mu.x), lerp(SA_H(mi + float2(0, 1)), SA_H(mi + float2(1, 1)), mu.x), mu.y);
    float2 bq = wm2 / (WaveScale * 0.01 * 3.1), bi = floor(bq), bf = bq - bi, bu = bf * bf * (3.0 - 2.0 * bf);
    float bv = lerp(lerp(SA_H(bi), SA_H(bi + float2(1, 0)), bu.x), lerp(SA_H(bi + float2(0, 1)), SA_H(bi + float2(1, 1)), bu.x), bu.y);
    #undef SA_H
    float2 uv1b = float2(P.x * 0.79 + P.y * 0.61, -P.x * 0.61 + P.y * 0.79) / (WaveScale * 1.37) + T * float2(0.009, 0.012);
    float2 uv2b = float2(P.x * 0.26 - P.y * 0.97, P.x * 0.97 + P.y * 0.26) / (WaveScale * 0.53) + T * float2(0.014, -0.008);
    float2 n1b = Texture2DSample(WaveTex, WaveTexSampler, uv1b).xy * 2.0 - 1.0;
    float2 n2b = Texture2DSample(WaveTex, WaveTexSampler, uv2b).xy * 2.0 - 1.0;
    float bw = smoothstep(0.3, 0.7, bv);
    n1 = lerp(n1, n1b, bw) * 1.25;                          // the blend of two lowers the slope variance: keep it
    n2 = lerp(n2, n2b, 1.0 - bw) * 1.25;
    float footS = max(length(ddx(P.xyz)), length(ddy(P.xyz))) * 0.01;                    // m per pixel
    near *= saturate(1.5 - footS / (WaveScale * 0.01 / 8.0));                          // octave 1 (WaveScale)
    macroW = 1.0 + SeaMacroAmp * (mv * 2.0 - 1.0);
    n2 *= saturate(1.5 - footS / (WaveScale * 0.01 * 0.37 / 8.0));                     // octave 2, own footprint
}
float2 nxy = ((n1 * near * near + n2 * near * 0.7) * WaveStrength + n3 * WaveStrength * 0.5 * (1.0 - 0.5 * fade)) * macroW;
float3 tx = normalize(cross(float3(0.0, 1.0, 0.0), up));                          // ~ north on the sea plane
float3 ty = cross(up, tx);
float3 nw = normalize(nxy.x * tx + nxy.y * ty + up);
NormalWS = normalize(lerp(canN, nw, m));
// unresolved waves far away widen the sun glint (roughness grows with distance), F0 water = 0.02 -> Specular 0.25
Rough = lerp(Rg, lerp(WaterRough, WaterRoughFar, fade), m);
Spec = lerp(Sp, WaterSpec, m);
return lerp(g, body, m);
