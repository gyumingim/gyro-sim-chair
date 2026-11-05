# 언리얼을 "진짜처럼" 보이게 하는 법 — 우리 조종석(VR 90 fps)에 맞춘 정리

만든 날: 2026-11-05 · 조사 담당(웹 조사 + 읽기 전용, `unreal/`·`sim/` 안 건드림)
먼저 읽을 것: `docs/cockpit-realism-spec.md`(실물 F-16 사진과의 차이·고칠 목록). 이 문서는 그 스펙을 반복하지 않고,
"사람들이 언리얼을 사진처럼 만드는 일반 방법" 을 우리 상황(UE 5.8, 콘텐츠 전용·에디터 Python, PC VR 90 fps + 모니터 모드)에 맞춰 고른 것이다.

표기: **[확인됨]** = Epic/제조사 공식 문서에 있음, **[커뮤니티]** = 포럼·블로그(검증 안 됨), **추정** = 내 계산·짐작(측정 안 함).
GPU ms 는 전부 **추정**이다. 지금 조종석 VR 픽셀 수 흉내 측정이 약 5.0 ms(구름 포함, `docs/sim-progress-2026-11-05.md`, 실제 헤드셋 아님)이고 90 Hz 예산은 11.1 ms.

---

## 0. 결론 먼저

**사진 같은 느낌의 대부분은 "비싼 기능" 이 아니라 공짜에 가까운 세 가지에서 온다: ① 틈·모서리의 어둠(구운 AO + 접촉 그림자), ② 빛의 대비(채움 빛 줄이기, 노출을 바깥에 맞춤), ③ 표면의 불완전함(거칠기 얼룩·모서리 닳음·베벨).**
VR 에서는 여기에 ④ **선명함**(흐린 TAA/TSR 은 "가짜 같음" 보다 더 거슬림)과 ⑤ **눈속임 렌즈 효과를 끄는 것**이 추가된다.

먼저 알아야 할 위험 하나: **우리 설정(Deferred + Lumen GI/반사 + VSM + TSR + Instanced Stereo)은 Epic 이 VR 에서 "실험적, 공식 지원 아님" 이라고 한 조합이다.**
Epic: "Nanite and Lumen on XR are experimental and not officially supported … PC with the Deferred Renderer and DX12" ([Epic, Nanite and Lumen for XR, 5.8 문서](https://dev.epicgames.com/documentation/unreal-engine/nanite-and-lumen-for-xr-in-unreal-engine)) **[확인됨]**.
Varjo 는 Lumen 스테레오에서 RTX 4090 으로 약 30~60 fps 를 예상한다고 썼다([Varjo UE5 권장 설정](https://developer.varjo.com/docs/v3.10.3/unreal/ue5/unreal5-recommended-settings), 옛 버전 문서) **[확인됨, 단 옛 버전]**.
Lumen + Instanced Stereo 에서 한쪽 눈 반사가 깜빡이는 보고도 있다([UE 포럼](https://forums.unrealengine.com/t/instanced-stereo-in-vr-problems-also-screen-mirroring-issue/2630133)) **[커뮤니티]**.
→ 그래서 **0번 일 = 실제 헤드셋에서 렌더 경로 3개를 같은 조건으로 재기**(아래 표의 0). 이 결과에 따라 1~10 의 예산이 정해진다.

### 우리 프로젝트 할 일 TOP 10 (VR 에서 "사실감 이득 ÷ GPU 비용" 순)

| # | 할 일 | 구체 값 | 적용 방법 | GPU (추정) |
|---|---|---|---|---|
| 0 | **렌더 경로 측정 (먼저)** | A 지금(Lumen High) / B **Lumen Lite**(`sg.GlobalIlluminationQuality=1` → Irradiance Final Gather `r.Lumen.FinalGatherMethod 0`, 반사는 SSR) / C GI 없음(`r.DynamicGlobalIlluminationMethod=0`, `r.ReflectionMethod=2` SSR) + SkyLight + 구운 AO. 각각 실제 헤드셋에서 GPU ms·한쪽 눈 깜빡임 확인 | `DefaultEngine.ini` 또는 실행 중 콘솔(`sg.*` 는 즉시 바뀜). `measure_fps.py` 로 같은 시점·같은 프리셋 | B 는 A 의 약 절반 (Epic 주장 "2배 빠름"), C 는 A 보다 1~3 ms 싸게 **추정** |
| 1 | **AO·곡률(cavity) 굽기** | Blender Cycles AO 거리 5~10 cm + 아주 짧은(1~2 cm) cavity. Epic 권장대로 **BaseColor 와 Specular(0.5) 둘 다에 곱함** | Blender Python(굽기) + 재질 인스턴스 텍스처 파라미터 | ≈0.05 ms |
| 2 | **깊이 있는 디테일은 진짜 모양으로** (베벨, 나사, 판 틈) | 모서리 베벨 2~4 mm. 깊이 수 mm 이상(판 틈, 나사 머리, 스위치 테)은 노멀맵 말고 메시 | Blender Python | 삼각형 +10~20 %, ≈0 ms |
| 3 | **빛 대비 되찾기** | 채움 점광원 `CK_FILL_CD` 1.6 → 0~0.5. 태양 `contact_shadow_length` 0.03~0.1. 큰 구조물 그림자 켜기. Local Exposure `shadow_contrast_scale` 0.75 → 0.9, `highlight_contrast_scale` 0.85 유지(Epic 권장 0.6~1), `local_exposure_blurred_luminance_blend` 0.5, `detail_strength` 1 | 에디터 Python(`set_editor_property`) | +0.1~0.3 ms |
| 4 | **재질 값 바로잡기 + 거칠기 얼룩** | 비금속 BaseColor sRGB 30~240(선형 ≈0.012~0.87). `CK_Black` 0.012 선형(sRGB≈28)은 바닥 아래 → 0.015~0.02. Metallic 은 0/1 만, Specular 0.5 고정. 거칠기는 단색 대신 얼룩 마스크로 ±0.1~0.2 변화, 손 닿는 곳(스로틀·스틱·문턱)은 더 매끈 | 재질 인스턴스 파라미터 + `make_textures.py` 로 만든 얼룩/지문 텍스처 | ≈0 ms (텍스처 1~2장) |
| 5 | **캐노피 유리 한 겹 + 긁힘 반짝임** | 스펙 P0 그대로(`docs/cockpit-realism-spec.md` 4장). 추가: 유리는 **한 겹만**(겹치면 두 번째 층 반사 품질이 떨어짐), Thin Translucent 는 착색 유리용이고 비용이 더 들 수 있어 지금의 Translucent + Surface ForwardShading 유지 권장 | 재질 그래프(Python `MaterialEditingLibrary` 가능하나 손이 많음) | 0.2~0.4 ms |
| 6 | **공기(대기 원근·안개)** | SkyAtmosphere `aerial_pespective_view_distance_scale` **0.6 → 1.0~1.5**(지금은 기본보다 공기가 얇음), `mie_scattering_scale` 조금 올려 지평선 흰 띠, 높이 안개는 "Support Sky Atmosphere Affecting Height Fog" 켜고 안개 색 검정 → 대기가 안개를 몰게 함 | 에디터 Python + 프로젝트 설정 1개 | +0.05~0.2 ms |
| 7 | **VR 에서 렌즈 효과 끄기 / 모니터는 따로** | VR: 모션블러 0, DOF 0, 색수차(`scene_fringe_intensity`) 0, 필름 그레인 0, 렌즈 플레어 0, **비네트 0**(헤드셋 렌즈가 이미 가장자리를 어둡게 함 — 추정), 블룸 0.2~0.35. 모니터: 비네트 0.2~0.3, 그레인 0~0.1 | PostProcessVolume 2개(VR/모니터) 또는 런타임에 값 바꾸기 | 0 또는 절약 |
| 8 | **선명함(해상도·AA·포비티드)** | TSR 100 % 유지 + `vr.PixelDensity` 1.0 → 여유 되는 만큼 1.1~1.3. 고정 포비티드(VRS) `vr.VRS.HMDFixedFoveationLevel` 1~2 로 가장자리 비용을 줄여 중앙 해상도에 씀(DLSS 와는 같이 못 씀) | `DefaultEngine.ini`/콘솔 | 포비티드로 절약, 픽셀 밀도로 지출 |
| 9 | **구름 비용 줄이기(남는 ms 를 위로 돌림)** | `stop_tracing_transmittance_threshold` 0.005 → 0.01~0.02, 다중산란 옥타브 1, Ground Contribution 끔, 구름 아래 비행이 많으면 Ray March Volume Shadow 끄고 그림자맵 사용 | 에디터 Python | 0.3~1 ms 절약 **추정** |
| 10 | **노출: 비율이 맞으면 단위는 그대로** | 지금 태양 10 lux(실물 120,000 lux, Epic 권장). 대기·SkyLight 는 태양에 비례하므로 **바깥 비율은 이미 맞음**. 고칠 것은 **화면·HUD 의 자체 발광 밝기 비율**: 실물 하늘 대비 MFD 가 훨씬 어두움 → HDR(Eye Adaptation) 시각화의 휘도계로 "지평선 하늘 : MFD : HUD 기호" 비율을 재서 맞춤. 자동노출 범위는 지금처럼 좁게(약 2 스톱) | 재질 인스턴스 Emissive 배율 + Python | 0 ms |

비용 합계: 1~7 은 대략 +0.4~1.2 ms, 9 로 0.3~1 ms 를 벌어 상쇄 → **총 +0.5 ms 안팎이 목표 (추정)**. 0 의 결과에 따라 B(Lumen Lite)로 가면 2 ms 넘게 여유가 더 생길 수 있음(추정).

**하지 않을 것 (VR 90 fps 에서 비싸거나 해로움):** 하드웨어 레이트레이싱, Lumen 고품질 반투명 반사의 무측정 켜기, MegaLights(조명 수십 개짜리 장면용 — 우리는 태양 1개), Nanite 로 조종석 바꾸기, 시차 차폐 맵(POM), 모션블러·DOF·색수차, Fab/Megascans(Epic 계정 필요 — 계정 만들지 않음).

---

## 1. 우리에게 특별한 점 세 가지 (일반 조언을 그대로 쓰면 안 되는 이유)

1. **조종석은 태양에 대해 계속 돈다.** 비행기가 선회하면 해 방향이 바뀌므로 **빛을 통째로 굽는 방식(GPU Lightmass 라이트맵)은 못 쓴다** — 굽는 건 빛 방향과 무관한 **AO·곡률뿐**.
   DCS 도 조종석 AO 를 텍스처에 구워 넣는다(RoughMet 텍스처의 빨강 채널 = AO, 초록 = 거칠기, 파랑 = 금속; [DCS 포럼 PBR 변환 가이드](https://forum.dcs.world/topic/164331-converting-model-to-pbr-w-roughmet-maps-roughness-metal-guide), [2012 스레드: 조종석은 정적이라 구운 AO 에 크게 의존](https://forum.dcs.world/topic/75326-enable-ambient-occlusion/)) **[커뮤니티]**.
   MSFS 도 조종석·기체 AO 굽기 문서가 따로 있다([MSFS 2024 SDK: Ambient Occlusion](https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/airframe/ambient-occlusion/)) **[확인됨: 문서 존재]**.
2. **보는 거리 30~80 cm, 두 눈.** 스테레오에서는 노멀맵의 "가짜 깊이" 가 들통난다. 깊이가 보이는 디테일은 메시로, 아주 작은 것만 노멀맵으로([Polycount: VR 에서 베벨 vs 노멀맵](https://polycount.com/discussion/185509/bevel-or-use-normal-maps-in-vr), [UE 포럼](https://forums.unrealengine.com/t/normal-maps-tessellation-and-vr/360837)) **[커뮤니티]**.
3. **글씨를 읽어야 한다.** 흐린 AA 는 사실감보다 먼저 쓸모를 깎는다. MSFS VR 가이드들도 "작은 계기 글씨가 중요하면 TAA 100 %" 를 권한다([Fly Away Simulation VR 가이드](https://flyawaysimulation.com/ask/answers/best-vr-settings-msfs-2024/)) **[커뮤니티]**.

---

## 2. 주제별 참고

### 2.1 렌더 경로 (Forward vs Deferred, Lumen, VR)
- **Forward + MSAA = VR 의 전통적 답.** Meta(2026-04 갱신)는 PC VR 에도 Forward 를 권하고, Lumen·Nanite 는 Deferred 가 필요하다고 명시([Meta: Unreal Forward Renderer](https://developers.meta.com/horizon/documentation/unreal/unreal-forward-renderer/)) **[확인됨]**.
  Epic 도 Forward 가 "더 빠른 기본" 이고 AA 선택지가 낫다고 씀([Epic: Forward Shading Renderer](https://dev.epicgames.com/documentation/en-us/unreal-engine/forward-shading-renderer-in-unreal-engine)) **[확인됨]**. Robo Recall 에서 Forward 가 22 % 빨랐다(12.3 → 9.6 ms, GTX 970, 오래된 1건)([UE 4.27 Forward Renderer 문서](https://docs.unrealengine.com/4.27/TestingAndOptimization/PerformanceAndProfiling/ForwardRenderer)) **[옛 자료, 검색 요약으로 확인]**.
  - 우리에게: Forward 로 가면 **Lumen·VSM(포럼 보고상 Forward 미지원)·SSR·SSAO 일부를 잃는다**(5.1 시절 포럼 답변 — 검색 요약으로만 확인, 스레드 특정 못 함) **[커뮤니티, 확인 필요]**. 조종석이 태양을 따라 도는 우리 장면에서 GI 없이 SkyLight + 구운 AO 만으로 충분할지가 핵심 질문 → 0번 측정의 C 안을 Forward 로도 한 번 재 볼 가치 있음. 렌더러 전환은 **엔진 재시작 + 셰이더 재컴파일**이 필요.
- **Lumen 품질 단계.** Epic: 단계를 하나 내리면 비용이 약 절반. Medium GI = Irradiance Final Gather(`r.Lumen.FinalGatherMethod 0`), Medium 반사 = Lumen 반사 끄고 SSR([Epic: Lumen Performance Guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-performance-guide-for-unreal-engine)) **[확인됨]**.
  UE 5.8 의 **Lumen Lite(베타)** 가 이 Medium 경로로, "Lumen High 의 2배 빠름", PC 지원([UE 5.8 Release Notes](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-8-release-notes), [Guru3D](https://www.guru3d.com/story/unreal-engine-58-debuts-lumen-lite-and-productionready-megalights/), [PC Gamer](https://pcgamer.com/software/unreal-engine-5-8-launches-with-improved-terrain-and-vegetation-tools-a-lumen-lite-option-for-faster-global-illumination-and-for-the-times-we-now-live-in-an-open-standard-plugin-for-llm-systems/)) **[확인됨]**. VR 지원 여부는 문서에 없음 **[확인 필요]**.
- **비용 줄이는 Lumen 콘솔 변수** (Epic 성능 가이드): `r.Lumen.Reflections.DownsampleFactor 2`, `r.Lumen.Reflections.MaxRoughnessToTraceClamp`(기본 0.4 위는 싼 근사), `r.Lumen.ScreenProbeGather.DownsampleFactor`(간격↑ = 싸고 흐림), `r.Lumen.Reflections.Allow=0`(SSR 로 대체, Series S 에서 약 1 ms) **[확인됨]**.
- **Lumen 은 DFAO 를 대신한다**(Lumen GI 문서) — 즉 Lumen 을 끄면(C 안) Movable SkyLight 그림자는 메시 거리장 AO 에 의존([Epic: Lumen GI and Reflections](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine)) **[확인됨]**. 우리는 `r.GenerateMeshDistanceFields=True` 이미 켜짐.
- **MegaLights**: 5.8 에서 정식(Production Ready)([UE 5.8 Release Notes](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-8-release-notes)) **[확인됨]**. 하지만 "그림자 지는 광원이 아주 많은" 장면용이고 Deferred 전용, 5.5 시절 VR 한쪽 눈 깨짐 보고([UE 포럼](https://forums.unrealengine.com/t/megalights-feedback-thread/2051575?page=2)) **[커뮤니티]** → **우리는 안 씀**.
- **실제 군용·훈련 시뮬레이터 사례**: Epic·Varjo·Brunner·Meta Immersive Synthetics 의 Project Antoinette(UE 기반, Eurofighter, 6DOF 모션, 시선추적 포비티드)([Varjo 블로그](https://varjo.com/blog/creating-a-photoreal-accurate-and-real-time-flight-simulator-introducing-project-antoinette)) — 렌더 설정 수치는 공개 안 됨. 그들도 강조한 건 "계기 글씨가 읽혀야 함" 과 "높은 프레임(멀미 방지)" **[확인됨]**.

### 2.2 빛
- **물리 단위.** Directional Light = 럭스(lx), SkyLight = cd/m²([Epic: Physical Lighting Units](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-physical-lighting-units-in-unreal-engine)). Sky Atmosphere 문서: 천정의 해 **120,000 lux**, 지름 0.545°, 흰 면 총 약 150,000 lux 중 하늘 몫 약 20 %, 다중산란 1([Epic: Sky Atmosphere](https://dev.epicgames.com/documentation/en-us/unreal-engine/sky-atmosphere-component-in-unreal-engine)) **[확인됨]**.
  - 우리: 태양 10 lux, 노출 EV100 ≈ 2(`build_level.py`). 대기·실시간 SkyLight 캡처가 태양에 비례하므로 **바깥 장면 비율은 물리값과 같다 (추정: 산란이 선형이므로)**. 물리값(120,000 lux, EV100 ≈ 14~15)으로 바꾸면 모든 발광 재질(HUD·MFD·라벨)을 다시 맞춰야 하므로 **바꾸지 않는 것을 권장**. 대신 발광 밝기를 같은 비율로 맞춘다(TOP 10 #10).
  - 참고 환산: 입사광 E = 2.5 × 2^EV100 → 120,000 lux ≈ EV100 15.5 (계산, [UE 포럼 환산 논의](https://forums.unrealengine.com/t/lighting-exposure-and-intensity-units-confusion/211375)) **[계산]**.
- **자동노출.** 최소·최대 EV100 이 같으면 자동노출 꺼짐. Manual 모드는 카메라 ISO/셔터/조리개 사용. 권장값: Low Percent 70~80, High 80~95, Local Exposure Highlight/Shadow Contrast 0.6~1, Blurred Luminance Blend 0.4~0.6, Detail Strength 1. 그리고 **"Lumen GI 를 쓸 때는 Local Exposure 를 항상 설정하라"**([Epic: Auto Exposure](https://dev.epicgames.com/documentation/en-us/unreal-engine/auto-exposure-in-unreal-engine)) **[확인됨]**.
  - 우리: 범위 약 2 스톱(EV 0.5~2.5)으로 좁게 둔 것은 좋음(아래를 봐도 하늘이 안 날아감). 실물 조종석 영상처럼 "안은 어둡고 밖은 밝게" 가 맞다(스펙 2.2). VR 에서 노출이 머리 따라 출렁이면 어지러우므로 `auto_exposure_speed_up/down` 은 1~2 스톱/초 정도로 느리게 (추정).
  - 중앙 가중이 필요하면 Exposure Metering Mask 텍스처(같은 문서) **[확인됨]**.
- **그림자.** VSM 은 "Nanite 를 안 쓰면 잘 안 맞을 수 있다"(Epic)([Epic: Virtual Shadow Maps](https://dev.epicgames.com/documentation/en-us/unreal-engine/virtual-shadow-maps-in-unreal-engine)) **[확인됨]** — 우리는 Nanite 없이 VSM. 대안 CSM(`r.Shadow.Virtual.Enable=0`, 캐스케이드 3~4, 그림자 거리는 조종석 근처에 해상도가 몰리게 짧게)과 **0번 측정 때 같이 A/B** 할 것. 조종석 그림자 선명도가 떨어지면 VSM 유지.
  - **접촉 그림자**: 화면 공간, 길이는 화면 비율(1 = 화면 끝까지), 예시 0.1, 길수록 노이즈([Epic: Contact Shadows](https://dev.epicgames.com/documentation/en-us/unreal-engine/contact-shadows-in-unreal-engine)) **[확인됨]**. 나사·스위치 밑 틈을 살리는 가장 싼 방법. 화면 공간 효과라 두 눈에서 조금 다를 수 있음 — 길이를 짧게(0.03~0.1).
- **AO.** 화면 공간 AO 는 VR 에서 두 눈 차이를 만들 수 있다(Meta 문서: 화면 공간 효과는 스테레오 불일치로 불편할 수 있음)([Meta](https://developers.meta.com/horizon/documentation/unreal/unreal-forward-renderer/)) **[확인됨]** → **구운 AO 가 VR 의 정답**. Epic 도 cavity 맵을 BaseColor·Specular 에 곱하라고 함([Epic: Physically Based Materials](https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine)) **[확인됨]**.
- **반사.** Epic 블로그: Lumen 이 반사 캡처·평면 반사·SSR 을 대체([Epic Tech Blog: Lumen](https://www.unrealengine.com/en-US/tech-blog/unreal-engine-5-goes-all-in-on-dynamic-global-illumination-with-lumen)). 반투명 앞면만 고품질 반사, 뒤 층은 Radiance Cache(흐린 반사)([Lumen GI 문서](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine)) **[확인됨]**. 평면 반사(Planar)는 장면을 한 번 더 그리므로 VR 에서 금지 (추정).

### 2.3 톤매핑·색
- UE 의 Filmic(ACES 계열) 톤매퍼: Film 섹션의 Slope·Toe·Shoulder 로 곡선 조절([Epic: Color Grading and the Filmic Tonemapper](https://dev.epicgames.com/documentation/unreal-engine/color-grading-and-the-filmic-tonemapper-in-unreal-engine)) **[확인됨]**. 기본값 그대로가 대체로 가장 사실적; 채도를 올리는 "보기 좋은" 그레이딩은 오히려 게임처럼 보이게 한다 (커뮤니티 통념, **추정**).
- 실물 영상 기준(스펙 1장): 바깥 하늘은 거의 흰색 근처, 조종석 그늘은 거의 검정. Toe 를 올려 검정을 들어 올리지 말 것.
- AgX·Khronos Neutral 같은 다른 톤매퍼는 유료 플러그인(Fab)이라 제외([UE 포럼 AgX](https://forums.unrealengine.com/t/hideout-studio-agx-tone-mappers/2726108)) **[커뮤니티]**.

### 2.4 재질
- **값 범위.** Epic 측정표: 숯 0.02, 새 아스팔트 0.02, 흙 0.13, 풀 0.21, 새 콘크리트 0.51, 새 눈 0.81(선형). Metallic 은 0 또는 1, Specular 0.5(≈4 %)가 거의 모든 재질에 맞음, 표면 변화는 Specular 말고 **Roughness 맵**으로([Epic: Physically Based Materials](https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine)) **[확인됨]**.
  Allegorithmic(Substance) 가이드 계열: 비금속 sRGB 30(관대)~50(엄격) 이상, 240 이하([PBR Guide Vol.2 사본](https://www.scribd.com/document/413439897/286277128-PBR-Guide-Vol-2), [RenderHub](https://www.renderhub.com/3d-tools/pbr-albedo-reflectance-picker)) **[커뮤니티 사본]**.
  - 우리: `CK_Paint` 0.040, `CK_Paint2` 0.026, `CK_Black` 0.012(선형). 마지막 것은 sRGB ≈ 28 로 바닥 아래(계산) → 0.015~0.02 권장. 무광 검정 FS 37038 은 원래 매우 어두우니 그 이상 올리진 않음.
- **불완전함이 사실감.** "너무 깨끗하면 가짜" — 모서리 노이즈, 얼룩 데칼, 유리 지문 같은 작은 흠([UE 포럼 Tips for life-like visualizations](https://forums.unrealengine.com/t/tips-for-creating-life-like-visualizations/48954), [Blender Guru: Achieving Photorealism](https://www.blenderguru.com/posts/achieving-photorealism-in-blender)) **[커뮤니티]**. MSFS SDK 도 조종석에 나이·사용에 맞는 먼지·긁힘·마모, 창 주변 때를 넣으라고 함([MSFS 2024: Cockpit Textures and Materials](https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/cockpit/textures/cockpit-textures-and-materials/index.md)) **[확인됨]**.
  - 단, 과하면 역효과: DCS 이용자들이 "사포로 닦은 캐노피" 같은 과한 긁힘에 불만([DCS 포럼](https://forum.dcs.world/topic/176124-canopy-crazingreflections-are-breaking-the-gameexperience/)) **[커뮤니티]** → 긁힘은 태양 쪽에서만, 세기는 슬라이더로.
- **모서리 닳음**: 구운 곡률 맵 × 노이즈 → 페인트 아래 금속(BaseColor 밝은 회색, Metallic 1, Roughness 0.35~0.5). 레이어 하나를 재질 함수로 만들고 인스턴스 파라미터 `WearAmount` 로 조절. 스펙 P0 와 같은 굽기에서 나옴.
- **텍셀 밀도**: 조종석 전체를 **같은 밀도**로(다르면 "가까이서 매우 티 남" — MSFS SDK, 위 링크) **[확인됨]**. VR 근거리 정해진 숫자는 못 찾음; 참고로 2048 px/1 m = 20.48 px/cm([Texel Density 참고](https://3dreference.notion.site/Texel-Density-f9ac9f58dd2d4d7d8baa0707f9447ef6)) **[커뮤니티]**. 눈~패널 50~70 cm 이면 20~40 px/cm 가 적당할 것으로 **추정** (헤드셋 약 20~25 px/도 가정).
- **텍스처 출처**: Poly Haven(CC0, 상업 사용·무표기 가능, 단 원작자 행세·재라이선스 금지)([Poly Haven License](https://polyhaven.com/license), [FAQ](https://polyhaven.com/faq)), ambientCG(CC0)([cinevva 정리](https://app.cinevva.com/guides/free-textures-hdris-materials)) — **계정 없이 다운로드 가능, 우리 `fetch_textures.py` 와 맞음**.
  Megascans 는 2025 년부터 Fab 에서 일부 무료·대부분 유료, 라이선스가 **Epic 계정에 묶임**([Epic 포럼 2025-03 Megascans update](https://forums.unrealengine.com/t/megascans-update-march-2025/2419561), [CG Channel](https://www.cgchannel.com/2024/10/epic-games-has-made-megascans-free-to-all-but-only-until-the-end-of-2024/)) **[확인됨]** → 계정 생성 금지이므로 **사용자가 직접 받지 않는 한 안 씀**. Substance Painter 도 유료 Adobe 계정 → 대신 Blender 굽기 + 우리 코드 생성 텍스처.
- **Nanite**: 조종석 수준의 다각형 수에서는 필요 없음. XR 에서 실험적이고 반투명 재질은 지원 안 함(Varjo 문서: 반투명 메시는 Nanite 끄기, Instanced Stereo 에서 Nanite 깜빡임 보고)([Varjo](https://developer.varjo.com/docs/v3.10.3/unreal/ue5/unreal5-recommended-settings)) **[확인됨, 옛 버전]**.
- **Substrate**: 5.7 에서 정식(production-ready) 보도([Unreal Source 5.7](https://unrealsource.com/d/unreal-engine-5-7-is-now-available)) **[커뮤니티 보도]**. 지금 재질을 옮길 이득이 작아 보류 (추정).

### 2.5 유리·캐노피·HUD 결합유리
- **Thin Translucent 셰이딩 모델**: "물리적으로 맞는 착색/색 유리, 정반사와 뒤 배경을 정확히" — Lighting Mode = Surface ForwardShading + `ThinTranslucentMaterialOutput` 노드 필요([Epic: Shading Models](https://dev.epicgames.com/documentation/en-us/unreal-engine/shading-models-in-unreal-engine), [Epic: Colored Translucent Shadows](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-colored-translucent-shadows-in-unreal-engine)) **[확인됨]**.
  - 우리 권장: 캐노피는 거의 무색이라 일반 Translucent + Surface ForwardShading(스펙 P0) 으로 충분. **HUD 결합유리(초록/금빛 코팅)** 는 색이 핵심이므로 Thin Translucent 를 시험해 볼 만함 — 면적이 작아 비용 작음(추정).
- **겹치는 유리 금지**: 반투명 앞면만 고품질 반사, 뒤 층은 흐린 반사([Lumen 문서](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine), [UE 포럼 stacked translucency](https://forums.unrealengine.com/t/lumen-reflections-look-incorrect-on-stacked-translucent-materials/2602058)) **[확인됨/커뮤니티]**. 캐노피 + MFD 앞 유리 + HUD 유리가 시선상 겹치면 두 번째부터 반사가 흐려짐 → MFD 앞 유리는 반투명 대신 **화면 재질 안에 반사(프레넬 × SkyLight 큐브맵)를 섞는** 방식이 싸고 안전 (추정).
- **긁힘은 해 쪽에서만**: 실물·DCS 모두 "긁힘이 햇빛을 받으면 하얗게 빛남"([DCS 포럼 canopy scratches](https://forum.dcs.world/topic/177380-canopy-scratches-illumination/)) **[커뮤니티]**. 실시간 기법 공식 문서는 못 찾음 — 스펙의 `pow(saturate(dot(R, L_sun)), 64)` 가짜 반짝임 방식은 **우리 설계(추정)**.
- MSFS 는 창에 먼지·긁힘·지문 레이어를 재질 기능으로 둔다([MSFS 2024: Windshield and Windows](https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/airframe/windshield-and-windows/)) **[확인됨: 문서 제목·목차 수준, 세부 수치 못 읽음]**.

### 2.6 카메라·후처리 (VR vs 모니터)
| 효과 | VR | 모니터 | 근거 |
|---|---|---|---|
| 모션블러 | 끔 | 끔(또는 아주 약하게) | Unity URP: VR 에서 모션블러·색수차·렌즈 왜곡 피하라([Unity 문서](https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal%408.1/manual/integration-with-post-processing.html)) **[확인됨, 타 엔진]** |
| 피사계심도(DOF) | 끔 | 끔(조종석은 전부 초점) | Unity 용어집([Post FX for VR](https://unity.com/glossary/post-fx-for-vr)) **[커뮤니티급]** |
| 색수차 | 끔 | 0~0.1 | 위 Unity 문서 |
| 렌즈 플레어 | 끔 | 0.1 이하 | Epic XR 성능 문서: 무거운 후처리(렌즈 플레어·SSR·TAA·SSAO·블룸)는 0 으로([Epic: XR Performance Features](https://dev.epicgames.com/documentation/en-us/unreal-engine/xr-performance-features-in-unreal-engine)) **[확인됨]** |
| 블룸 | 0.2~0.35 (태양·HUD 번짐에만) | 0.35~0.5 | 위 Epic 문서는 0 권장 — 우리는 해 번짐이 실물에 있으므로 낮게 유지(측정 후 판단) |
| 비네트 | 0 (추정: 헤드셋 렌즈가 이미 어둡게 함) | 0.2~0.3 | 사진 느낌에는 약간의 비네트·글레어가 도움(Richard Yot 의 후처리 강좌 인용, [BlenderNation](https://www.blendernation.com/2025/11/15/post-processing-for-photorealism-in-blender/) — 정지 이미지 기준) **[커뮤니티]** |
| 필름 그레인 | 끔(두 눈 다르면 거슬림, 추정) | 0~0.1 | 근거 약함 — 취향 |

- **모니터 시야각(FOV)**: 27인치 화면을 60 cm 에서 보면 실제 가로 시야 약 50° (계산: 2·atan(30/60)). 이 값이면 "실물 크기" 지만 좁아 답답함 → 비행 게임들은 70~90° 를 흔히 씀 (**추정, 출처 없음**). 초보 모드는 넓게, "실물 비례 보기" 를 옵션으로.
- 사진처럼 보이려면 "사진 지식(노출·ISO·셔터·렌즈)" 을 알라는 조언([80.lv, Pasquale Scionti 인용](https://80.lv/articles/tutorial-lighting-for-beginners-in-unreal-engine)) **[커뮤니티]**.

### 2.7 VR 전용
- **AA**: VR 에서 TAA 는 흐리고, MSAA 는 선명(단 Forward 전용)([UE 포럼 VR AA](https://forums.unrealengine.com/t/vr-anti-aliasing-nightmare-taa-vs-msaa-meta-quest-help-needed-video-attached/2371688)) **[커뮤니티]**. 5.6 에서 TSR + VR + DX12 시각 문제 보고([UE 포럼](https://forums.unrealengine.com/t/rendering-with-tsr-antialiasing-in-vr/2549080)) **[커뮤니티]** → 5.8 실제 헤드셋에서 꼭 확인.
- **해상도**: VR 은 `r.ScreenPercentage` 대신 `vr.PixelDensity`(1 = 헤드셋 이상 해상도, 픽셀 수 = 2×W×H×밀도²)([Epic 블로그 4.19 VR 해상도](https://www.unrealengine.com/blog/significant-changes-coming-to-vr-resolution-settings-in-4-19)) **[확인됨, 옛 자료]**. UE5 에서 일부 AA 와 안 먹는 보고([UE 포럼](https://forums.unrealengine.com/t/ue5-vr-resolution-limited/518585)) **[커뮤니티]**.
- **포비티드(VRS)**: `r.VRS.Enable`, `vr.VRS.HMDFixedFoveationLevel`, `vr.VRS.HMDFixedFoveationDynamic`; DX12 + VRS Tier 2 필요(RTX 5080 해당), **DLSS 와 같이 못 씀**, 시선추적 포비티드는 미지원(Epic 문서)([Epic: XR Performance Features](https://dev.epicgames.com/documentation/en-us/unreal-engine/xr-performance-features-in-unreal-engine)) **[확인됨]**. Meta: 포비티드는 Forward/Deferred 상관없이 동작([Meta](https://developers.meta.com/horizon/documentation/unreal/unreal-forward-renderer/)) **[확인됨]**.
- **DLSS/DLAA in VR**: NVIDIA 문서끼리 VR 지원 여부가 엇갈리고, DLSS 4 플러그인 + UE 5.5 VR 한쪽 눈 검정 버그 보고([NVIDIA 포럼](https://forums.developer.nvidia.com/t/critical-dlss-4-bug-in-ue-5-5-for-vr/325433)) **[커뮤니티]**. 게다가 Fab 플러그인(계정) → **보류**.
- **Instanced Stereo**: 켜 두는 게 기본(Varjo, Epic), 켜고 끌 때 재시작·셰이더 재컴파일([Epic XR 문서](https://dev.epicgames.com/documentation/en-us/unreal-engine/xr-performance-features-in-unreal-engine)) **[확인됨]**. 한쪽 눈만 이상하면 끄고 비교(Epic 직원 조언, [UE 포럼](https://forums.unrealengine.com/t/instanced-stereo-in-vr-problems-also-screen-mirroring-issue/2630133)) **[커뮤니티]**.
- **다른 시뮬레이터가 하는 것**: MSFS VR — VR 전용 그래픽 프로필 따로, 렌더 배율 80~100 %, 글래스 콕핏 갱신률(CPU) 낮추기([Fly Away Simulation](https://flyawaysimulation.com/ask/answers/best-vr-settings-msfs-2024/), [MSFS 2024 RTX 5080 가이드](https://flyawaysimulation.com/ask/answers/best-msfs-2024-graphics-settings-rtx-5080/)) **[커뮤니티]**. 우리 MFD 렌더 타깃 갱신을 30 Hz 로 낮추는 것도 같은 아이디어 (추정 절약 0.1~0.3 ms, CPU/GPU).
  DCS — 조종석 AO 를 텍스처에 굽고 PBR(RoughMet) 사용(2.1절) **[커뮤니티]**.
- **90 fps 에서 너무 비싼 것 (우선 끄는 목록)**: Lumen 하드웨어 RT, Lumen 고품질 반투명 반사, 평면 반사, 볼류메트릭 포그(넓은 범위), 구름 높은 샘플 수, POM, Nanite+VSM 조합 실험, 2 이상 픽셀 밀도. (Epic 이 Lumen 을 "VR 두 눈 각각 렌더 → 최고급 GPU 에서도 목표 fps 어려움" 이라 경고, [Epic Nanite/Lumen XR](https://dev.epicgames.com/documentation/unreal-engine/nanite-and-lumen-for-xr-in-unreal-engine)) **[확인됨]**.

### 2.8 하늘·대기·구름 (비행용)
- **대기 원근(Aerial Perspective)**: 거리를 늘려 먼 곳을 더 뿌옇게. 우리 0.6 은 기본(1)보다 얇음 → 1.0~1.5. Mie 산란 = 먼지·연무, Mie 이방성 0.8(지구 기본) ~ 0.9(해 주변 후광 좁게). 높이 안개를 대기가 몰게: 프로젝트 설정 "Support Sky Atmosphere Affecting Height Fog" + 안개 Inscattering 색 검정 + `height_fog_contribution`([Epic: Sky Atmosphere](https://dev.epicgames.com/documentation/en-us/unreal-engine/sky-atmosphere-component-in-unreal-engine)) **[확인됨]**.
  - 품질 cvar(같은 문서): `r.SkyAtmosphere.FastSkyLUT.Width/Height` 256(구름 그림자 개선), `r.SkyAtmosphere.AerialPerspectiveLUT.Width`(메모리 급증 주의) **[확인됨]**.
- **해 원반**: 각지름 0.545°(Epic) — 우리 `light_source_angle` 0.53 과 같음 → 유지.
- **볼류메트릭 구름 비용**(Epic 컴포넌트 문서): 투과율 임계값 올리면 샘플 감소, Ray March Volume Shadow 끄면 그림자맵 사용(지상 시점에서 보통 충분, 덜 정확), 다중산란 옥타브는 1 이 최선, Ground Contribution 은 비용 추가, 샘플 상한 cvar `r.VolumetricCloud.ViewRaySampleCountMax` 등([Epic: Volumetric Cloud Component Properties](https://dev.epicgames.com/documentation/unreal-engine/volumetric-cloud-component-properties-in-unreal-engine)) **[확인됨]**.
- **VR 구름 버그 이력**: `r.VolumetricRenderTarget.Mode 1` 에서 오른쪽 눈에 구름이 메시 앞에 그려짐 — UE-269202, 5.6 에서 고침([Epic 이슈 트래커](https://issues.unrealengine.com/issue/UE-269202), [UE 포럼](https://forums.unrealengine.com/t/volumetric-cloud-render-appears-in-front-of-meshes-in-right-eye-vr/2500285)) **[확인됨]**. 우리는 5.8 이지만 헤드셋 첫 시험 때 오른쪽 눈 확인 항목에 넣을 것.
- **5.8 Fog Screen Space Scattering(실험적)**: 안개 다중산란 근사, 볼류메트릭 구름은 미지원([UE 5.8 Release Notes](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-8-release-notes)) **[확인됨]** → 실험적이고 VR 미확인이라 보류.

---

## 3. "왜 내 장면이 가짜 같지?" 점검표 (조종석용)

각 항목은 같은 스크린샷 4장(1, 1b, 4a, 6a) + 헤드셋에서 확인. 괄호는 근거.

1. 틈·모서리 아래가 충분히 어두운가? (구운 AO/cavity — Epic PBM 문서, DCS)
2. 모서리가 칼날처럼 각진가? → 베벨이 빛을 받아 얇은 밝은 선이 보여야 함 (Blender Guru, Polycount)
3. 모든 면이 같은 거칠기인가? → 손 닿는 곳은 반질, 나머지는 얼룩 (Epic: 변화는 Roughness 맵으로)
4. 검정이 너무 검거나(sRGB < 30) 흰색이 240 넘는가? (PBR 가이드)
5. 채움 빛·국소 노출이 그림자를 너무 들어 올리는가? (실물 영상: 그늘은 거의 검정 — 스펙 2.2)
6. 노출이 머리 돌릴 때마다 출렁이는가? (자동노출 범위·속도)
7. 지평선이 또렷한가? → 대기 원근이 먼 곳을 하얗게 (Sky Atmosphere 문서)
8. 유리가 "없는" 것처럼 보이는가, 아니면 반대로 사포처럼 과한가? (DCS 포럼 양쪽 불만)
9. VR 에서 글씨·선이 흐린가? (TAA/TSR 블러 — 사실감보다 먼저 고칠 것)
10. 한쪽 눈에만 보이는 차이(반사·구름·그림자 깜빡임)가 있는가? (Lumen·Instanced Stereo·화면 공간 효과)
11. 텍스처 선명도가 부품마다 다른가? (MSFS SDK: 텍셀 밀도 일정)
12. 렌즈 효과(색수차·DOF·모션블러)가 켜져 있는가? (VR 에서 끔)
13. 깊이가 보여야 할 디테일(나사·판 틈)이 노멀맵뿐인가? (VR 스테레오에서 납작해 보임)
14. 크기·비례가 맞는가? (VR 은 실제 크기가 그대로 느껴짐 — 스펙 3장 치수)

---

## 4. 에디터 Python 으로 되는 것 / 손으로 해야 하는 것

| 일 | Python(`build_level.py`·`ue_cockpit.py` 방식) | 손 작업 / 주의 |
|---|---|---|
| 콘솔 변수(r.*, sg.*, vr.*) | `unreal.SystemLibrary.execute_console_command(None, "r.X 1")`(실행 중), 영구는 `Config/DefaultEngine.ini` `[/Script/Engine.RendererSettings]` 편집 | 렌더러 전환(Forward, Instanced Stereo, VSM 켜기/끄기)은 **에디터 재시작 + 셰이더 재컴파일** |
| PostProcessVolume 값 | `ps.set_editor_property("scene_fringe_intensity", 0.0)` 등 (이미 쓰는 방식). 속성 이름은 `override_…` 짝 필요 | VR/모니터 두 프로필은 런타임(블루프린트 없이) 바꾸려면 sim_client 쪽 콘솔 명령 또는 볼륨 2개 + 우선순위 |
| 조명·대기·구름 컴포넌트 | `set_editor_property`(예: `contact_shadow_length`, `aerial_pespective_view_distance_scale`(철자 원문 그대로), `mie_scattering_scale`, `stop_tracing_transmittance_threshold`) | 일부 속성 이름은 버전마다 다름 → 실패 로그 확인(이미 try/except 패턴 있음) |
| 재질 인스턴스 값 | `MaterialEditingLibrary.set_material_instance_scalar/vector/texture_parameter_value` | — |
| 재질 그래프(새 노드) | `MaterialEditingLibrary.create_material_expression` + `connect_material_expressions` 로 가능 | 노드 많으면 손으로 만드는 게 빠를 수 있음. Thin Translucent 출력 노드는 직접 확인 필요 |
| AO·곡률 굽기, 베벨 | Blender Python(`model_blender.py`, Cycles bake) | 굽기 결과 눈으로 확인 |
| 텍스처 내려받기 | Poly Haven / ambientCG 는 계정 없이 URL 로 가능(`fetch_textures.py`) | Fab/Megascans·Substance 는 계정 필요 → 사용자 결정 |
| 노출 비율 재기 | — | 에디터 Show > Visualize > HDR(Eye Adaptation) 휘도계로 손으로 측정 |
| 헤드셋 확인(선명도·한쪽 눈 차이·멀미) | — | **반드시 사람 눈으로** |

---

## 5. 확인 못 한 것 / 가정
- UE 5.8 에서 Lumen Lite·TSR·VSM·볼류메트릭 구름의 **VR 스테레오 동작**: 공식 문서에 없음 **[확인 필요]**.
- 모든 GPU ms 값, 텍셀 밀도 20~40 px/cm, 노출 속도 1~2 스톱/초, 모니터 FOV, 비네트를 VR 에서 0 으로 하는 이유: **추정**.
- "태양 10 lux 여도 바깥 비율은 물리값과 같다" 는 대기 산란이 빛 세기에 선형이라는 가정에 기댄 **추정**(자동노출 범위가 맞으면 겉보기 같음).
- MSFS 창 재질 문서는 목차 수준만 읽힘(본문 수치 없음).
- 커뮤니티 VR 설정 가이드(Fly Away Simulation 등)는 한 사이트 위주라 신뢰도 낮음.
