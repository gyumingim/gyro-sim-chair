// Leaf-card trees (sim/veg_cards_tiles.py tiles): body of the pixel Custom node in /Game/Trees/M_GyroTreeCard
// (Scripts/trees_material.py build_card). Masked, Two Sided Foliage. Vertex colour = the veg_v2 encoding
//   RGB = species tint (sRGB bytes), A = 64 x kind + ao (kind 0 bark, 1 pine, 2 broadleaf, 3 shrub);
// UV (TEXCOORD_0) = leaf atlas uv for card leaves, -1 for bark / shrubs / rocks (drawn opaque, plain tint).
// Card normals are baked in the tiles (clump sphere + crown sphere + up bias + per-card noise, veg_cards.card); here only
// a little extra up bias (UpBias) so lower layers do not go black.
// Inputs:  VC, VA, N (vertex normal WS), PIR, V (camera vector WS), UV, TexRGB / TexA (atlas sample: linear rgb, alpha)
//          Gain, VarAmt, AoBase, AoAmb, SssAmt, RimAmt, TexLum (mean linear luminance of the opaque atlas texels),
//          TexChroma (how much of the atlas colour, 0 = luminance detail only), OakSat (broadleaf saturation), MipScale
//          (coverage-preserving mips: alpha x (1 + mip x MipScale) so far cards keep their coverage), UpBias,
//          IP (instance origin, absolute world cm), PosVar, TreeBri, TreeHue, Mottle, MottleM, MottleHue, Bleed (see below)
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
// 11-12 'mottle' (M_GyroTreeCardM; all 0 in M_GyroTreeCard = the look before): per-tree random also from a hash of the
// instance position IP (absolute world cm; PosVar 1), so the variation does not rely on PerInstanceRandom alone;
// TreeBri / TreeHue = extra per-tree brightness / yellow-blue swing (mean-preserving, linear); Mottle / MottleHue = a
// world value noise on the tree position (MottleM metre cells: neighbouring trees share a tone -> canopy mottling);
// Bleed = each pine / broadleaf tree leans a random 0..Bleed of the way to the other species' colour (ratio of the
// veg_v2 TINTs broad / pine = (2.06, 1.87, 0.88)), so the two species palettes overlap instead of two flat greens.
float2 iq = floor(IP.xy / 100.0);
float3 hp = frac(float3(iq.xyx) * 0.1031);
hp += dot(hp, hp.yzx + 33.33);
float hpos = frac((hp.x + hp.y) * hp.z);
float r0 = lerp(PIR, frac(PIR + hpos), step(0.5, PosVar));
float r1 = r0, r2 = frac(r0 * 7.31 + 0.137), r3 = frac(r0 * 13.7 + 0.71), r4 = frac(r0 * 23.1 + 0.29), r5 = frac(r0 * 41.3 + 0.53);
if (kind < 0.5)
{
    return tint * (1.0 + 0.25 * VarAmt * (r1 - 0.5)) * lerp(1.0, ao, 0.7);
}
float3 c = tint * Gain;
c *= 1.0 + VarAmt * 0.24 * (r1 - 0.5);
c *= float3(1.0 + VarAmt * 0.20 * (r2 - 0.5), 1.0, 1.0 - VarAmt * 0.26 * (r2 - 0.5));
{
    float2 g = IP.xy / max(MottleM * 100.0, 100.0);
    float2 gi = floor(g), gf = frac(g);
    gf = gf * gf * (3.0 - 2.0 * gf);
    float4 px = frac(float4(gi.x, gi.x + 1.0, gi.x, gi.x + 1.0) * 0.1031);    // the hash above per lattice corner
    float4 py = frac(float4(gi.y, gi.y, gi.y + 1.0, gi.y + 1.0) * 0.1031);
    float4 dd = px * (py + 33.33) + py * (px + 33.33) + px * (px + 33.33);
    float4 hx = frac((px + py + 2.0 * dd) * (px + dd));
    float vn = lerp(lerp(hx.x, hx.y, gf.x), lerp(hx.z, hx.w, gf.x), gf.y) * 2.0 - 1.0;       // -1..1, ~MottleM m blobs
    float hh = (r4 - 0.5) * 2.0;
    c *= 1.0 + TreeBri * (r3 - 0.5) * 2.0 + Mottle * vn;
    c *= float3(1.0 + 0.5 * (TreeHue * hh + MottleHue * vn), 1.0, 1.0 - 0.7 * (TreeHue * hh + MottleHue * vn));
    float3 toOak = float3(2.06, 1.87, 0.88);
    float3 ratio = (kind < 1.5) ? toOak : 1.0 / toOak;
    if (kind < 2.5)
        c *= lerp(float3(1, 1, 1), ratio, Bleed * r5);
}
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
SSS = c * SssAmt * (0.4 + 0.6 * ao);              // neutral (11-16; was x (1.2, 1.4, 0.9): crowns greener than the photo)
return c;
