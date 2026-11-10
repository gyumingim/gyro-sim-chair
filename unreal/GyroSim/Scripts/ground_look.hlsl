// V-World photo ground look (vworld mode): sea surface + photo colour match. Body of the Custom node in
// /Game/Materials/Ground/M_GyroGround (Scripts/ground_material.py pastes this file in, after Cesium's material layers).
// Inputs:  C (layer base colour = V-World photo, linear), Rg / Sp (layer roughness / specular), N (vertex normal, world),
//          P (absolute world position, cm; world frame X north, Y east, Z up, Z 0 = mean sea level at the origin),
//          Q (camera-relative world position, cm), T (time s), WaveTex (+ WaveTexSampler), parameters below.
// Outputs: return = base colour; Rough, Spec, NormalWS (world space: the material has tangent space normals off), Mask.
// Sea mask: the Copernicus DEM has the sea at exactly 0 m MSL (terrain_build.py; the EGM2008 geoid varies only
// 28.99..29.42 m over Busan), so the height above the sea - Z plus the curvature drop X^2/2M + Y^2/2N of the local
// tangent frame - picks the sea (and river surfaces at 0 m). Bright photo pixels (ships, piers, breakwaters) and grey /
// brown ones (rock islets the 30 m DEM flattened to 0 m, quays) and green ones (delta fields 1-3 m up) stay land: sea
// pixels are blue / teal (B > R, B >= ~0.8 G). The height band is wide (the 30 m DEM ramps the coast over ~1 cell).

float3 up = normalize(N);
float dist = length(Q) * 0.01;                                                    // m from the camera
float h = (P.z + P.x * P.x / (2.0 * CurvM) + P.y * P.y / (2.0 * CurvN)) * 0.01;   // m above the sea (approx.)
float lum = dot(C, float3(0.2126, 0.7152, 0.0722));
float mH = 1.0 - smoothstep(SeaH0, SeaH1, h);
float mC = 1.0 - smoothstep(GuardL0, GuardL1, lum);                               // bright = ship / pier / foam -> land
float mB = smoothstep(GuardB0, GuardB1, C.b - C.r)                                 // grey / brown = rock islet, quay -> land
         * smoothstep(0.70, 0.90, C.b / max(C.g, 1e-4));                           // green = low fields / parks -> land
float m = saturate(WaterOn * mH * mC * mB);
Mask = m;

// ---- land: photo colour match (orthophoto tiles are graded brighter / more saturated than the scene light) --------
float3 g = lerp(lum.xxx, C, LandSat);
g = LandMid * pow(max(g, 1e-5) / LandMid, LandContrast);
g *= LandGain * LandTint;

// ---- sea: dark water body + sky reflection (Fresnel, from the engine's specular), wind waves -------------------------
// water leaving reflectance of coastal sea is only a few percent: the look is mostly the reflected sky (Specular)
float detail = clamp(lum / max(PhotoSeaLum, 1e-4), 0.55, 1.8);                  // keep the photo's own variation (wakes, swell)
float3 desat = lerp(lum.xxx, C, ShallowSat);
float3 body = lerp(DeepColor * detail, desat * ShallowGain, ShallowMix * saturate((lum - PhotoSeaLum) / max(PhotoSeaLum, 1e-4)));
float fade = saturate(dist / WaveFadeM);
// three octaves at unrelated scales / directions (no visible repeat), the small ones fade out with distance (they would
// alias into a grid); far away only the long swell octave and the growing roughness remain
float2 uv1 = P.xy / WaveScale + T * float2(0.013, 0.007);
float2 uv2 = float2(P.x * 0.8 - P.y * 0.6, P.x * 0.6 + P.y * 0.8) / (WaveScale * 0.37) + T * float2(-0.011, 0.017);
float2 uv3 = float2(P.x * 0.94 + P.y * 0.34, -P.x * 0.34 + P.y * 0.94) / (WaveScale * 7.3) + T * float2(0.004, -0.002);
float2 n1 = Texture2DSample(WaveTex, WaveTexSampler, uv1).xy * 2.0 - 1.0;
float2 n2 = Texture2DSample(WaveTex, WaveTexSampler, uv2).xy * 2.0 - 1.0;
float2 n3 = Texture2DSample(WaveTex, WaveTexSampler, uv3).xy * 2.0 - 1.0;
float near = 1.0 - fade;
float2 nxy = (n1 * near * near + n2 * near * 0.7) * WaveStrength + n3 * WaveStrength * 0.5 * (1.0 - 0.5 * fade);
float3 tx = normalize(cross(float3(0.0, 1.0, 0.0), up));                          // ~ north on the sea plane
float3 ty = cross(up, tx);
float3 nw = normalize(nxy.x * tx + nxy.y * ty + up);
NormalWS = normalize(lerp(up, nw, m));
// unresolved waves far away widen the sun glint (roughness grows with distance), F0 water = 0.02 -> Specular 0.25
Rough = lerp(Rg, lerp(WaterRough, WaterRoughFar, fade), m);
Spec = lerp(Sp, WaterSpec, m);
return lerp(g, body, m);
