# 캐노피 비침 (2026-11-13 보류 → 11-14 V5 기본 켬)

결론 (11-14): 물리 기반 반사 V5 를 **기본으로 켠다** (사용자 결정). 끄려면 룩 페이지 8768 의 '캐노피 반사' 체크를 푼다.
(11-13 에는 빼 두었다: 아래는 그때까지의 기록.)

## 지금 기본값 (view_fx.py)
- 투명한 무색 유리 (호박색 틴트 제거, 회색 막 제거: 안쪽 셸 = M_CkCanopyTrans, 1−F 투과만)
- 11-13 위쪽 회색 막 원인: 바깥 Fx 겹(V4)의 조종석 대용 형상 반사(ReflAmt 1)가 꺼지지 않은 채 남아 있었다. view_fx 에서 Fx 겹의 ReflAmt 를 0 으로 했다 (`GYROSIM_CANOPY_FXREFL=1` 이면 다시 켜짐).
  하늘 위 차이: 위쪽 보기 +49/255 → −2/255. 남은 −2~−5 는 안쪽 투과 겹의 Fresnel 감쇠(F0 0.05)다.
  진단과 그림: scratchpad canopy_curve/t15, t16, img/13·14.
- **11-14: V5 반사를 기본으로 켬 (사용자 결정).** `cr_on` 기본 1: view_fx.refl_live 의 값 없음 기본, tune_server START, tune_defaults.json.
  - 끄는 법: 룩 페이지 http://127.0.0.1:8768/ 의 '캐노피 반사' 체크 해제 (params.json 에 cr_on 0). 다시 켜려면 체크.
  - FlightMap 에 큐브 촬영 액터를 배치했다: SceneCaptureCube 'CanopyCube' (태그 CanopyCube), Aircraft 액터에 붙임, 상대 위치 (412, 0, 75) cm,
    회전 0, Movable, 대상 RT_CkCanopyInterior, 매 프레임·움직일 때 촬영 끔. 만든 스크립트: unreal/GyroSim/Scripts/canopy_cube_place.py
    (편집기 없이 commandlet, 다시 돌려도 같은 액터를 다시 씀). Play 마다 view_fx.interior_cube 가 이 액터를 찾아 한 번 굽는다
    (2048 + 밉, AircraftPart 부품만, 해 직사광·하늘·안개·구름 없음). 로그: `canopy cube: capture at the eye, show-only N physical parts`,
    10 초 뒤 `canopy cube: baked (SceneCaptureCube_0)`.
  - 굽는 때: Play 첫 틱에 구우면 유리에 크고 밝은 면들이 보였다 (11-14 FlightMap 화면 밖 A/B). 같은 세션에서 로딩 뒤 다시 구우면
    CockpitView 처럼 옅어졌다. 그래서 액터를 찾은 뒤 `GYROSIM_CANOPY_CUBE_DELAY` (기본 10) 초 뒤에 한 번 굽는다. 그 전에는 큐브 층 0.
    원인은 못 찾음 (첫 틱에 빛·노출이 아직 안 정해졌다는 것은 추정).
  - 확인 (11-14, 화면 밖 편집기 + 시뮬 서버, 해운대 350 m): 기본값으로 on=True, ReflAmt 1.9, CubeAmt 1, 오류 없음.
    그림: 세션 scratchpad canopy_cube_map/img/flight_*.png (켬) / flight_off_*.png (끔), 고치기 전 img/v4_before_fix/.
  - 백업 (세션 scratchpad canopy_cube_map/backup/): FlightMap.umap.before_cube (배치 전 맵), params.json.before,
    DefaultEngine.ini.with_rt (레이트레이싱 실험 설정). DefaultEngine.ini 는 실험 전 값(r.RayTracing·SkinCache·SM6 없음)으로 되돌렸다.
- 11-13 물리 기반 반사 V5 (scratchpad review/canopy_reflection_advice.md). (11-13 에는 기본 꺼짐이었다.)
  - 켜는 법: 룩 페이지 http://127.0.0.1:8768/ 의 '캐노피 반사' 체크, 또는 `GYROSIM_CANOPY_FXREFL=1`.
  - 셰이더 구성: 유리 두 면 Fresnel(ReflAmt 1.9) × (A 조종사 구 + B 해 받는 테두리 + C 실내 큐브 + D 바깥) + E 번쩍임.
  - A·B 는 지금 해 방향으로 실시간 음영을 넣는다.
  - C 는 해 직사광 없이 굽고, 보여 줄 부품만 지정하는 목록(진짜 부품만, 조종사·가상 표시·유리 제외)을 쓴다. 2048 + 밉.
  - 슬라이더: cr_on, cr_mult, cr_cube, cr_lit, cr_glint (1 = 물리값).
  - 큐브는 FlightMap 에 SceneCaptureCube(태그 CanopyCube)를 배치해야 시뮬에서 구워진다. 11-14 배치함 (위).
  - 4096 큐브는 불가: 편집기 빌드에서 엔진이 2048 로 제한한다.
  - 재질 백업: scratchpad canopy_curve/backup/uasset/M_CkCanopyV3Fx.174323.uasset (V4).
  - 그림: http://127.0.0.1:8814/ ⑤.
- 캐노피 메시 기본값은 F16_Glass_Fit 이다 (11-13 사용자 결정, `GYROSIM_CANOPY_SMOOTH` 기본 fit). `cc` 로 두면 옛 F16_Glass_Smooth, `0` 이면 원본을 쓴다.
- 실내 큐브 반사 끔 (GYROSIM_CANOPY_CUBE=0), 호(링) 끔 (GYROSIM_CANOPY_RINGS=0), 거울 셸 끔, 레이트레이싱 끔 (GYROSIM_CANOPY_RT=0)
- 거울 복제(canopy_ghost.py)는 따로 부르지 않으면 안 쓰임

## 해 본 것과 결과
| 방법 | 결과 |
|---|---|
| 실시간 큐브 (눈 위치, 256 px, 2초마다) | 평평한 그림을 덮은 듯, 흐릿 |
| 큐브 + 상자/구/타원체 시차 보정, 1024 px, 하늘 검게 구움 | 만화경 패턴 (오목 거울 접힘은 물리적으로 맞음 + 근사 오류 조각). 사용자: "반사 모양이 이상함" |
| Lumen SW / HW 레이트레이싱 front-layer | 100% 에선 정확히 휘어 비침, 평소 세기엔 희미. SM6 + r.RayTracing 필요 (DefaultEngine.ini 에 켜 둠, 기본은 안 씀) |
| 휜 거울 셸 (금속 1, 디더 불투명도) | 위쪽 하얗게 날아감, 섞으면 회색 막 + 점 노이즈 |
| 해석적 링 광원 (호) | 각진 메시에선 계단, 매끈한 메시에서도 거의 안 보임 |
| 거울 복제 (조종석 39개 부품, 평면 3장) | 흰 덩어리, 곡면 따라 안 휨 |

## 다시 할 때 참고
- c12 사진(F-16D 뒷좌석)의 큰 동심원 호는 복좌기 좌석 사이 후프 등 밝은 선이 비친 것 — 단좌에는 그 물체가 없음.
- 실제 반사율 약 5%: 어두운 하늘 쪽에서만 밝은 선 몇 줄이 보이는 정도. 세면 VR 에서 거슬린다는 불만이 흔함.
- 조사: 세션 scratchpad review/canopy_techniques.md, review/canopy_fable.md (MSFS 식 구운 실내 큐브맵 + 시차 보정 + Fresnel 덧셈이 표준).
- Play 월드에서 파이썬은 액터를 못 만듦 → 큐브 캡처·거울 복제는 FlightMap 에 미리 배치해야 함.
- 확인함 (11-13): 큐브 캡처 위치는 의도대로 (412, 0, 75) = 눈 (430, 0, 100) 보다 18 cm 뒤·25 cm 아래, 기체 회전 0 이라 월드 위치도 맞음.
  6면 그림에서 계기판이 "터널 끝에 작게" 보인 것은 디버그 상자 선의 원근 + 90° 화각 착시였음 (계기판 폭 약 33 %, 계산과 맞음). 버그 아님.
- **원인 확인 (11-13, 곡면 검사):** 캐노피 메시가 매끈한 곡선이 아님 — 원본 428 삼각형, 이웃 면 꺾임 평균 8.6°·p95 25°,
  단면이 지그재그. 지금 쓰는 F16_Glass_Smooth(단순 분할 + 법선 복사)는 줄무늬 시험에서 원본보다 더 조각남(만화경).
  해법: 원본 꼭짓점에 매끈한 곡면을 맞춰(r(x,φ) RBF 또는 초타원 단면 + 스플라인) 가장자리 2~3 cm 로 다시 메시
  (두 겹 합 1~2만 삼각형), 법선은 해석적으로, 안쪽 겹은 같은 곡면에서 띄우기, import 시 high precision tangent basis 켜기.
  Catmull-Clark 금지. 자료: scratchpad canopy_curve/ (img/08_bl_zebra_grid.png, mesh/ideal_1cm.obj, data/*.json).
  **정정 (11-13 검토 canopy_remesh_review1.md):**
  - "원본 꼭짓점이 매끈한 면에서 0.08 mm" 는 순환 논리로 나온 값이었다. 거의 보간하는 맞춤으로 잰 표본 내 잔차이기 때문이다.
    한 점씩 빼고 맞춰 보면(LOO) 중앙값이 1.1~1.9 mm 다. 꼭짓점 잡음은 0.5~1 mm 로 추정한다.
  - `mesh/ideal_1cm.obj` 는 이상면이 아니라 "평활을 약하게 한 기준면"이다. 앞 캐노피 면적의 29 % 가 −0.3 /m 보다 오목하다.
  - 원본 / Smooth 의 반사 방향 오차 절대값(중앙 2°, p95 5° 등)은 기준면 불확실성(법선 1~3.5°, 반사로는 그 2배) 안에 있다.
    "원본이 각지다", "Smooth 가 더 나쁘다" 는 결론은 기준면 없이도 성립한다.
- F16_Glass_Fit (11-13 v2, scratchpad canopy_curve/fitmesh2.py, verify2.py → data/verify2.json):
  - 앞 캐노피: 대칭 cubic RBF, smoothing 10000 (규칙: T4 를 통과하는 것 중 T5 도 통과하는 가장 작은 값).
  - 테두리: 원본 꺾은선에 정확히 고정하고, 6.5 cm 띠에서 차이를 0 으로 줄임.
  - 뒤 창: 원본 면을 2.5 cm 로 다시 나눈 것에 확산 법선을 붙임. 매끈한 모델은 T4·T5 를 함께 통과하지 못했다.
  - 11-13 부터 기본값이다. 안쪽 겹 간격은 테두리 6.5 cm 띠 안에서 6.28 mm → 1 mm 로 줄인다 (원본처럼 문턱에서 두 겹이 거의 만남).
  - 뒤 창 법선 확산 횟수는 25 로 고정했다.
  - T14 (오프스크린 UE 에서 원본 / Smooth / Fit 를 eye 4방향 + 문턱으로 찍음): 줄무늬가 Fit 에서 매끈하다. 결과는 scratchpad canopy_curve/t14, img/11·12.
  - 남은 것: 뒤 창 고름(T5·T11), 정수리선의 약한 물결(T6), 프레임 모서리 꺾임(테두리 3 cm 안). 반사를 다시 켤 때만 손볼 가치가 있다.
- CockpitView 편집기와 시뮬은 UDP 4220 을 같이 씀 → 동시에 켜지 말 것.
