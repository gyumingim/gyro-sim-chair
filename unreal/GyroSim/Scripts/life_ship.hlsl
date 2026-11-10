// GyroLife ships: mesh vertex colour = base colour, UV.x = paint flag (1 hull, 2 trim / funnel / hatch covers), swapped
// for a colour per ship (hash of lane seed and ship number) from the palette of this ship type (Kind: 0 container,
// 1 feeder, 2 ferry, 3 bulk, 4 tug, 5 fishing, 6 boat). Small craft heave gently. Output: local offset cm; CR colour + roughness.
float3 hull, trim;
float u = r1, v2 = r2;
if (Kind < 1.5) {
    hull = (u < 0.30) ? float3(0.025, 0.04, 0.09) : (u < 0.60) ? float3(0.018, 0.018, 0.02) : (u < 0.78) ? float3(0.14, 0.03, 0.025)
         : (u < 0.90) ? float3(0.03, 0.08, 0.06) : float3(0.10, 0.11, 0.12);
    trim = (v2 < 0.5) ? float3(0.75, 0.75, 0.74) : float3(0.30, 0.08, 0.05);
} else if (Kind < 2.5) {
    hull = float3(0.80, 0.81, 0.82);
    trim = (u < 0.4) ? float3(0.03, 0.12, 0.45) : (u < 0.7) ? float3(0.55, 0.05, 0.05) : float3(0.02, 0.05, 0.16);
} else if (Kind < 3.5) {
    hull = (u < 0.4) ? float3(0.02, 0.02, 0.022) : (u < 0.7) ? float3(0.03, 0.05, 0.12) : float3(0.22, 0.05, 0.04);
    trim = (v2 < 0.5) ? float3(0.30, 0.31, 0.32) : float3(0.25, 0.07, 0.05);
} else if (Kind < 4.5) {
    hull = (u < 0.4) ? float3(0.40, 0.04, 0.03) : (u < 0.7) ? float3(0.02, 0.02, 0.022) : float3(0.03, 0.10, 0.35);
    trim = (v2 < 0.5) ? float3(0.70, 0.30, 0.03) : float3(0.02, 0.02, 0.02);
} else if (Kind < 5.5) {
    hull = (u < 0.45) ? float3(0.70, 0.71, 0.72) : (u < 0.75) ? float3(0.05, 0.16, 0.45) : float3(0.12, 0.35, 0.55);
    trim = (v2 < 0.5) ? float3(0.05, 0.20, 0.45) : float3(0.55, 0.30, 0.05);
} else {
    hull = (u < 0.7) ? float3(0.80, 0.81, 0.82) : (u < 0.85) ? float3(0.03, 0.06, 0.18) : float3(0.45, 0.45, 0.47);
    trim = float3(0.80, 0.81, 0.82);
}
float3 col = (UV.x > 1.5) ? trim : (UV.x > 0.5) ? hull : VC.rgb;
CR = float4(col, (UV.x > 2.5) ? r1 : (UV.x > 0.5) ? 0.45 : 0.6);   // containers: alpha carries the ship seed to the pixel node
float bob = (Kind > 3.5) ? ((Kind > 5.5) ? 18.0 : 10.0) : 0.0;
float ph = r1 * 6.2832;
float3 o = float3(x / max(SC, 0.01), 0, bob * sin(t * 1.3 + ph) + bob * 0.5 * sin(t * 2.1 + ph * 1.7));
// tiny pitch / roll for small craft (rotate LP about the pivot)
float pr = (bob > 0.0) ? 0.012 * sin(t * 0.9 + ph) : 0.0;
float rr = (bob > 0.0) ? 0.02 * sin(t * 1.1 + ph * 2.3) : 0.0;
float3 lp2 = LP + float3(0, 0, LP.x * pr + LP.y * rr);
return o + (lp2 * s - LP);
