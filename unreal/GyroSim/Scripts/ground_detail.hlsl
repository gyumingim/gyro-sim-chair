// Render-time ground sharpening for the V-World photo (vworld mode). NOT wired in yet: two Custom-node bodies meant for
// the ground material owner (Scripts/ground_material.py / ground_look.hlsl). The cached tiles are never changed or
// upscaled: the V-World open API terms forbid changing served content and using changed copies without prior consent
// (이용약관 13조 10항, 19조 4항, https://www.vworld.kr/v4po_prcint_a001.do). This only changes how the GPU filters and
// shades the photo on screen. Offline emulation + comparison: sim/ground_detail_preview.py (same math in numpy).
//
// ==== Part A: Catmull-Rom (bicubic) overlay sampling ==================================================================
// Replaces the bilinear Texture Sample of the overlay in a copy of Cesium's ML_CesiumRasterOverlay. Blends from bilinear
// (photo texel <= 1 screen pixel, i.e. when minified: keeps the mip chain / no extra cost visible) to Catmull-Rom when a
// texel covers >= SharpTexels screen pixels (low flight). Clamped to the 4 nearest texels' range: no ringing / halos.
// Inputs: Tex (+ TexSampler), UV (the layer's overlay UV), SharpTexels (1.2). Output: return = float4 colour.
// Cost: 5 bilinear fetches + 4 point fetches instead of 1 (only the overlay layer; estimate, not measured in engine).
/* ---- Part A body ----
float2 sz;  Tex.GetDimensions(sz.x, sz.y);
float2 px = UV * sz;
float2 dpx = max(abs(ddx(px)), abs(ddy(px)));
float mag = 1.0 / max(max(dpx.x, dpx.y), 1e-4);                          // screen pixels per texel
float k = saturate((mag - 1.0) / max(SharpTexels - 1.0, 1e-3));
float4 bil = Texture2DSample(Tex, TexSampler, UV);
if (k <= 0.0) return bil;
float2 x = px - 0.5, x1 = floor(x), f = x - x1;
float2 w0 = f * (-0.5 + f * (1.0 - 0.5 * f)), w1 = 1.0 + f * f * (-2.5 + 1.5 * f);
float2 w2 = f * (0.5 + f * (2.0 - 1.5 * f)),  w3 = f * f * (-0.5 + 0.5 * f);
float2 w12 = w1 + w2, t12 = (x1 + 0.5 + w2 / w12) / sz, t0 = (x1 - 0.5) / sz, t3 = (x1 + 2.5) / sz;
float4 c = Texture2DSampleLevel(Tex, TexSampler, float2(t12.x, t0.y), 0) * (w12.x * w0.y)
         + Texture2DSampleLevel(Tex, TexSampler, float2(t0.x, t12.y), 0) * (w0.x * w12.y)
         + Texture2DSampleLevel(Tex, TexSampler, t12, 0)                 * (w12.x * w12.y)
         + Texture2DSampleLevel(Tex, TexSampler, float2(t3.x, t12.y), 0) * (w3.x * w12.y)
         + Texture2DSampleLevel(Tex, TexSampler, float2(t12.x, t3.y), 0) * (w12.x * w3.y);
c /= (w12.x * w0.y + w0.x * w12.y + w12.x * w12.y + w3.x * w12.y + w12.x * w3.y);
float2 b = (x1 + 0.5) / sz, e = 1.0 / sz;
float4 q0 = Texture2DSampleLevel(Tex, TexSampler, b, 0), q1 = Texture2DSampleLevel(Tex, TexSampler, b + float2(e.x, 0), 0);
float4 q2 = Texture2DSampleLevel(Tex, TexSampler, b + float2(0, e.y), 0), q3 = Texture2DSampleLevel(Tex, TexSampler, b + e, 0);
c = clamp(c, min(min(q0, q1), min(q2, q3)), max(max(q0, q1), max(q2, q3)));
return lerp(bil, c, k);
---- end Part A ---- */
//
// ==== Part B: land micro-texture ======================================================================================
// Paste into ground_look.hlsl after the land colour match (g) and before the land / sea mix; it uses that file's names:
// C (photo colour), P (absolute world position cm), Q (camera-relative cm), m (sea mask 0..1), lum.
// Faint luminance-only value noise (mean 1.0) at 0.13 m / 0.37 m wavelengths - finer than the 0.24 m photo texel - with
// a per-pixel class weight (vegetation full, grey ground / roads DetailGrey, bright roofs DetailBright), faded out by
// camera distance (DetailNear..DetailFar m) and per octave when a screen pixel gets too big for it (no shimmer).
// Parameters (atmos_look.GROUND would hold them): DetailAmp 0.07, DetailL1 0.13, DetailL2 0.37, DetailVeg 1.0,
// DetailGrey 0.55, DetailBright 0.25, DetailNear 150, DetailFar 700. DetailAmp 0 = off.
/* ---- Part B body ----
{
    float2 wm = P.xy * 0.01;                                                           // metres
    float foot = max(length(ddx(P.xyz)), length(ddy(P.xyz))) * 0.01;                   // m per screen pixel
    float mx = max(C.r, max(C.g, C.b)), mn = min(C.r, min(C.g, C.b));
    float veg = saturate((C.g - max(C.r, C.b)) * 12.0) * saturate((mx - mn) / max(mx, 1e-4) * 4.0);
    float bright = saturate((lum - 0.55) * 4.0);   // NOTE: tuned on sRGB 0..1 in the preview; C is linear here -> retune
    float cls = DetailVeg * veg + DetailGrey * (1.0 - veg) * (1.0 - bright) + DetailBright * bright * (1.0 - veg);
    float n = 0.0;
    float2 L = float2(DetailL1, DetailL2), W = float2(0.6, 0.4);
    [unroll] for (int o = 0; o < 2; o++) {
        float2 q = wm / L[o], i = floor(q), fr = q - i, u = fr * fr * (3.0 - 2.0 * fr);
        uint2 ii = uint2(int2(i));
        #define GD_H(a) ((float)(((((a).x * 374761393u + (a).y * 668265263u) ^ (((a).x * 374761393u + (a).y * 668265263u) >> 13)) * 1274126177u) ^ (((((a).x * 374761393u + (a).y * 668265263u) ^ (((a).x * 374761393u + (a).y * 668265263u) >> 13)) * 1274126177u) >> 16)) * 2.3283064e-10)
        float v = lerp(lerp(GD_H(ii), GD_H(ii + uint2(1, 0)), u.x), lerp(GD_H(ii + uint2(0, 1)), GD_H(ii + uint2(1, 1)), u.x), u.y);
        #undef GD_H
        n += W[o] * saturate(1.0 - (foot / (0.5 * L[o]) - 0.5)) * (v * 2.0 - 1.0);
    }
    float fadeD = 1.0 - saturate((dist - DetailNear) / max(DetailFar - DetailNear, 1.0));
    g *= 1.0 + DetailAmp * cls * fadeD * (1.0 - m) * n;
}
---- end Part B ---- */
