// Leaf-card trees (sim/veg_cards_tiles.py tiles): body of the pixel Custom node in /Game/Trees/M_GyroTreeCard
// (Scripts/trees_material.py build_card). Masked, Two Sided Foliage. Vertex colour = the veg_v2 encoding
//   RGB = species tint (sRGB bytes), A = 64 x kind + ao (kind 0 bark, 1 pine, 2 broadleaf, 3 shrub);
// UV (TEXCOORD_0) = leaf atlas uv for card leaves, -1 for bark / shrubs / rocks (drawn opaque, plain tint).
// Card normals are baked in the tiles (clump sphere + crown sphere + up bias + per-card noise, veg_cards.card); here only
// a little extra up bias (UpBias) so lower layers do not go black.
// Inputs:  VC, VA, N (vertex normal WS), PIR, V (camera vector WS), UV, TexRGB / TexA (atlas sample: linear rgb, alpha)
//          Gain, VarAmt, AoBase, AoAmb, SssAmt, RimAmt, TexLum (mean linear luminance of the opaque atlas texels),
//          TexChroma (how much of the atlas colour, 0 = luminance detail only), OakSat (broadleaf saturation), MipScale
//          (coverage-preserving mips: alpha x (1 + mip x MipScale) so far cards keep their coverage), UpBias
// Outputs: return = base colour; Rough, NormalWS, SSS, AOut, Mask (opacity mask, clip 0.5)

float a255 = round(VA * 255.0);
float kind = floor(a255 / 64.0 + 0.001);
float ao = fmod(a255, 64.0) / 63.0;
float3 tint = lerp(VC / 12.92, pow((max(VC, 0.0) + 0.055) / 1.055, 2.4), step(0.04045, VC));
float3 Nn = normalize(N);
Mask = 1.0;
Rough = 0.88;
AOut = lerp(1.0, ao, AoAmb);
SSS = float3(0, 0, 0);
NormalWS = Nn;
float r1 = PIR, r2 = frac(PIR * 7.31 + 0.137);
if (kind < 0.5)
{
    return tint * (1.0 + 0.25 * VarAmt * (r1 - 0.5)) * lerp(1.0, ao, 0.7);
}
float3 c = tint * Gain;
c *= 1.0 + VarAmt * 0.24 * (r1 - 0.5);
c *= float3(1.0 + VarAmt * 0.20 * (r2 - 0.5), 1.0, 1.0 - VarAmt * 0.26 * (r2 - 0.5));
if (UV.x > -0.5)
{
    float2 st = UV * 1024.0;
    float2 dx = ddx(st), dy = ddy(st);
    float mip = 0.5 * log2(max(max(dot(dx, dx), dot(dy, dy)), 1e-8));
    Mask = TexA * (1.0 + max(mip, 0.0) * MipScale);
    float lum = dot(TexRGB, float3(0.2126, 0.7152, 0.0722));
    float3 det = lerp(lum.xxx, TexRGB, TexChroma) / TexLum;
    c *= det;
    NormalWS = normalize(Nn + float3(0, 0, UpBias));
}
float l = dot(c, float3(0.2126, 0.7152, 0.0722));
if (kind > 1.5)
    c = lerp(l.xxx, c, OakSat);
c *= lerp(1.0, ao, AoBase);
float rim = pow(1.0 - saturate(abs(dot(NormalWS, normalize(V)))), 3.0);
c *= 1.0 + RimAmt * rim * (0.5 + 0.5 * ao);
SSS = c * float3(1.2, 1.4, 0.9) * SssAmt * (0.4 + 0.6 * ao);
return c;
