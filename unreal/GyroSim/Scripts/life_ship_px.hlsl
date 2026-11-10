// GyroLife ships, pixel: containers (UV.x = 3) get one muted colour per 6.1 x 2.44 x 2.59 m box (local position, so the
// pattern rides with the ship) and dark seams between boxes; everything else passes CR through. -> float4 colour, roughness.
float3 col = CR.rgb;
float rough = CR.a;
if (UV.x > 2.5) {
    float3 q = LP / 100.0;
    float3 cell = float3(6.1, 2.44, 2.59);
    float3 id = floor(q / cell);
    float3 f = frac(q / cell);
    // colour per block of boxes (one 12.8 m bay x ~3 rows, all tiers: reads as 2-4 flat colours per bay from the air, not
    // speckle), each box only +-8 % brightness
    float3 blk = float3(floor(q.x / 12.8), floor(q.y / 7.3), 0);
    float h = frac(sin(dot(blk + CR.a * 31.7, float3(12.9898, 78.233, 37.719))) * 43758.5453);
    float h2 = frac(sin(dot(id, float3(39.35, 11.13, 83.17))) * 24634.63);
    int k = (int)floor(h * 11.0);
    float3 pal[11] = { float3(0.26, 0.06, 0.035), float3(0.15, 0.03, 0.03), float3(0.03, 0.06, 0.16), float3(0.02, 0.035, 0.08),
                       float3(0.22, 0.23, 0.24), float3(0.55, 0.55, 0.53), float3(0.06, 0.12, 0.06), float3(0.15, 0.08, 0.035),
                       float3(0.16, 0.22, 0.30), float3(0.32, 0.11, 0.03), float3(0.04, 0.13, 0.14) };
    col = pal[k] * (0.92 + 0.16 * h2);
    float3 n = normalize(cross(ddx(q), ddy(q)));
    float3 e = min(f, 1.0 - f) * cell;
    float edge = min(min(abs(n.x) > 0.5 ? 1e3 : e.x, abs(n.y) > 0.5 ? 1e3 : e.y), abs(n.z) > 0.5 ? 1e3 : e.z);
    col *= lerp(0.35, 1.0, saturate(edge / 0.10));
    rough = 0.7;
}
return float4(col, rough);
