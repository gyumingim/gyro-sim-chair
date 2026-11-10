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
float k = saturate(Spd / 450.0);
float o;
if (part < 0.25) {                                   // stern trail: churned centre, spreading and fading
    float cx = (across - 0.5) * 2.0;
    float core = exp(-cx * cx * 2.5);
    o = 0.85 * core * pow(1.0 - along, 1.6) * foam * (0.6 + 0.4 * saturate(1.0 - along * 3.0));
} else if (part < 0.75) {                            // Kelvin arms: thin lines of broken water
    float cx = (across - 0.5) * 2.0;
    o = 0.45 * exp(-cx * cx * 4.0) * pow(1.0 - along, 2.2) * foam;
} else {                                             // bow wave along the hull
    o = 0.8 * pow(1.0 - across, 1.5) * (1.0 - along) * saturate(0.5 + foam);
}
return saturate(o * k) * Amt;
