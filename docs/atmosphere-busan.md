# 부산 공기 · 빛 · 바다 (11-10)

목표: 하늘·먼 산·바다가 실제 부산 항공/드론 사진처럼 보이게. 비행 계산·건물 재질은 건드리지 않음.

## 어디에 있나
| 파일 | 하는 일 |
|---|---|
| `unreal/GyroSim/Content/Python/atmos_look.py` | 모든 값 (해·대기·안개·후처리·땅 재질 파라미터). Play 때 Python 으로 적용 — `FlightMap.umap` 은 안 바꿈 |
| `sim_client.py` (2곳) | `apply_look` 끝에서 `atmos_look.apply` (화질 프리셋마다), `_vworld_ground` 에서 `atmos_look.apply_ground` (V-World 땅 재질) |
| `Scripts/ground_material.py` + `ground_look.hlsl` | `/Game/Materials/Ground/M_GyroGround` (Cesium 기본 재질 복사 + Custom 노드: 바다 수면 + 사진 색 맞춤), `MI_GyroGround` |
| `Scripts/atmos_shots.py` | 두 번째 에디터 화면 밖 전/후 촬영 (`-GyroSimAtmosShots -RenderOffscreen`, 서버 없이, 결과는 git 밖 `C:\GyroSimTiles\shots\atmos`) |

끄기: 환경변수 `GYROSIM_ATMOS=off` → 맵 원래 값 + Cesium 기본 땅 재질 (전/후 비교용).

## 바꾼 것과 이유
(값은 `atmos_look.py` 가 기준. 아래 숫자는 11-10 확정값.)

- **해 방향**: 방위 215° (남서), 고도 42° (봄·가을 오후 2시쯤). 원래 맵은 방위 325° (북서) 38° — 한국에서 해가 그 높이로 북서쪽에 있을 수 없고,
  V-World 정사영상은 한낮에 찍어 그림자가 북쪽으로 구워져 있어서, 해를 남쪽에 두면 3D 건물 그림자와 사진 그림자 방향이 맞는다.
  해 세기 10 lux 는 그대로 (노출이 이 값에 맞춰져 있음 — 하늘/해 밝기 비는 Sky Atmosphere 가 물리적으로 정하므로 절대값은 결과에 영향 없음).
- **연무 (Mie 산란)**: 원래 엔진 기본 0.004/km × 1.3 = 맑은 공기 (가시거리 300 km 넘음) → 먼 산이 가까운 것처럼 또렷했다.
  한국 에어로졸 광학두께 ~0.3, 부산 낮 가시거리 대개 15–25 km (Koschmieder: 가시거리 = 3.912 / 소산계수).
  사진의 먼 능선 대비(σL*)에 맞춰 녹색 채널 0.065/km (+ Rayleigh 0.013, 지상 가시거리 ~45 km, 높이 1.2 km 로 옅어짐) 로 정함.
  색은 Ångström 지수 ~1.3 (도시·해안 에어로졸: 빨강:초록:파랑 = 0.76 : 1 : 1.34) 에서 사진 비교로 조금 더 푸르게 0.45 : 0.70 : 1.
  흡수는 작게 (0.002, 단일산란 알베도 ~0.97), 위상 비대칭 g 0.6 (엔진 0.8, 측정 에어로졸 0.6–0.7) — 0.8 / 흡수 9 % 로는
  해를 등진 쪽 지평선이 모든 실사진보다 어둡고 회색이었다 (sweep run5: f/g/h/i 비교, 표는 비교 페이지).
- **바다**: DEM 에서 바다는 정확히 해발 0 m (지오이드는 부산 안에서 28.99–29.42 m 만 변함) → 재질이 높이로 바다를 찾아
  어두운 물 색 + 하늘 반사(물 F0 = 0.02 → Specular 0.25) + 바람 물결 노멀 3단(먼 곳은 작은 물결 대신 거칠기 증가 = 햇빛 반짝임이 넓어짐).
  V-World 사진의 바다는 타일마다 청록/파랑이 달라 이음매가 보이고 채도가 높았다 (사용자 지적). 밝은 화소(배·방파제)와 회색·갈색 화소(DEM 이 0 m 로 눌러버린 바위섬)는 땅으로 남김.
- **땅 사진 색**: 그대로 (채도·대비 1.0). 0.85 / 0.92 는 가까운 곳이 "연하다" 는 지적과 반대 방향, ×1.08 은 실사진 채도를 넘었다 (근거리 C* 11.9 vs 실사진 8.9).
- **화면 색 보정**: 채도 ×1.06, 대비 ×1.08 (연무가 가까운 곳 대비도 조금 깎으므로 실사진 근거리 σL* 20–25 쪽으로 되돌림). 국소 노출(조종석용 realism 값)은 그대로.
- **카메라 느낌**: 모니터에서 톤매퍼 샤픈 0.5 (VR 0). 블룸·비네트·노출 속도는 realism v2 값 그대로 (모션블러·피사계심도 없음 — VR 안전).

## 숫자 (실사진 vs 전 vs 후)
비교 페이지와 같은 영역 통계 (L* 밝기, σL* 대비, C* 채도, h 색상각). 결과: 비교 페이지 표 참고.

## 출처
- Sky Atmosphere 속성 (Aerial Perspective View Distance Scale, Mie 는 하늘에만 / 공중원근은 거리 배율):
  https://dev.epicgames.com/documentation/unreal-engine/sky-atmosphere-component-properties-in-unreal-engine
- Sky Atmosphere 개요 (Mie = 연무·해 주변 후광, Rayleigh = 파란 하늘): https://dev.epicgames.com/documentation/unreal-engine/sky-atmosphere-component-in-unreal-engine
- 물리 단위 조명 / 노출: https://dev.epicgames.com/documentation/unreal-engine/using-physical-lighting-units-in-unreal-engine
- 해 120 000 lux / 하늘 20 % (포럼, 문서 인용): https://forums.unrealengine.com/t/lighting-ratio-using-physically-based-light-with-skyatmosphere/2651660
- Hillaire 2020, 대기 LUT 방식: https://blog.selfshadow.com/publications/s2020-shading-course/hillaire/s2020_pbs_hillaire_slides.pdf
- Cesium for Unreal 재질 편집 (재질 레이어 키, 레이어 스택): https://cesium.com/learn/unreal/unreal-edit-materials/
- 부산 AOD (위성 AOD, 부산항): https://www.mdpi.com/2073-4433/16/10/1123
- Koschmieder 가시거리 식, Ångström 지수: 대기광학 표준 (가정: 부산 대표값으로 1.3)

## 확인 안 된 것 (가정)
- 실사진 카메라 위치·방향은 사진에서 눈으로 추정. 사진마다 날씨·계절·카메라 보정이 다르다 (08, 09 는 필터 보정 — 수치 비교에서 뺐음).
- 1000–3000 m 비행 높이 실사진은 무료로 못 구함 → 비행 높이 장면은 눈으로만 판단.
- VR 화면은 이번에 찍지 않음 (VR 프리셋은 같은 대기 값 + 샤픈 0).

## 바다 · 해안 · 랜드마크 유리 (11-10 2차)
- **바다** (`atmos_look.SEA_NEW` → `MI_GyroGround`; `GYROSIM_SEA_LOOK=0` = `MI_GyroGround_Sea0` = 11-09 값): 깊은 물색 (0.030, 0.085, 0.165),
  물결 세기 0.12 → 0.2 (해면 기울기 분산 ≈ 0.003 + 0.00512·U, Cox & Munk 1954 → 풍속 5 m/s 에서 rms ~10°; 0.12 는 3–7° 라 먼 바다가 흐린 지평선만 비췄다).
  같은 시점 측정 (sRGB): 광안대교 뒤 마린시티 (64, 85, 102) → (44, 80, 114), 사진 (40, 89, 141). 태종대 120 m 는 1차 (11, 50, 112) 가 사진 청록 (54, 115, 120) 보다
  너무 짙어 2차에서 줄임 → (21, 59, 104). 얕은 물 쪽 사진색 섞기 (ShallowMix 0.4) 는 유지.
  이전 랜드마크 비교 페이지의 짙은 청록 바다는 촬영 때 바다 재질이 꺼져 있었던 것 (`GYROSIM_LSHOT_ATMOS` 기본 0) — Play 화면 문제가 아니었다.
- **마린시티 흰 둔덕**: Copernicus GLO-30 는 표면 모델이라 해안 바로 앞 아파트가 15–28 m 언덕으로 들어가 있었다 (35.1542 N 129.1450 E 27.7 m, 옆 산책로 4–6 m).
  `sim/terrain_coastfix.py`: 바다에서 2.5 칸 안, 7×7 이웃 중앙값보다 6 m 이상 높고, GIS 건물(AL_D010 부산)이 8 m 안에 있는 칸 (+ 붙은 칸) 74개 → 중앙값.
  지형 타일 188개 재생성 (원본 `*.terrain.pre_coastfix`). 이기대·오륙도·태종대 같은 자연 절벽은 건물이 없어 안 바뀜.
  **남은 일**: `proc/dem_N35E128/129.npy` 는 서버가 열고 있어 (memory map) 못 씀 → 서버를 끈 상태에서 `python -I sim/terrain_coastfix.py --apply` 한 번 더
  (그 전까지 JSBSim 지형 높이는 수정 전 값, 해당 칸 최대 ~18 m 차이).
- **랜드마크 유리** (`Scripts/landmarks_material.py` + `landmarks_glass.hlsl` → `/Game/Landmarks/MI_GyroLandmark`, `landmarks_look.GLASS`; `GYROSIM_LM_GLASS=0` = Cesium 기본):
  glb 의 유리판 (metallic 0.5–0.6 / roughness 0.07–0.1) 과 틀 (0.1 / 0.55) 사이 값인 화소만 유리로 봄. 거칠기 0.03 (+판마다 0–0.05), 판마다 ±15 % / 층마다 ±10 % 밝기,
  판 기울기 최대 0.8° + 판 안 볼록 0.4°, 틀은 ×0.75 알루미늄. 1차 (몸체 ×0.45, metallic 0.7) 는 사진보다 어두웠다 (제니스 공중 (62, 73, 89) vs 사진 (93, 116, 144)) → ×0.8 / 0.6.
- **GPU** (landmarks_shots startfpschart, 1080p 화소 환산, 같은 세션 전→후 3회): marine_air 4.25 / 4.18 / 4.19 → 4.17 / 4.19 / 4.20 ms, haeundae_overview 4.15 / 4.06 / 4.05 → 4.05 / 4.06 / 4.07 ms (차이 없음).
- 지면 세부 무늬 (`ground_look.hlsl`, `GYROSIM_GROUND_SHARP=0` = 끔): 150 / 500 / 1500 m 에서 선명도 지표 변화 0–2 % (실행 간 차이 수준), GPU 차이 없음 (3.62 → 3.63, 3.69 → 3.60 ms).
