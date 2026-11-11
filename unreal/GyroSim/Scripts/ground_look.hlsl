// V-World photo ground look (vworld mode): sea surface + photo colour match. Body of the Custom node in
// /Game/Materials/Ground/M_GyroGround (Scripts/ground_material.py pastes this file in, after Cesium's material layers).
// Inputs:  C (layer base colour = V-World photo, linear), Rg / Sp (layer roughness / specular), N (vertex normal, world),
//          P (absolute world position, cm; world frame X north, Y east, Z up, Z 0 = mean sea level at the origin),
//          Q (camera-relative world position, cm), T (time s), WaveTex (+ WaveTexSampler), parameters below.
//          CoastTex (+ CoastTexSampler), CoastU / CoastV (float3, MPC_GyroCoast) - coast v2 below.
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

// ---- coast v2 (11-10, CoastOn 1; GYROSIM_COAST_V2=0 -> 0 = the rule above): the OSM coastline as a signed distance field
// (T_GyroCoast from sim/coast_build.py --mask, equirectangular over the Busan box; world -> UV affine CoastU / CoastV in
// MPC_GyroCoast with quadratic rows CoastU2 / CoastV2, P in km; refitted by coast_look.py whenever the Cesium origin moves). R = coast distance (land +), G = bridge
// footprint distance (inside +), B = sea distance from the shore, A = shore class (0 natural, 0.5 beach, 1 man-made).
//  - the sea / land edge is the coastline itself, anti-aliased over one screen pixel (the 30 m DEM ramp no longer decides);
//  - photo guards (bright = ship / pier, grey = rock) only within CoastGuardM of the shore and never under a bridge mask:
//    the 광안대교 deck + shadow baked into the photo were 'bright -> land' = the white strip under the 3D bridge;
//  - the photo's own sea colour is used only near the shore (SeaPhotoNear..Far m): further out the procedural sea alone,
//    so the rectangular photo-tile seams on the open sea vanish; under the bridge masks (BridgeMaskOn) never;
//  - inland water (rivers, ponds) more than CoastInlandM from the coast keeps the old height / colour rule.
// Render-time only: the V-World photo is not modified or stored.
float photoW = 1.0, coastSteep = 0.0, coastCls = 0.0, coastSd = 1e4;
if (CoastOn > 0.5)
{
    float2 ck = P.xy * 1e-5;                                                       // km (quadratic fit: meridian convergence)
    float3 cq = float3(ck.x * ck.x, ck.x * ck.y, ck.y * ck.y);
    float2 cuv = float2(dot(CoastU.xy, ck) + CoastU.z + dot(CoastU2, cq), dot(CoastV.xy, ck) + CoastV.z + dot(CoastV2, cq));
    if (all(cuv > 0.0005) && all(cuv < 0.9995))
    {
        float4 cm = Texture2DSample(CoastTex, CoastTexSampler, cuv);
        float sd = (cm.r - 0.5) * 2.0 * CoastD;                                     // m, land +
        float bin = BridgeMaskOn * saturate(0.5 + (cm.g - 0.5) * 2.0 * BridgeD / 4.0);  // 1 inside a bridge mask (4 m soft edge)
        float far = cm.b * FarD;                                                    // m out from the shore (sea)
        float footC = max(max(length(ddx(P.xyz)), length(ddy(P.xyz))) * 0.01, 0.05);     // m per screen pixel
        float seaC = saturate(0.5 - sd / footC)                                     // crisp, 1 px anti-aliased edge
                   * (1.0 - smoothstep(2.0, 4.0, h));                               // islets OSM has no coastline for (the coast terrain keeps them)
        float guard = lerp(1.0, mC * mB, (1.0 - smoothstep(0.7 * CoastGuardM, CoastGuardM, far)) * (1.0 - bin));   // full near shore
                                                                                    // (moored boats / pontoons stay photo, no pale half-blend)
        float inland = saturate((sd - CoastInlandM) / 20.0) * mH * mC * mB;         // rivers / ponds well inside the OSM land
        m = saturate(WaterOn * max(seaC * guard, inland));
        photoW = (1.0 - smoothstep(SeaPhotoNear, SeaPhotoFar, far)) * (1.0 - bin);
        coastSd = sd;
        coastCls = cm.a;
        coastSteep = saturate((0.75 - up.z) * 4.0);                                  // > ~45 deg terrain faces (sea walls)
    }
    else if (CoastFaceOn > 0.5)
        photoW = 0.0;   // 11-11: outside the mask box the open sea is procedural too (the photo-coloured sea beyond the box edge
                        // met the procedural sea inside it in a straight dark / light boundary = the 'black bars' far out)
}
Mask = m;

// ---- land: photo colour match (orthophoto tiles are graded brighter / more saturated than the scene light) --------
float3 g = lerp(lum.xxx, C, LandSat);
g = LandMid * pow(max(g, 1e-5) / LandMid, LandContrast);
g *= LandGain * LandTint;

// ---- ground photo v2 (11-11, docs/ground-photo-busan.md; GYROSIM_GROUND_PHOTO_V2=0 -> identity 1/1/1/1): the V-World ortho
// photo is graded like a bright-midday survey print. Luminance gain x gamma (pivot 1: mids darker, white stays), saturation
// (luminance kept), and a soft shoulder above PhKnee (linear albedo; 1 = off) for blown concrete / roofs. Land photo term
// only (the sea body, sea walls and rock faces below use their own colours). Live values: MPC_GyroTune TuneD when TuneOn
// (tune_look.py) and TuneD was written (x > 0). Render-time only: the photo is not modified or stored.
float phR = 1.0;
{
    float tOnP = step(0.5, TuneA.x) * step(0.01, TuneD.x);
    float pGain = lerp(PhGain, TuneD.x, tOnP), pGam = lerp(PhGamma, TuneD.y, tOnP);
    float pSat = lerp(PhSat, TuneD.z, tOnP), pKnee = lerp(PhKnee, TuneD.w, tOnP);
    float l0 = max(dot(g, float3(0.2126, 0.7152, 0.0722)), 1e-5);
    float l1 = pGain * pow(l0, pGam);
    float k = min(pKnee, 0.999), ex = max(l1 - k, 0.0);
    l1 = min(l1, k) + ex / (1.0 + ex / max(1.0 - k, 1e-3));                   // shoulder: l = 1 above the knee -> k + (1 - k) / 2
    phR = l1 / l0;
    g = max(lerp(l0.xxx, g, pSat), 0.0) * phR;
}

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
    // round 2: (a) the photo ground between / under the 3D trees reads as lawn -> darker, greyer under the forest mask (all
    // distances); (b) far away, where single crowns are < 3 px, stand-sized light / dark patches (CanopyFarM m value noise)
    // keep the slopes rough instead of flat paint
    // round 5: the darkening fades out with camera distance (far slopes keep the photo brightness - review 11-11: v1 won at
    // 900-1500 m because far mountains were too dark)
    float vu = vegc * (1.0 - m) * CanopyAmp * (1.0 - smoothstep(CanopyFadeNear, CanopyFadeFar, dist));
    // bright, colourless photo rock (granite tops, rocky shore; exposure makes them read as snow / paper): down to a
    // weathered warm grey. Grey roads / roofs are darker or under the 3D buildings; sand is yellower (sat) and stays.
    float satc = (mxc - mnc) / max(mxc, 1e-4);
    float rk = smoothstep(0.28, 0.45, lum) * (1.0 - smoothstep(0.08, 0.18, satc)) * (1.0 - m) * CanopyAmp;
    g = lerp(g, lum * phR * RockGrey * float3(1.0, 0.96, 0.9), rk);
    g = lerp(g, lerp(dot(g, float3(0.2126, 0.7152, 0.0722)).xxx, g, 1.0 - CanopyDesat) * (1.0 - CanopyUnder), vu);
    {
        float2 fq = P.xy * 0.01 / CanopyFarM, fi = floor(fq), ff = fq - fi, fu = ff * ff * (3.0 - 2.0 * ff);
        #define CF_H(a) frac(sin(dot((a), float2(41.3, 289.1))) * 15731.743)
        float fv = lerp(lerp(CF_H(fi), CF_H(fi + float2(1, 0)), fu.x), lerp(CF_H(fi + float2(0, 1)), CF_H(fi + float2(1, 1)), fu.x), fu.y);
        #undef CF_H
        float wf = vu * saturate(footc / (CanopyM / 3.0) - 0.5) * saturate(1.5 - footc / (CanopyFarM / 3.0));
        g *= 1.0 + CanopyFarAmp * (fv * 2.0 - 1.0) * wf;
    }
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

// ---- photo relief (11-11, docs/photo-relief-busan.md; GYROSIM_PHOTO_DEPTH=0 -> RelF.w 0 = off): a height field made from
// the photo at Play (sim/photo_relief.py: Depth Anything V2 Small + compact-object bumps for cars / umbrellas, 0 on the 3D
// building footprints) in ReliefTex = RT_GyroRelief, 8 x 8 z18 tiles around the camera (Content/Python/relief_look.py,
// toroidal slots). R = height / 32 m (forest luminance detail folded in, 0 on 3D building footprints and unloaded slots).
// World -> window px (MPC_GyroTune Rel*): quadratic rows RelU / RelV (P in km); RelWin = (window corner mod RT, RT size). Normals from 4 taps,
// a 20-step height-field march toward the sun (RelSun) darkens the shadowed photo. Render-time only, nothing stored.
if (RelF.w > 0.5 && RelK.x > 0.0)
{
    float2 rk = P.xy * 1e-5;
    float3 rq = float3(rk.x * rk.x, rk.x * rk.y, rk.y * rk.y);
    float2 rp = float2(dot(RelU.xy, rk) + RelU.z + dot(RelU2.xyz, rq), dot(RelV.xy, rk) + RelV.z + dot(RelV2.xyz, rq));
    float footR = max(length(ddx(P.xyz)), length(ddy(P.xyz))) * 0.01;              // m per screen pixel
    float edgeR = min(min(rp.x, rp.y), min(RelWin.z - rp.x, RelWin.z - rp.y));      // px inside the window
    float wR = (1.0 - m) * saturate(1.5 - footR / 0.8) * (1.0 - smoothstep(RelF.x, RelF.y, dist)) * saturate(edgeR / 96.0);
    if (wR > 0.001)
    {
        float2 ruv = (rp + RelWin.xy) / RelWin.z;                                   // wraps (RT address wrap)
        float re = 1.0 / RelWin.z;
        float hs = 32.0 * RelK.x;
        #define RL_H(o) (Texture2DSampleLevel(ReliefTex, ReliefTexSampler, ruv + (o) * re, 0).r * hs)
        float h0 = RL_H(float2(0, 0));
        float dhx = 0.5 * (RL_H(float2(1, 0)) - RL_H(float2(-1, 0)));                // m per px
        float dhy = 0.5 * (RL_H(float2(0, 1)) - RL_H(float2(0, -1)));
        float gX = (dhx * RelU.x + dhy * RelV.x) * 1e-3, gY = (dhx * RelU.y + dhy * RelV.y) * 1e-3;     // m per m (world X, Y)
        canN = normalize(canN - RelK.y * wR * float3(gX, gY, 0.0));
        float3 sd = normalize(RelSun.xyz);
        if (RelK.z > 0.0 && sd.z > 0.02 && wR > 0.01)
        {
            float2 dp = float2(sd.x * RelU.x + sd.y * RelU.y, sd.x * RelV.x + sd.y * RelV.y);
            dp /= max(length(dp), 1e-6);
            float rise = RelF.z * sd.z / max(length(sd.xy), 1e-3);                  // m of height per px toward the sun
            float occ = 0.0;
            [loop] for (int si = 1; si <= 20; si++)
            {
                float st = si * 2.0;                                                // px (up to ~10 m)
                float hsn = RL_H(dp * st);
                occ = max(occ, saturate((hsn - (h0 + st * rise)) / 0.3));
            }
            g *= 1.0 - saturate(RelK.z) * occ * wR;
        }
        #undef RL_H
    }
}

// coast v2: steep man-made shore faces (the sea wall step of the coast-aware terrain, ~2 m vertex spacing) get a concrete
// face instead of the photo stretched down the step: weathered concrete, a dark wet band below WetBandM
if (CoastOn > 0.5)
{
    float near6 = (1.0 - saturate((coastSd - 6.0) / 4.0)) * (1.0 - m);
    float wall = coastSteep * saturate(coastCls * 2.0 - 1.0) * near6;
    float3 conc = lerp(SeaWallWet, SeaWallColor, smoothstep(WetBandM - 0.3, WetBandM + 0.3, h));
    g = lerp(g, conc * (0.9 + 0.2 * saturate(lum * 4.0)), wall);
    // 11-11 (CoastFaceOn): natural shore steps (태종대 / 이기대 cliffs: the coast terrain drops the sea next to the cliff top to
    // 0 m, so the photo's few shoreline pixels were stretched down a 10-40 m face = vertical streaks). Rock instead: the photo's
    // own mean tone, darkened and desaturated, with horizontal strata (height noise) and coarse blocks - no vertical streaks.
    if (CoastFaceOn > 0.5)
    {
        float rockW = coastSteep * (1.0 - saturate(coastCls * 2.0 - 1.0)) * (1.0 - saturate((coastSd - 12.0) / 6.0)) * (1.0 - m);
        float2 bq = P.xy * 0.01 / 3.7;
        float bh = frac(sin(dot(floor(bq), float2(127.1, 311.7))) * 43758.5453);
        float st = frac(sin(floor(h / 1.3 + bh * 3.0) * 78.233) * 43758.5453);
        float3 rock = RockColor * (0.75 + 0.35 * st) * (0.85 + 0.3 * bh) * lerp(1.0, SeaWallWet.g / max(RockColor.g, 1e-3), 1.0 - smoothstep(WetBandM - 0.3, WetBandM + 0.6, h));
        g = lerp(g, rock, rockW);
    }
}

// ---- sea: dark water body + sky reflection (Fresnel, from the engine's specular), wind waves -------------------------
// water leaving reflectance of coastal sea is only a few percent: the look is mostly the reflected sky (Specular)
float detail = lerp(1.0, clamp(lum / max(PhotoSeaLum, 1e-4), 0.55, 1.8), photoW);   // keep the photo's own variation (wakes, swell) near shore
float3 desat = lerp(lum.xxx, C, ShallowSat);
float3 body = lerp(DeepColor * detail, desat * ShallowGain, ShallowMix * photoW * saturate((lum - PhotoSeaLum) / max(PhotoSeaLum, 1e-4)));
float fade = saturate(dist / WaveFadeM);
// three octaves at unrelated scales / directions (no visible repeat), the small ones fade out with distance (they would
// alias into a grid); far away only the long swell octave and the growing roughness remain
float2 uv1 = P.xy / WaveScale + T * float2(0.013, 0.007);
float2 uv2 = float2(P.x * 0.8 - P.y * 0.6, P.x * 0.6 + P.y * 0.8) / (WaveScale * 0.37) + T * float2(-0.011, 0.017);
float2 uv3 = float2(P.x * 0.94 + P.y * 0.34, -P.x * 0.34 + P.y * 0.94) / (WaveScale * 7.3) + T * float2(0.004, -0.002);
float2 n1 = Texture2DSample(WaveTex, WaveTexSampler, uv1).xy * 2.0 - 1.0;
float2 n2 = Texture2DSample(WaveTex, WaveTexSampler, uv2).xy * 2.0 - 1.0;
float2 n3 = Texture2DSample(WaveTex, WaveTexSampler, uv3).xy * 2.0 - 1.0;
// far sea 11-11 (SeaFarArt 1; 0 = before): from altitude only the swell octave n3 (one texture, ~130 m period) is left and it
// read as a regular diamond grid. Domain-warp its UV by a smooth ~SeaWarpM m noise field and blend in a second copy at another
// scale / rotation by a third noise: no visible period. Two extra texture fetches + hash noise, only on the sea.
if (SeaFarArt > 0.5)
{
    float2 wq = P.xy * 0.01 / SeaWarpM;
    #define SF_H(a) frac(sin(dot((a), float2(127.1, 311.7))) * 43758.5453)
    #define SF_N(q) lerp(lerp(SF_H(floor(q)), SF_H(floor(q) + float2(1, 0)), smoothstep(0.0, 1.0, frac(q).x)), lerp(SF_H(floor(q) + float2(0, 1)), SF_H(floor(q) + float2(1, 1)), smoothstep(0.0, 1.0, frac(q).x)), smoothstep(0.0, 1.0, frac(q).y))
    float2 warp = float2(SF_N(wq), SF_N(wq + float2(17.3, 41.9))) * 2.0 - 1.0;
    float sel = smoothstep(0.3, 0.7, SF_N(wq * 0.61 + float2(5.1, 9.7)));
    #undef SF_N
    #undef SF_H
    float2 uv3w = uv3 + warp * SeaWarpAmp;
    float2 uv3b = float2(P.x * 0.42 - P.y * 0.91, P.x * 0.91 + P.y * 0.42) / (WaveScale * 4.9) + warp.yx * SeaWarpAmp + T * float2(-0.003, 0.004);
    float2 n3a = Texture2DSample(WaveTex, WaveTexSampler, uv3w).xy * 2.0 - 1.0;
    float2 n3b = Texture2DSample(WaveTex, WaveTexSampler, uv3b).xy * 2.0 - 1.0;
    n3 = lerp(n3a, n3b, sel) * 1.2;
}
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
float wRough = lerp(WaterRough, WaterRoughFar, fade), wSpec = WaterSpec;
// far sea 11-11: brighter sky reflection toward the horizon (photos: the far sea is pale sky-blue, not a dark block). At grazing
// view angles the water is smoother in effect (wave backs hidden) and its Fresnel reflectance climbs: roughness -> SeaRoughGraze,
// specular x (1 + SeaSpecGraze) by Schlick's (1 - N.V)^5 weight.
if (SeaFarArt > 0.5)
{
    float nv = saturate(dot(up, -normalize(Q)));
    float gz = pow(1.0 - nv, 5.0);
    wRough = lerp(wRough, SeaRoughGraze, saturate(gz * 3.0));
    wSpec = wSpec * (1.0 + SeaSpecGraze * saturate(gz * 3.0));
}
// ---- grounded day (11-11, GdOn 1; GYROSIM_GROUNDED_DAY=0 -> 0, docs/grounded-day-busan.md): building occlusion field
// T_GyroBldgAO (sim/bldg_ao_build.py: R = sky-view factor estimate of the ground from the GIS footprints / heights, B = the
// ortho photo's lean zone at the foot of towers), same grid / UV rows as the coast mask. Lumen sees no Cesium mesh, so the
// sky light reached street canyons unoccluded (real photos: canyon ground about as bright as open ground in the sun, much
// darker in the shade; sim: canyon ground brighter than open ground). The SVF goes into AmbientOcclusion (sky / indirect
// light only, the sun is untouched); GdCanyonAlb / GdLeanDark optionally into the albedo (art fix, not physical).
GdAOut = AOin;
if (GdOn > 0.5)
{
    float2 gk = P.xy * 1e-5;
    float3 gq = float3(gk.x * gk.x, gk.x * gk.y, gk.y * gk.y);
    float2 guv = float2(dot(CoastU.xy, gk) + CoastU.z + dot(CoastU2, gq), dot(CoastV.xy, gk) + CoastV.z + dot(CoastV2, gq));
    if (all(guv > 0.0005) && all(guv < 0.9995))
    {
        float4 bo = Texture2DSample(BldgAOTex, BldgAOTexSampler, guv);
        float land = 1.0 - m;
        float tOn = step(0.5, TuneA.x);                                             // live tuning (tune_look.py, MPC_GyroTune)
        float gAO = lerp(GdAO, TuneC.y, tOn), gCA = lerp(GdCanyonAlb, TuneC.z, tOn), gLD = lerp(GdLeanDark, TuneC.w, tOn);
        GdAOut = AOin * lerp(1.0, bo.r, saturate(gAO) * land);
        g *= lerp(1.0, lerp(1.0, bo.r, gCA) * (1.0 - gLD * bo.b), land);
        // building contact (11-12, BcOn; GYROSIM_BLDG_CONTACT, docs/research/building-grounding-study.md): photogrammetry scans
        // show the ground next to a building 1-1.7 stop darker than open ground (baked shade / dirt), the V-World photo shows
        // it as bright or brighter (the off-nadir photo paints the building's own roof / wall there). (a') the photo inside
        // the footprint + BcMargin m + the lean zone (B) x BcDark (pattern kept); (b) contact band 1 - BcK exp(-d / BcW).
        // A = signed distance to the footprint edge, (d + 8) x 8 (sim/bldg_ao_build.py).
        if (BcOn > 0.5)
        {
            float sd = bo.a * 255.0 / 8.0 - 8.0;
            float zone = max(saturate(BcMargin + 1.0 - sd), bo.b);
            float band = BcK * exp(-max(sd, 0.0) / max(BcW, 0.1));
            g *= lerp(1.0, lerp(1.0, BcDark, zone) * (1.0 - band), land);
        }
    }
}
Rough = lerp(Rg, wRough, m);
Spec = lerp(Sp, saturate(wSpec), m);
return lerp(g, body, m);
