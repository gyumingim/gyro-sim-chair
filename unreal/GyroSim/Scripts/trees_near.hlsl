// Near real-leaf trees (Content/Python/trees_near.py): body of the Custom node in /Game/Trees/M_GyroTreeNear
// (Scripts/trees_near_assets.py). Own code, no textures. Mesh vertex colour (sim/trees_near_build.py):
//   R = 1 foliage / 0 bark, G = per-leaf (tuft) random, B = crown occlusion (inner / low = dark), A = height in the tree.
// T = Tint parameter: the species' linear canopy tint (sim/veg_v2.TINT), one material instance per kind (trees_near.py).
// Inputs:  VC (float4), T (float3 tint), PIR (PerInstanceRandom), N (vertex normal, world), V (camera vector),
//          Gain (leaf albedo / canopy tint), VarAmt, OccAmt, SssAmt, BarkGain
// Outputs: return = base colour; Rough, SSS (subsurface colour), AOut (ambient occlusion)
float fol = VC.r > 0.5 ? 1.0 : 0.0;
float occ = VC.b;
float3 tint = (T.g > 0.0001) ? T.rgb : float3(0.045, 0.075, 0.040);
float r1 = PIR, r2 = frac(PIR * 7.31 + 0.137), lr = VC.g;
AOut = lerp(1.0, 0.35 + 0.65 * occ, OccAmt);
if (fol < 0.5)
{
    float3 bark = float3(0.115, 0.092, 0.075) * BarkGain * (0.85 + 0.3 * r1) * (0.55 + 0.45 * occ);
    bark = lerp(bark, bark * float3(1.35, 0.95, 0.75), saturate(VC.a * 1.6 - 0.5) * step(tint.b, tint.g * 0.7)); // pines: orange upper bark
    Rough = 0.9;
    SSS = float3(0, 0, 0);
    return bark;
}
float3 c = tint * Gain;
c *= 1.0 + VarAmt * 0.22 * (r1 - 0.5);                                         // per tree value
c *= float3(1.0 + VarAmt * 0.16 * (r2 - 0.5), 1.0, 1.0 - VarAmt * 0.2 * (r2 - 0.5));  // per tree hue
c *= 0.86 + 0.28 * lr;                                                           // per leaf / tuft
c *= float3(1.0 + 0.06 * (lr - 0.5), 1.0, 1.0 - 0.08 * (lr - 0.5));
c *= lerp(1.0, 0.45 + 0.55 * occ, OccAmt);                                       // inner / low leaves darker
Rough = 0.78 + 0.12 * lr;
SSS = c * float3(1.2, 1.5, 0.8) * SssAmt * (0.35 + 0.65 * occ);
return c;
