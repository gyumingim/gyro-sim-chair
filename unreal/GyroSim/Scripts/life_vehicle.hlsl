// GyroLife road vehicles: SM_LifeVehicle = three unit boxes (UV.x = part * 10 + paint: 0 body, 1 cabin, 2 shadow plate).
// Kind per car (hash of lane seed and car number, shares by road class = floor(SEED)): 0 sedan 1 SUV 2 1-ton truck 3 bus 4 truck.
// Output: local-space offset (cm) for WPO (through a Local -> World vector transform); CR = base colour + roughness.
int cls = (int)floor(SEED);
// class order = sim/traffic_build.py CLASS: motorway trunk primary secondary tertiary motorway_link trunk_link primary_link secondary_link tertiary_link
float pb = (cls == 2) ? 0.09 : (cls == 3) ? 0.07 : (cls == 1) ? 0.04 : (cls == 4) ? 0.04 : 0.015;
float pt = (cls == 0) ? 0.20 : (cls == 1 || cls == 5 || cls == 6) ? 0.12 : 0.04;
float pp = 0.10;
int kind = (r1 < pb) ? 3 : (r1 < pb + pt) ? 4 : (r1 < pb + pt + pp) ? 2 : (r1 < pb + pt + pp + 0.30) ? 1 : 0;
// sizes cm: body (len, wid, hgt, z0, xoff), cabin (len, wid, hgt, z0, xoff)
float4 bA = float4(460, 180, 75, 20);  float bX = 0;    float4 cA = float4(240, 160, 55, 95);  float cX = -20;
if (kind == 1) { bA = float4(470, 190, 90, 25);  bX = 0;    cA = float4(300, 176, 75, 115); cX = -25; }
if (kind == 2) { bA = float4(320, 176, 60, 60);  bX = -85;  cA = float4(165, 170, 150, 45); cX = 165; }
if (kind == 3) { bA = float4(1150, 250, 195, 30); bX = 0;   cA = float4(1130, 248, 95, 225); cX = 0; }
if (kind == 4) { bA = float4(620, 245, 260, 110); bX = -110; cA = float4(210, 240, 200, 70); cX = 310; }
float part = floor(UV.x / 10.0 + 0.01);
float paint = UV.x - part * 10.0;
float3 sz, ce;
if (part < 0.5)      { sz = bA.xyz; ce = float3(bX, 0, bA.w + bA.z * 0.5); }
else if (part < 1.5) { sz = cA.xyz; ce = float3(cX, 0, cA.w + cA.z * 0.5); }
else {
    float x0 = min(bX - bA.x * 0.5, cX - cA.x * 0.5), x1 = max(bX + bA.x * 0.5, cX + cA.x * 0.5);
    sz = float3(x1 - x0 + 50, max(bA.y, cA.y) + 40, 1); ce = float3((x0 + x1) * 0.5, 0, 4);
}
float3 nl = LP * sz + ce;
// paint: Korean car colours (white / grey / black dominate), trucks white boxes, city buses blue / green / red
float3 pc;
float u = r2;
if (kind <= 1) pc = (u < 0.33) ? float3(0.72, 0.72, 0.71) : (u < 0.48) ? float3(0.42, 0.43, 0.45) : (u < 0.62) ? float3(0.16, 0.17, 0.18)
                 : (u < 0.82) ? float3(0.02, 0.02, 0.025) : (u < 0.88) ? float3(0.03, 0.06, 0.16) : (u < 0.92) ? float3(0.36, 0.03, 0.03)
                 : (u < 0.96) ? float3(0.30, 0.26, 0.20) : float3(0.12, 0.22, 0.35);
else if (kind == 2) pc = (u < 0.55) ? float3(0.72, 0.72, 0.71) : float3(0.06, 0.16, 0.42);
else if (kind == 3) pc = (u < 0.40) ? float3(0.05, 0.20, 0.50) : (u < 0.70) ? float3(0.06, 0.32, 0.14) : (u < 0.85) ? float3(0.50, 0.06, 0.05) : float3(0.62, 0.62, 0.60);
else pc = (part < 0.5) ? ((u < 0.7) ? float3(0.70, 0.70, 0.69) : float3(0.30, 0.30, 0.32)) : ((u < 0.5) ? float3(0.72, 0.72, 0.71) : float3(0.08, 0.18, 0.45));
float3 col = (part > 1.5) ? float3(0.012, 0.012, 0.012) : (paint > 0.5) ? pc : float3(0.015, 0.02, 0.025);
float rough = (part > 1.5) ? 1.0 : (paint > 0.5) ? 0.38 : 0.08;
CR = float4(col, rough);
return float3(x / max(SC, 0.01), 0, 0) + (nl * s - LP);
