// Reflective curtain-wall glass for the Busan landmark models (sim/landmarks/landmarks_build.py glb tiles). Body of the
// Custom node in /Game/Landmarks/M_GyroLandmark (Scripts/landmarks_material.py pastes this file in, after Cesium's glTF
// material layers, like the ground material). Material only, the glb tiles are unchanged.
// Inputs:  C / Rg / Mt / Sp (layer base colour, roughness, metallic, specular = the glb's PBR values x vertex colour),
//          UV (TEXCOORD_0: facade texture repeats, 4 bays x 4 floors per repeat), N (vertex normal, world),
//          V (camera vector, surface -> eye), L (direction to the sun, SkyAtmosphereLightDirection),
//          parameters below (MI_GyroLandmark, defaults = landmarks_look.GLASS).
// Outputs: return = base colour; Rough, Metal, Spec, NormalWS (world space: tangent space normals off)
// Which pixels are glass: the glb facade modules have glass panes (metallic 0.5-0.6, roughness 0.07-0.1) and frames /
// mullions / spandrel bands (metallic 0.1, roughness 0.55) - mip-mapped far away they blend. t = glass share from the
// metallic value, and the pixel is a glass-module pixel only when its roughness agrees with that blend (stone, panels,
// metal roofs, membranes have other metallic / roughness pairs and keep the glb look).
// Why: the glb glass (light blue base 0.3-0.5, metallic 0.6) read as pale, uniform plastic - real glass towers are a dark
// body (the interior behind the pane transmits little back) with a ~10-20 % reflection of the sky and the city that rises
// with the view angle (Fresnel), and every pane / floor reflects slightly differently (panes are never exactly flat or
// coplanar: 'oil canning', heat-strengthened glass roller waves ~0.1-0.3 deg, installation tolerances ~1 deg).

Rough = Rg; Metal = Mt; Spec = Sp; NormalWS = N;
float tRaw = (Mt - FrameM) / max(PaneM - FrameM, 1e-3);                  // 0 = frame, 1 = pane
float t = saturate(tRaw);
float rgWant = lerp(FrameR, PaneR, t);                                   // roughness of that blend in the glb
float isMod = (1.0 - smoothstep(0.06, 0.10, abs(Rg - rgWant))) * step(-0.05, tRaw) * step(tRaw, 1.25);
float g = saturate(GlassOn * isMod);
if (g <= 0.0)
{
    return C;
}

// panes / floors: one texture repeat = 4 x 4 cells
#define H1(x) frac(sin((x) * 12.9898) * 43758.5453)
float2 q = UV * Grid;
float2 cell = floor(q);
float2 f = frac(q) - 0.5;
float2 fw = max(abs(ddx(q)) + abs(ddy(q)), 1e-4);                         // cells per pixel
float near = 1.0 - saturate((max(fw.x, fw.y) - 0.2) / 0.5);              // sub-pixel panes far away: no per-pane detail
float hp = H1(cell.x * 1.731 + cell.y * 37.17);                          // per pane
float hp2 = H1(cell.x * 7.13 + cell.y * 3.71 + 1.3);
float hp3 = H1(cell.x * 3.37 + cell.y * 11.9 + 4.7);
float hf = H1(cell.y * 0.917 + 9.1);                                     // per floor (whole row: coating batch / interior)

// body colour: dark tinted pane, small per-pane / per-floor brightness change
float vary = 1.0 + near * (PaneVar * (hp - 0.5) + FloorVar * (hf - 0.5));
float3 paneCol = C * GlassDark * vary;
float3 frameCol = C * FrameGain;
float3 col = lerp(frameCol, paneCol, t);

// normal: per-pane tilt + a slight pillow inside each pane (oil canning), fading out where panes are sub-pixel
float3 up = float3(0.0, 0.0, 1.0);
float3 tx = abs(N.z) > 0.95 ? float3(1.0, 0.0, 0.0) : normalize(cross(up, N));   // along the wall
float3 ty = cross(N, tx);                                                         // up the wall
float tilt = tan(radians(TiltDeg));
float2 d = float2(hp2 - 0.5, hp3 - 0.5) * 2.0 * tilt + f * tan(radians(BowDeg)) * 2.0;
float3 nP = normalize(N + (d.x * tx + d.y * ty) * near * t);
NormalWS = normalize(lerp(N, nP, g));

float rPane = GlassRough + GlassRoughVar * hp * near;
// backlit v2 (11-11, BacklitV2 on / off; same rule as buildings_facade.hlsl): looking toward the sun the
// panes go dark and matte except a BkKeep share of single panes (glints) - backlit photos: facade glints ~0.1 % of pixels,
// sun-side facades ~3.6 stops under the sky near the sun. Far away (sub-pixel panes) the average.
float3 Ls = normalize(L + float3(0.0, 0.0, 1e-4));
float bkV = BacklitV2 * smoothstep(0.15, 0.75, dot(-normalize(V), Ls));
float bkKeep = lerp(BkKeep, step(1.0 - BkKeep, H1(cell.x * 2.9 + cell.y * 13.7 + 5.1)), near);
float bkG = bkV * (1.0 - bkKeep) * t;
col *= lerp(1.0, BkDark, bkG);
rPane += BkRough * bkG;
Rough = lerp(Rg, lerp(FrameRough, rPane, t), g);
Metal = lerp(Mt, lerp(FrameMetal, GlassMetal * lerp(1.0, BkMetal, bkV * (1.0 - bkKeep)), t), g);
Spec = lerp(Sp, lerp(0.5, GlassSpec, t), g);
return lerp(C, col, g);
