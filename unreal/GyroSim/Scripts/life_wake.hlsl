// GyroLife wake foam (pixel, translucent): SM_LifeWake vertex colour = (along 0..1, across 0..1, part 0 trail / 0.5 Kelvin
// arm / 1 bow wave), P = absolute world position cm (foam texture fixed on the water, so the ship moves through it),
// Spd = ship speed cm/s (PerInstanceCustomData 3), T / TFix time. -> opacity (foam colour is a constant).
float t = (TFix >= 0.0) ? TFix : T;
float along = VC.r, across = VC.g, part = VC.b;
float2 q = P.xy / 900.0;
// value noise, 2 octaves
float2 i0 = floor(q), f0 = frac(q);
float2 uu = f0 * f0 * (3.0 - 2.0 * f0);
float a = frac(sin(dot(i0, float2(127.1, 311.7))) * 43758.55), b = frac(sin(dot(i0 + float2(1, 0), float2(127.1, 311.7))) * 43758.55);
float c = frac(sin(dot(i0 + float2(0, 1), float2(127.1, 311.7))) * 43758.55), d = frac(sin(dot(i0 + float2(1, 1), float2(127.1, 311.7))) * 43758.55);
float n1 = lerp(lerp(a, b, uu.x), lerp(c, d, uu.x), uu.y);
float2 q2 = P.xy / 230.0 + float2(t * 0.05, 0);
i0 = floor(q2); f0 = frac(q2); uu = f0 * f0 * (3.0 - 2.0 * f0);
a = frac(sin(dot(i0, float2(127.1, 311.7))) * 43758.55); b = frac(sin(dot(i0 + float2(1, 0), float2(127.1, 311.7))) * 43758.55);
c = frac(sin(dot(i0 + float2(0, 1), float2(127.1, 311.7))) * 43758.55); d = frac(sin(dot(i0 + float2(1, 1), float2(127.1, 311.7))) * 43758.55);
float n2 = lerp(lerp(a, b, uu.x), lerp(c, d, uu.x), uu.y);
float foam = saturate(0.35 + 0.9 * n1 * n2 + 0.25 * n2);
float k = saturate(Spd / 600.0);
// fade with distance behind the ship: faster ships keep their wake longer (along 0..1 = ~4.5 ship lengths; a 300 m ship at
// 11 kn fades out over ~500 m, a 165 m ferry at 17 kn over ~600 m)
float keep = lerp(0.25, 0.55, saturate(Spd / 900.0));
float o;
if (part < 0.25) {                                   // stern trail: narrow churned centre, quickly thinning
    float cx = (across - 0.5) * 2.0;
    float core = exp(-cx * cx * 7.0);
    o = 0.45 * core * saturate(1.0 - along / keep) * foam * (0.5 + 0.5 * saturate(1.0 - along * 6.0));
} else if (part < 0.75) {                            // Kelvin arms: thin, faint lines
    float cx = (across - 0.5) * 2.0;
    o = 0.16 * exp(-cx * cx * 10.0) * saturate(1.0 - along / (keep * 1.2)) * foam;
} else {                                             // bow wave along the hull
    o = 0.45 * pow(1.0 - across, 2.0) * (1.0 - along) * saturate(0.5 + foam);
}return saturate(o * k) * Amt;
