// Trees v2 look (sim/veg_v2.py tiles): body of the pixel Custom node in /Game/Trees/M_GyroTree2 (Scripts/trees_material.py,
// build2). The prototypes are many small leaf clumps (jittered icosahedra) on a branch skeleton; the vertex colour carries
//   RGB = species tint, sRGB-encoded bytes (veg_v2.lin_to_srgb8: linear 8-bit bands in the dark greens),
//   A   = 64 x kind + ao (6 bits): kind 0 bark, 1 pine, 2 broadleaf, 3 shrub; ao = baked crown self-shadowing.
// Cesium copies the bytes unchanged (CesiumGltfComponent ColorVisitor), so A * 255 is the exact code.
// Shading model Two Sided Foliage: Subsurface colour = light through the leaves (backlit crowns glow a little).
// Inputs:  VC (rgb), VA (alpha), P (absolute world position, cm), N (vertex normal, world), PIR (PerInstanceRandom 0..1),
//          VarAmt (per-tree variation 0..1), Season (0 summer .. 1 autumn, broadleaf only), AoBase / AoAmb (how much of the
//          baked ao goes to the base colour / the AO pin), ClumpM (m), GapDark, Bump, SssAmt, Gain
// Outputs: return = base colour; Rough, NormalWS (world space), SSS (subsurface colour), AOut (ambient occlusion)

float a255 = round(VA * 255.0);
float kind = floor(a255 / 64.0 + 0.001);
float ao = fmod(a255, 64.0) / 63.0;
float3 tint = lerp(VC / 12.92, pow((max(VC, 0.0) + 0.055) / 1.055, 2.4), step(0.04045, VC));
float fol = kind > 0.5 ? 1.0 : 0.0;
float3 Nn = normalize(N);
NormalWS = Nn;
Rough = 0.88;
AOut = lerp(1.0, ao, AoAmb);
SSS = float3(0, 0, 0);
float r1 = PIR, r2 = frac(PIR * 7.31 + 0.137), r3 = frac(PIR * 13.7 + 0.71);
if (fol < 0.5)
{
    float3 bark = tint * (1.0 + 0.25 * VarAmt * (r1 - 0.5)) * lerp(1.0, ao, 0.7);
    return bark;
}
// ---- per-tree variation (value +-12 %, hue yellow <-> blue-green +-) and season ------------------------------------
float3 c = tint * Gain;
c *= 1.0 + VarAmt * 0.24 * (r1 - 0.5);
c *= float3(1.0 + VarAmt * 0.20 * (r2 - 0.5), 1.0, 1.0 - VarAmt * 0.26 * (r2 - 0.5));
if (Season > 0.0 && kind > 1.5)                                                // broadleaf / shrub: autumn colours
{
    float3 fall = lerp(float3(0.30, 0.10, 0.02), float3(0.42, 0.26, 0.03), r3) * dot(c, float3(0.3, 0.6, 0.1)) / 0.09;
    c = lerp(c, fall, saturate(Season * (0.6 + 0.6 * r2)));
}
// ---- leaf texture: two octaves of world-space value noise (clumps of leaves / needle tufts and the gaps between) -----
float3 pm = P * 0.01;
float foot = max(length(ddx(P)), length(ddy(P))) * 0.01;                      // m per pixel
#define TF_H(q) frac(sin(dot((q), float3(127.1, 311.7, 74.7))) * 43758.5453)
float n[2]; float3 g[2];
float sc[2] = { ClumpM, ClumpM * 0.41 };
[unroll] for (int o = 0; o < 2; o++)
{
    float3 q = pm / sc[o], i = floor(q), f = q - i, u = f * f * (3.0 - 2.0 * f), du = 6.0 * f * (1.0 - f);
    float a = TF_H(i), b = TF_H(i + float3(1, 0, 0)), cc = TF_H(i + float3(0, 1, 0)), d = TF_H(i + float3(1, 1, 0));
    float e = TF_H(i + float3(0, 0, 1)), ff = TF_H(i + float3(1, 0, 1)), gg = TF_H(i + float3(0, 1, 1)), h = TF_H(i + float3(1, 1, 1));
    float k0 = a, k1 = b - a, k2 = cc - a, k3 = e - a, k4 = a - b - cc + d, k5 = a - cc - e + gg, k6 = a - b - e + ff, k7 = -a + b + cc - d + e - ff - gg + h;
    n[o] = k0 + k1 * u.x + k2 * u.y + k3 * u.z + k4 * u.x * u.y + k5 * u.y * u.z + k6 * u.z * u.x + k7 * u.x * u.y * u.z;
    g[o] = du * float3(k1 + k4 * u.y + k6 * u.z + k7 * u.y * u.z, k2 + k5 * u.z + k4 * u.x + k7 * u.z * u.x,
                       k3 + k6 * u.x + k5 * u.y + k7 * u.x * u.y) / sc[o];
}
#undef TF_H
float w0 = saturate(1.5 - foot / (sc[0] / 4.0));
float w1 = saturate(1.5 - foot / (sc[1] / 4.0));
float v = 0.5 + (n[0] - 0.5) * w0 + (n[1] - 0.5) * 0.7 * w1;
float gap = smoothstep(0.42, 0.16, v);
float tip = smoothstep(0.58, 0.88, v);
c *= lerp(1.0, 1.0 - GapDark, gap) * (1.0 + 0.16 * tip);
float3 gr = (g[0] * w0 + g[1] * 0.7 * w1) * (sc[0] * 0.5);
gr -= Nn * dot(gr, Nn);
NormalWS = normalize(Nn - Bump * gr);
// ---- baked self-shadowing + translucency ----------------------------------------------------------------------------
c *= lerp(1.0, ao, AoBase);
SSS = c * float3(1.3, 1.6, 0.9) * SssAmt * (0.4 + 0.6 * ao);
Rough = lerp(0.80, 0.95, gap);
return c;
