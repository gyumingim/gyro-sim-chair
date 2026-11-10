// GyroLife motion (vertex, WPO): instance custom data -> position x along the instance's local +X, car number n.
// Shared head of the vehicle / ship / wake custom nodes (Scripts/life_assets.py pastes it in front of each body).
// Inputs: L C J V D SEED FL K (PerInstanceCustomData 0..7), T (Time), TFix (>= 0 = frozen time for repeatable shots),
// LP (instance-local position cm), WPR (camera-relative world position cm), Far (cm), SC (instance scale along X).
float t = (TFix >= 0.0) ? TFix : T;
float g = t * V + C;
float w = floor(g / max(D, 1.0));
float x = (g - w * max(D, 1.0)) + J * D;
float n = J + K - w;
float s = (x < L) ? 1.0 : 0.0;
if (fmod(FL, 2.0) >= 1.0) s *= saturate(x / 400.0);              // first piece of an open chain: grow in over 4 m
if (FL >= 2.0) s *= saturate((L - x) / 400.0);                    // last piece: shrink out
float dist = length(WPR);
s *= 1.0 - smoothstep(Far * 0.7, Far, dist);                      // fade out (shrink) towards the cull distance
uint hn = (uint)(n + 1048576.0);
uint h = hn * 747796405u + (uint)(frac(SEED) * 65535.0) * 2891336453u + 12345u;
h = ((h >> ((h >> 28u) + 4u)) ^ h) * 277803737u;
h = (h >> 22u) ^ h;
float r1 = (float)(h & 65535u) / 65535.0;
float r2 = (float)((h >> 16u) & 65535u) / 65535.0;
