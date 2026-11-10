// Foliage look for the 3D trees tileset (sim/veg_build.py: instanced icosahedron "blob" crowns + trunks, vertex colour
// only, no UVs). Body of the Custom node in /Game/Trees/M_GyroTree (Scripts/trees_material.py). Art pass 11-10: the
// smooth crowns read as plastic blobs up close; a real crown from the air is a cluster of leaf clumps with dark gaps
// between them and each clump lit on its own sunny side. Render-time only, no new geometry:
//   - 3D value noise in world space (metres) at ClumpM and ClumpM * 0.37: clumps (bright) vs gaps (dark, AO-like),
//   - the noise gradient bends the normal, so each clump gets its own lit / shaded side,
//   - both fade to the plain crown by screen footprint (no shimmer far away; far trees stay as before).
// Inputs:  VC (vertex colour rgb, linear), P (absolute world position, cm), N (vertex normal, world), Amt (0 = off),
//          ClumpM (m), GapDark (0..1), Bump (normal bend)
// Outputs: return = base colour; Rough, NormalWS (world space; the material has tangent space normals off)

float3 Nn = normalize(N);
Rough = 0.85;
NormalWS = Nn;
float3 base = VC.rgb;
if (Amt <= 0.0)
{
    return base;
}
float3 pm = P * 0.01;                                                         // metres
float foot = max(length(ddx(P)), length(ddy(P))) * 0.01;                      // m per pixel
#define TF_H(c) frac(sin(dot((c), float3(127.1, 311.7, 74.7))) * 43758.5453)
float n[2]; float3 g[2];
float sc[2] = { ClumpM, ClumpM * 0.37 };
[unroll] for (int o = 0; o < 2; o++)
{
    float3 q = pm / sc[o], i = floor(q), f = q - i, u = f * f * (3.0 - 2.0 * f), du = 6.0 * f * (1.0 - f);
    float a = TF_H(i), b = TF_H(i + float3(1, 0, 0)), c = TF_H(i + float3(0, 1, 0)), d = TF_H(i + float3(1, 1, 0));
    float e = TF_H(i + float3(0, 0, 1)), ff = TF_H(i + float3(1, 0, 1)), gg = TF_H(i + float3(0, 1, 1)), h = TF_H(i + float3(1, 1, 1));
    float k0 = a, k1 = b - a, k2 = c - a, k3 = e - a, k4 = a - b - c + d, k5 = a - c - e + gg, k6 = a - b - e + ff, k7 = -a + b + c - d + e - ff - gg + h;
    n[o] = k0 + k1 * u.x + k2 * u.y + k3 * u.z + k4 * u.x * u.y + k5 * u.y * u.z + k6 * u.z * u.x + k7 * u.x * u.y * u.z;
    g[o] = du * float3(k1 + k4 * u.y + k6 * u.z + k7 * u.y * u.z, k2 + k5 * u.z + k4 * u.x + k7 * u.z * u.x,
                       k3 + k6 * u.x + k5 * u.y + k7 * u.x * u.y) / sc[o];
}
#undef TF_H
float w0 = saturate(1.5 - foot / (sc[0] / 4.0)) * Amt;                        // octave visible while a clump is > ~4 px
float w1 = saturate(1.5 - foot / (sc[1] / 4.0)) * Amt;
float v = 0.5 + (n[0] - 0.5) * w0 + (n[1] - 0.5) * 0.6 * w1;                  // 0.5 = the plain crown
float gap = smoothstep(0.42, 0.18, v);                                        // deep gaps between clumps
float tip = smoothstep(0.55, 0.85, v);                                        // clump tops catch more light
base *= lerp(1.0, 1.0 - GapDark, gap) * (1.0 + 0.18 * tip);
base *= float3(1.0 + 0.06 * (n[1] - 0.5) * w1, 1.0, 1.0 - 0.08 * (n[0] - 0.5) * w0);   // slight yellow / blue-green shifts
float3 gr = (g[0] * w0 + g[1] * 0.6 * w1) * (sc[0] * 0.5);
gr -= Nn * dot(gr, Nn);                                                       // tangential part only
NormalWS = normalize(Nn - Bump * gr);
Rough = lerp(0.85, 0.95, gap);
return base;
