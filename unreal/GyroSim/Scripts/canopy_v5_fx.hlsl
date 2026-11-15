// M_CkCanopyV3Fx Custom node code as saved 11-15 (reference copy; the material uasset is the source the engine uses).
// Edit = change the node in the editor (or a patch script) and update this copy.
// canopy outer shell V5 (11-13, scratchpad review canopy_reflection_advice.md): physically based reflection
//   e = F2 x (A pilot + B sunlit edges + C interior cube + D outside) + E sun spot / glints, F2 = two-surface Fresnel
//   (ReflAmt ~1.9: the inner shell has no specular). A / B are shaded LIVE with the current sun (no baked sun):
//   L = albedo x (SunE x max(N.L, 0) + SkyE x sky view) / pi, scene-linear like every lit surface.
// Inputs reused (no graph change):  InSun = SunE (sun illuminance, scene units = directional light lux x colour),
//   LitAbs = SkyE (sky illuminance on an up-facing surface), HaloGlow = LitGain (A + B strength, 1 = physical),
//   VeilPow = SunPow (sun spot exponent, 300-500 for VR), Wobble = CubeMinLod (cube mip floor).
// canopy outer shell V4 (11-13, scratchpad review canopy_fable.md option 1): pure additive reflection F x L, no veil terms.
// Local frame = aircraft (x fwd, y right, z up, cm). The reflection ray from the glass point LP along the real (smooth)
// normal's reflection rl is occluded by a closed cockpit proxy (tub floor at the sill height, rear bulkhead, pilot spheres):
// hit = dark interior; no hit = the outside world through the opposite glass (sky light cube: sky above, bright ground /
// horizon below). Bright frame rings around the fuselage axis (aft canopy frame, windscreen bow) are found by ray-plane
// intersection and give the concentric bent arcs of real canopy photos (c12); they slide with the head like reflections.
float3 up = normalize(Up);
float3 fw = normalize(Fw);
float3 rt = normalize(Rt);
float3 v = normalize(CV);
float3 n = normalize(N);
float cosv = max(abs(dot(v, n)), 0.05);
float gz = 1.0 - cosv;
float3 d = LP - Eye;
float2 puv = float2(atan2(d.y, d.x), -atan2(d.z, length(d.xy)));
float4 t = Texture2DSample(T, TSampler, puv * Tile);
float scr = t.r;
float3 sw = normalize(Sun);
float c = dot(-v, sw);
float F = saturate((F0 + (1.0 - F0) * pow(gz, 5.0)) * ReflAmt);
float2 t2 = t.ba * 2.0 - 1.0;
float3 sl = float3(dot(sw, fw), dot(sw, rt), dot(sw, up));
float2 suv = float2(atan2(sl.y, sl.x), -atan2(sl.z, length(sl.xy)));
float2 ds = suv - puv;
ds.x = ds.x - 6.2831853 * round(ds.x / 6.2831853);
float psi = atan2(ds.y, ds.x);
float aniso = pow(saturate(0.5 - 0.5 * dot(t2, float2(cos(2.0 * psi), sin(2.0 * psi)))), AnisoPow);
float glint = pow(saturate(c * 0.5 + 0.5), GlintPow) * step(0.0, c + 0.3);
float3 r = normalize(R);
float3 rl = float3(dot(r, fw), dot(r, rt), dot(r, up));
float sunUp = saturate(dot(sw, up));
float SunE = InSun, SkyE = LitAbs, LitGain = HaloGlow;
float3 sunC = SunCol / max(dot(SunCol, float3(0.2126, 0.7152, 0.0722)), 1e-4);   // sun colour, unit luminance
float3 lit = (sunC * SunE * saturate(sl.z) + SkyE) / 3.14159265 * LitGain;        // up-facing surface radiance per unit albedo
// ---- closed cockpit proxy ----
float tHit = 1e9;
float hitP = 0.0;                                  // 1 = the pilot (analytic, live sun) is the nearest hit
// outside seen through the opposite glass: the sky light cube (Env) is black in this scene's translucent pass (11-13 test:
// x1000 still 0), so a world-up sky / horizon / ground gradient scaled by EnvGain stands in for it (look-matched, estimate)
float rz = r.z;
float3 skyc = lerp(float3(0.62, 0.70, 0.82), float3(0.12, 0.22, 0.48), saturate(rz * 1.6));
float3 outc = lerp(float3(0.42, 0.40, 0.37), skyc, smoothstep(-0.12, 0.02, rz));
float3 Lr = (Env + outc) * EnvGain;                                 // no hit: outside through the opposite glass
if (rl.z < -0.001) {                               // tub floor / consoles at the sill height
    float th = (CoamZ - LP.z) / rl.z;
    float3 H = LP + rl * th;
    if (th > 0.0 && abs(H.y) < 52.0 && H.x > 255.0 && H.x < 565.0) {
        tHit = th;
        float gs = smoothstep(GsX - 3.0, GsX + 3.0, H.x) * (1.0 - smoothstep(31.0, 37.0, abs(H.y)));
        float con = (1.0 - smoothstep(GsX - 3.0, GsX + 3.0, H.x)) * smoothstep(327.0, 333.0, H.x) * smoothstep(15.0, 21.0, abs(H.y));
        float3 alb = lerp(InCol * 0.35, InCol, con);
        alb = lerp(alb, InCol * 0.08, gs);
        Lr = lit * alb;
    }
}
if (rl.x < -0.001) {                               // rear bulkhead / seat back
    float tb = (BulkX - LP.x) / rl.x;
    float3 Hb = LP + rl * tb;
    if (tb > 0.0 && tb < tHit && abs(Hb.y) < 45.0 && Hb.z < 145.0) {
        tHit = tb;
        Lr = SkyE * 0.5 / 3.14159265 * LitGain * InCol * 0.12;   // seat back / bulkhead: in shade, half sky
    }
}
// 11-15 (fixes_1114 r08): helmet smaller / fainter (HelmetR, HelmetAlb) and soft-edged (PilotSoft): the hard flat disc
// read as a white ellipse in the side glass. PilotSoft 0 + HelmetR 14 + HelmetAlb 0.8 = the V5 (11-14) pilot term.
float3 Lp = float3(0.0, 0.0, 0.0);
float wp = 0.0;
float4 sph[3] = { float4(Eye + float3(-6.0, 0.0, 4.0), HelmetR), float4(Eye + float3(-14.0, 19.0, -22.0), 10.0),
                  float4(Eye + float3(-14.0, -19.0, -22.0), 10.0) };
float3 scol[3] = { float3(1.0, 1.0, 0.975) * HelmetAlb, float3(0.22, 0.24, 0.18), float3(0.22, 0.24, 0.18) };   // helmet (V5: 0.80 white), suit / harness
[unroll] for (int k = 0; k < 3; k++) {
    float3 oc = LP - sph[k].xyz;
    float bq = dot(oc, rl);
    float disc = bq * bq - (dot(oc, oc) - sph[k].w * sph[k].w);
    if (disc > 0.0) {
        float tk = -bq - sqrt(disc);
        if (tk > 0.0 && tk < tHit) {
            tHit = tk; hitP = 1.0;
            float3 ns = normalize(LP + rl * tk - sph[k].xyz);                 // local frame sphere normal
            float3 E = sunC * SunE * saturate(dot(ns, sl)) + SkyE * (0.5 + 0.5 * ns.z);
            Lp = scol[k] * E / 3.14159265 * LitGain;
            // soft rim: disc / r^2 = 1 - (ray miss distance / r)^2 -> 0 at the silhouette
            wp = PilotRefl * ((PilotSoft > 0.0) ? smoothstep(0.0, PilotSoft, disc / (sph[k].w * sph[k].w)) : 1.0);
            if (PilotSoft <= 0.0) Lr = lerp(Lr, Lp, PilotRefl);      // V5: the pilot replaces the analytic interior here
        }
    }
}
// ---- bright frame rings around the fuselage axis (centre y 0, z RingZ, radius RingR) at x = ring planes ----
float3 rings = float3(0.0, 0.0, 0.0);
float xr[4] = { RingX0, RingX0 + 14.0, RingX1, RingX1 - 10.0 };
float wr[4] = { 1.0, 0.45, 0.8, 0.35 };          // second images (other glass face / frame edge): weaker
[unroll] for (int j = 0; j < 4; j++) {
    if (abs(rl.x) > 0.001) {
        float tr = (xr[j] - LP.x) / rl.x;
        if (tr > 0.0 && tr < tHit) {
            float3 Hr = LP + rl * tr;
            float2 q = float2(Hr.y, Hr.z - RingZ);
            float rad = length(q);
            float dd = (rad - RingR) / RingW;
            float ang = atan2(q.y, q.x);
            float rivet = 0.65 + 0.35 * step(0.5, frac(ang * 9.5493));    // rivet / segment dashes
            float3 rn = normalize(float3(0.0, -q.x, -q.y) + 1e-4);
            float3 Er = sunC * SunE * saturate(dot(rn, sl)) + SkyE * (0.5 + 0.5 * rn.z);
            rings += 0.35 * Er / 3.14159265 * LitGain * RingGain * wr[j] * exp(-dd * dd) * rivet * step(RingZ - RingR * 0.55, Hr.z);
        }
    }
}
// baked interior cube (11-13, scratchpad review canopy_techniques.md 4.2): captured once at the design eye in the aircraft
// frame with the sky / fog / clouds BLACK; parallax-corrected against a cockpit-sized box; replaces the analytic interior
// where the proxy is hit and is simply added elsewhere (black sky = no reflection). CubeAmt 0 = analytic only.
if (CubeAmt > 0.001) {
    float3 prd = rl + float3(1e-5, 1e-5, 1e-5);
    float pt;
    if (PxMode < 0.5) {                            // box proxy (Lagarde)
        float3 pta = (PxMax - LP) / prd;
        float3 ptb = (PxMin - LP) / prd;
        float3 ptf = max(pta, ptb);
        pt = max(min(min(ptf.x, ptf.y), ptf.z), 0.0);
    } else {                                       // ellipsoid inscribed in PxMin..PxMax (a sphere when the box is a cube):
        float3 pc = 0.5 * (PxMin + PxMax);         // smooth -> no creases where the box faces meet
        float3 pr = max(0.5 * (PxMax - PxMin), float3(1.0, 1.0, 1.0));
        float3 eo = (LP - pc) / pr;
        float3 ed = rl / pr;
        float qa = dot(ed, ed);
        float qb = dot(eo, ed);
        float qc = dot(eo, eo) - 1.0;
        pt = max((-qb + sqrt(max(qb * qb - qa * qc, 0.0))) / max(qa, 1e-8), 0.0);
    }
    float3 cdir = LP + rl * pt - CubePos;
    float clod = Wobble;                                                                 // mip floor CubeMinLod
#if PIXELSHADER
    clod = max(Cube.CalculateLevelOfDetail(CubeSampler, cdir), Wobble);                  // footprint mip (not in ray tracing hit shaders)
#endif
    float3 cin = Cube.SampleLevel(CubeSampler, cdir, clod).rgb;
    // 11-14 safety clamp (scratchpad canopy_barfix): no cube texel brighter than a sky-lit white diffuse surface
    // (albedo 1 x SkyE / pi) x CubeClamp; keeps the colour (scales by the largest channel). CubeClamp 0 = no clamp.
    float ccap = CubeClamp * SkyE / 3.14159265;
    if (ccap > 0.0) { float cmx = max(max(cin.r, cin.g), cin.b); cin *= min(1.0, ccap / max(cmx, 1e-6)); }
    cin *= CubeGain;
    float3 lc = (hitP > 0.5 && PilotSoft <= 0.0) ? Lr : ((tHit < 1e8) ? cin : Lr + cin);   // V5: pilot analytic; 11-15: cube behind it
    Lr = lerp(Lr, lc, saturate(CubeAmt));
}
if (PilotSoft > 0.0) Lr = lerp(Lr, Lp, wp);       // 11-15: soft-edged pilot over what is behind him (cube / interior / outside)
float SunPow = max(VeilPow, 1.0);
float sun = pow(saturate(dot(r, sw)), SunPow) * SunSpec * (SunPow / 3000.0);           // wider, same energy (VR: no one-eye sparkle)
float3 e = F * (Lr + rings) + SunCol * sun * F * 10.0 + SunCol * (scr * aniso * glint * Gain);
return float4(e, 1.0);
