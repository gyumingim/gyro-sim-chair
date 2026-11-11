// Hemi-octahedral impostor (pixel stage), sim/impostor/pipeline.py bakes the atlases (G x G views of the upper hemisphere,
// orthographic frames of the bounding sphere; A = sRGB albedo + alpha, B = oct normal xy, depth over the sphere diameter, AO).
// The same maths as the software renderer there: the 4 nearest views (bilinear in the view grid), each re-projected through
// its own frame plane (ray from the camera through this pixel), blended by weight x alpha.
// Inputs: CamL, PixL = camera / this pixel in instance-local space (cm; sphere radius 100), TexA / TexB (+ samplers), G,
//         CrownZ, CrownR, SphAmt (crown-volume normal blend, see the end),
//         Far (1 = only the nearest view: far trees). Local space = Blender's axes with y mirrored (UE is left-handed).
// Outputs: return = albedo (linear); Alpha, NrmL (local normal, UE axes), AO, PdoL (local vector camera->surface correction).
float3 O = CamL / 100.0; O.y = -O.y;
float3 Pp = PixL / 100.0; Pp.y = -Pp.y;
float3 D = normalize(Pp - O);
float3 v = normalize(O);
v.z = max(v.z, 0.0);
float sv = abs(v.x) + abs(v.y) + v.z + 1e-6;
float vx = v.x / sv, vy = v.y / sv;
float gu = vx + vy, gw = vx - vy;
float gi = clamp((gu + 1.0) * 0.5 * G - 0.5, 0.0, G - 1.0);
float gj = clamp((gw + 1.0) * 0.5 * G - 0.5, 0.0, G - 1.0);
float i0 = min(floor(gi), G - 2.0), j0 = min(floor(gj), G - 2.0);
float fi = gi - i0, fj = gj - j0;
if (Far > 0.5) { i0 = round(gi); j0 = round(gj); fi = 0.0; fj = 0.0; }
float tpix = length(Pp - O);
float aA = 0.0; float3 aC = 0; float3 aN = 0; float aO = 0.0; float aT = 0.0;
float wDom = -1.0; float aDom = 0.0; float3 cDom = 0;   // the nearest view alone (its silhouette, see Alpha below)
[unroll] for (int q = 0; q < 4; q++) {
    float di = (q == 1 || q == 3) ? 1.0 : 0.0;
    float dj = (q >= 2) ? 1.0 : 0.0;
    float wt = (di > 0.5 ? fi : 1.0 - fi) * (dj > 0.5 ? fj : 1.0 - fj);
    if (wt < 0.002) continue;
    float ii = min(i0 + di, G - 1.0), jj = min(j0 + dj, G - 1.0);
    float uu = (ii + 0.5) / G * 2.0 - 1.0, ww = (jj + 0.5) / G * 2.0 - 1.0;
    float3 dk = float3((uu + ww) * 0.5, (uu - ww) * 0.5, 0.0);
    dk.z = max(1.0 - abs(dk.x) - abs(dk.y), 0.0);
    dk = normalize(dk);
    if (dk.z < 0.02) dk = normalize(float3(dk.x, dk.y, 0.02));
    float3 Y = normalize(float3(0, 0, 1) - dk.z * dk);
    float3 X = cross(Y, dk);
    float den = dot(D, dk);
    if (abs(den) < 1e-4) continue;
    float t = -dot(O, dk) / den;
    float3 P = O + t * D;
    float a = dot(P, X), b = dot(P, Y);
    if (abs(a) > 0.995 || abs(b) > 0.995) continue;
    float2 uv = float2((ii + (a + 1.0) * 0.5) / G, (jj + (1.0 - b) * 0.5) / G);
    float4 sa = Texture2DSample(TexA, TexASampler, uv);
    float4 sb = Texture2DSample(TexB, TexBSampler, uv);
    if (wt > wDom) { wDom = wt; aDom = sa.a; cDom = sa.rgb; }
    float w = wt * sa.a;
    aA += w;
    aC += w * sa.rgb;
    float2 e = sb.rg * 2.0 - 1.0;
    float3 n = float3(e.x, e.y, 1.0 - abs(e.x) - abs(e.y));
    float tt = max(-n.z, 0.0);
    n.x -= sign(n.x) * tt; n.y -= sign(n.y) * tt;
    aN += w * normalize(n);
    aO += w * sb.a;
    float off = (sb.b - 0.5) * 2.0;                                  // + = farther from that view, in sphere radii
    float3 Q = P - dk * off;
    aT += w * dot(Q - O, D);
}
float inv = 1.0 / max(aA, 1e-4);
// 11-11: coverage = the nearest view's own silhouette (or the blend, whichever is more). The plain weighted blend of 4 views
// that do not line up (thin pine branches, 22 deg apart) cut the crowns to holes and most pines vanished in the game.
Alpha = max(aA, aDom);
if (aA < 1e-3) { aC = cDom; inv = 1.0; }
float3 nl = normalize(aN * inv + float3(0, 0, 1e-4));
// 11-11: crown-volume normal. The baked leaf normals alone average out (leaf cards point every way): the trees were lit like
// a flat mat. Blend toward the normal of a crown sphere (centre CrownZ, radius CrownR in sphere radii; this pixel's ray hit,
// or its closest approach) so each crown gets a lit side and a dark side like the old blob trees.
float3 Cc = float3(0.0, 0.0, CrownZ);
float3 oc = O - Cc;
float bq = dot(oc, D);
float disc = bq * bq - (dot(oc, oc) - CrownR * CrownR);
float th = disc > 0.0 ? -bq - sqrt(disc) : -bq;
float3 nS = normalize(O + D * th - Cc + float3(0, 0, 1e-4));
nl = normalize(lerp(nl, nS, SphAmt));
NrmL = float3(nl.x, -nl.y, nl.z);
AO = aO * inv;
float dt = max(aT * inv - tpix, 0.0);
float3 dl = D * dt * 100.0; dl.y = -dl.y;
PdoL = dl;
return aC * inv;
