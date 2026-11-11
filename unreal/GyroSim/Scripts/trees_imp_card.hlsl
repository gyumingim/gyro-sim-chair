// Impostor card (vertex stage, -> World Position Offset in LOCAL units; the graph turns it into world).
// Inputs: CamL = camera in instance-local space (cm), PosL = this vertex in local space before the offset (cm), UV = corner id.
// Local space: the card mesh is the +-100 cm cube's diagonal quad, the instance scale = the tree's bounding sphere radius
// (non-uniform: crown width / height), so the sphere is radius 100 here. The card faces the camera
// (see below for where the card sits and its size). Camera inside the sphere -> card collapsed (not drawn).
float3 c = CamL / 100.0;
float d = length(c);
if (d < 1.02) return -PosL;
float3 f = c / d;
float3 up0 = abs(f.z) > 0.999 ? float3(1, 0, 0) : float3(0, 0, 1);
float3 r = normalize(cross(up0, f));
float3 u = cross(f, r);
// 11-11: the card sits on the sphere's FRONT (toward the camera), not through its centre. Through the centre, on a hillside
// the far half of the card was under the slope, so the terrain hid most trees on slopes facing the camera. Half size at that
// plane: (d - 1) tan(asin(1 / d)) = (d - 1) / sqrt(d^2 - 1) still covers the sphere's silhouette.
float FWD = 1.0;
float s = (d - FWD) / sqrt(d * d - 1.0);
float2 k = float2(UV.x * 2.0 - 1.0, 1.0 - UV.y * 2.0);
float3 p = (f * FWD + (r * k.x + u * k.y) * s) * 100.0;
return p - PosL;
