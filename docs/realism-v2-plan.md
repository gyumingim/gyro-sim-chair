# 사실감 v2 계획 — 하늘·해·구름·캐노피 유리·노출 (1단계: 스크립트만, 아직 실행 안 함)

만든 날: 2026-11-05 · 담당: 사실감 v2 에이전트 · 상태: **스크립트 작성·커밋, 언리얼 미실행** (에디터가 열려 있어 사용자가 비행 중)
코드: `unreal/GyroSim/Scripts/realism_v2.py`(새 파일), `build_level.py`(호출 6줄), `realism_shots.py`(v1/v2 같은 세션 비교, 화면 밖 촬영, 종료).
앞선 작업(바꾸지 않고 이어감): `docs/unreal-realism-guide.md`, `docs/cockpit-realism-spec.md`, 커밋 504d4e2·02a155c·889390a·5209af9.
표기: **[확인됨]** 공식 문서, **[커뮤니티]**, **추정** = 측정 안 함. 모든 GPU ms 는 **추정** (2단계에서 잼).

---

## 0. 결론 먼저

- 가장 큰 차이 5개: ① 위쪽 하늘이 **옅고 청록빛**(사진은 더 짙은 군청), ② 구름이 **솜처럼 흐릿**(사진은 가장자리 또렷·바닥 어두움), ③ 캐노피 유리가 **없는 것처럼 보임**(반사·색·해 쪽 뿌연 빛 없음), ④ 해를 볼 때 **눈부심(glare) 없음**, ⑤ 바다·땅 사진이 **너무 원색**(V-World 정사영상 그대로; 반사·연무 없음).
- v2 는 ①~④ 를 값·재질로 고친다. ⑤ 는 Cesium 재질을 건드려야 해 2단계 조사로 미룸.
- VR 비용: VR 프로필은 렌즈 효과 없이 **거의 0 ~ +0.1 ms (추정)**, 구름 조기 종료로 일부 상쇄. 모니터 프로필은 Convolution 블룸 때문에 **+0.5~1.5 ms (추정)** — 120 fps 상한(8.3 ms) 안.
- 끄는 법: 빌드 때 `GYROSIM_REALISM_V2=0` → 순수 v1 레벨. 실행 중 `realism_v2.STATE["on"]=False` 후 프리셋 다시 적용 → v1 값.

---

## 1. 차이 목록 (우리 그림 vs 실제 사진)

우리: `C:\GyroSimTiles\shots\busan\busan_cockpit_300m_to_seomyeon.png`(이하 **B300**), `busan_rkpk_runway_cockpit.png`(**BRW**).
사진: 세션 scratchpad `page/cockpit/` 의 c01(KC-135 급유, F-16 캐노피), c10(F-15, 높은 고도), c14(F/A-18 고고도), c23(Gripen 해질녘 HUD·해), c24(Gripen HUD 유리), c25(Gripen 아퀴레이리 접근), c34(T-50 편대, 한국 남해 섬). 출처·라이선스는 `scripts/meta.json`.
숫자는 영역 평균(PIL, HSV) — 측정 스크립트 `C:\Users\a3162\AppData\Local\Temp\claude\b2ff6dea35ed22b8\92940a45-822d-4f2e-9a4d-643a3bbb683f\scratchpad\stats.py` (세션 임시 폴더 — 2단계에서 저장소로 옮길 것). 사진은 카메라 보정·편광 필터가 섞였을 수 있음(**가정**: 사진 색 = 눈 색이 아님). 그래서 목표는 "사진 범위 안쪽" 이지 사진 값 그대로가 아님.

| # | 차이 | 근거 (영역 값) | v2 에서 |
|---|---|---|---|
| 1.1 | **위쪽 하늘이 옅고 청록** | B300 위: 색상 210°, 채도 0.33, 밝기 0.73 / BRW 0.39·0.66 ↔ c25 222°·0.62·0.63, c34 220°·0.47·0.53, c14 217°·0.46·0.65, c10 223°·0.50·0.55 | 하늘만 어둡고 푸르게(`sky_luminance_factor`) |
| 1.2 | 지평선 흰 띠는 비슷 | B300 지평선 채도 0.03 밝기 0.84 ↔ c34 0.12·0.60(더 어둡고 약간 푸른 회색) | 위 1.1 로 같이 조금 내려감. 대기 원근(1.1)·Mie(×1.3)는 5209af9 의 일부러 정한 값이라 **유지** |
| 1.3 | **구름이 솜·안개처럼 흐릿**, 바닥이 밝음, 땅에 구름 그림자가 잘 안 보임 | B300/BRW 구름 가장자리가 넓게 번짐 ↔ c34·c14: 또렷한 가장자리, 평평하고 어두운 바닥 | 밀도 0.045→0.07, SkyLight 구름 AO, 구름 그림자 맵 범위 150→60 km |
| 1.4 | **캐노피 유리가 안 보임** (긁힘 반짝임은 해 쪽만) | B300/BRW 앞 유리에 아무 반사 없음 ↔ c01(하늘·기체가 유리에 비침, 색 띤 유리), c10(유리 가장자리 반사·붉은 테 반사), c14(유리 위 하늘 반사·긁힘) | 새 재질 `M_CkCanopyV2`: 프레넬 하늘 반사 + 실내 쪽 반사는 어둡게 + 약한 따뜻한 색 + 해 쪽 넓은 뿌연 빛 |
| 1.5 | **해 눈부심 없음** | 우리 그림에 해가 없음(해는 왼쪽 앞 38° 위) — `realism_shots` 의 `sun` 시점으로 확인 필요 ↔ c23: 해 둘레 큰 번짐·별 모양, 유리 긁힘이 해를 중심으로 빛남 | 모니터: Convolution 블룸(에너지 보존 번짐), 약한 렌즈 플레어. VR: 렌즈 효과 없음 |
| 1.6 | **바다가 원색 청록** | B300 바다: 197°·채도 0.68 ↔ c34 바다: 212~224°·채도 0.08~0.20 (연무 + 하늘 반사) | **v2 에 없음** → 2단계 조사(4장) |
| 1.7 | 도시·땅 사진이 평평하고 밝음 (정사영상에 구운 그늘, 반사 없음) | B300 가까운 도시 밝기 0.55, 대비 큼 ↔ c25 들판은 더 짙음 | **v2 에 없음** → 2단계 |
| 1.8 | 조종석 안 그림자 부드러움 | 두 그림에서 조종석 안이 거의 안 보임 → 판단 못 함 | 해 각도만 0.5357° (엔진 기본). 나머지는 2단계 `lookdown/left/right` 그림 보고 |
| 1.9 | 노출 | 바깥 밝기는 사진 범위 안. 조종석 쪽은 5209af9 에서 일부러 밝힘 | 노출 바이어스·범위 **유지**, 밝아지는 속도만 느리게(2 스톱/초) |

---

## 2. 바꾼 것 (값은 `realism_v2.py` 에 한곳)

| 항목 | v1 | v2 (공통) | 모니터 | VR | 기대 효과 | GPU (추정) | 근거 |
|---|---|---|---|---|---|---|---|
| 해 각지름 `light_source_angle` | 0.53 | **0.5357** | | | 거의 같음(엔진 기본값으로 맞춤) | 0 | Sky Atmosphere 문서: 해 0.545° [확인됨] |
| 하늘 밝기 `sky_luminance_factor` | (1,1,1) | **(0.80, 0.86, 1.0)** | | | 위쪽 하늘 약 −0.3 EV, 더 푸르게. 땅·조종석 직접광은 그대로 | 0 | SkyAtmosphere 의 Art Direction 값 [확인됨: 속성 존재] |
| 구름 밀도 `Cloud_GlobalDensity` (MI_Clouds) | 0.045 | **0.07** | | | 가장자리 또렷, 바닥 어둡게, 자기 그림자 대비↑. 배치(덮임 −0.22, 크기 110 = 사용자 고른 C안)는 유지 | ≈0 (밀도가 높으면 조기 종료가 빨라 오히려 약간 쌀 수 있음, 추정) | Volumetric Cloud 문서: 투과율 임계 아래면 추적 중단 [확인됨] |
| SkyLight 구름 AO `cloud_ambient_occlusion` | 끔 | **켬** (세기 1, 범위 60 km, 조리개 0.05) | | | 구름 아래·구름 그늘의 하늘빛이 줄어 땅·구름 바닥이 어두워짐 | +0.05 (2D 맵 1장) | 같은 문서 Sky Light 절 [확인됨] |
| 구름 그림자 맵 범위 `cloud_shadow_extent` | 150 km(기본) | **60 km** | | | 같은 해상도로 약 2.5배 촘촘 → 땅의 구름 그림자 또렷 | 0 | 같은 문서 Directional Light 절 [확인됨] |
| 노출 속도 `auto_exposure_speed_up/down` | 기본(3/1) | **2 / 1** | | | 조종석↔하늘 볼 때 출렁임 줄임 | 0 | 가이드 2.2 (추정 값) |
| 불투명 그림자를 공기에 `cast_shadows_on_atmosphere` | 끔 | | **켬** | 끔 | 구름 틈·기체 그림자가 공기 중 빛줄기로 | +0.1~0.3 | Sky Atmosphere 문서 [확인됨] |
| 블룸 방식 | Standard 0.35 | | **Convolution, 0.6** | Standard 0.3 | 해 원반 둘레 에너지 보존 번짐·별 모양 (c23 같은 눈부심) | 모니터 +0.5~1.5 | Epic Bloom 문서: Convolution 은 "에너지 보존", 비싸서 시네마틱·고사양용, 게임은 Standard 권장 [확인됨] |
| 렌즈 플레어 | 엔진 기본(덮어쓰지 않음) | | **0.12** | **0** | 모니터: 사진 느낌의 약한 고스트. VR: 눈에는 렌즈 고스트가 없음 | ≈0 | 가이드 2.6, Epic XR 성능 문서 [확인됨] |
| 구름 `stop_tracing_transmittance_threshold` | 0.005 | | 0.005 | **0.01** | VR 구름 비용 절약 | VR −0.2~0.5 | 가이드 #9 [확인됨] |
| 캐노피 재질 | `M_CkCanopy` (v1 그대로 둠) | **`M_CkCanopyV2`** | | | 아래 2.1 | +0.05~0.15 (큐브맵 2번, 유리 면적만) | 아래 |

### 2.1 캐노피 `M_CkCanopyV2` (v1 HLSL + 4가지)
v1 의 긁힘(해 쪽에서만 반짝, pow 40)·얼룩·해 쪽 halo·가장자리 프레넬은 **값 그대로**. 더한 것:
1. **하늘 반사**: 거울 방향으로 SkyLight 큐브맵(`SkyLightEnvMapSample`, 거칠기 0.08) × Schlick 프레넬(F0 0.05 = 폴리카보네이트 n≈1.585 계산값). 비침 비율만큼 뒤 배경이 줄어듦(실제 투과 ~90 %).
2. **실내 반사는 어둡게**: 거울 방향이 기체 기준 아래(조종석 통 안)를 향하면 반사 0 → 어두운 실내가 비치는 효과.
3. **약한 따뜻한 색 유리**: 배경 6 %를 "배경 추정(시선 방향 큐브맵) × (1, 0.9, 0.7)" 로 바꿈 = 곱셈 색 투과 근사. (일반 Translucent 는 곱셈 색을 못 하므로 쓴 꼼수. Thin Translucent 는 비용·VR 미확인이라 안 씀 — 가이드 2.5.)
4. **해 쪽 넓은 뿌연 빛(veil)**: pow(cos, 8) × 0.025 — 유리 전체가 해 근처에서 밝아지는 산란(c23).

Lumen "High Quality Translucency Reflections" 를 안 쓴 이유: 프로젝트 설정 + PPV 둘 다 필요, GPU 비용 증가, 앞 한 겹만([Epic Lumen GI·반사 문서](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine)) [확인됨], VR 프리셋은 Lumen 반사 대신 SSR, 우리 캐노피는 Unlit 이라 어차피 적용 안 됨. 큐브맵 꼼수는 두 프리셋 모두 같게 보이고 쌈.
빛줄기(Light shaft bloom)를 안 켠 이유: 화면 공간 방사 블러라 VR 에서 가짜처럼 보이고(추정), 모니터 눈부심은 Convolution 블룸이 맡음.

### 2.2 프로필이 어떻게 적용되나
- **빌드**(`build_level.py` → `realism_v2.build`): 캐노피 메시 기본 재질 = V2, `MI_Clouds` 밀도 0.07, 레벨의 하늘·빛·구름·PPV 에 **모니터 프로필**을 구워 넣음.
- **실행 중**: `realism_v2.install_hook(sim_client)` 가 `sim_client.apply_look` 을 감싸 프리셋(모니터/VR)이 바뀔 때마다 그 프로필을 적용.
  지금은 `realism_shots.py` 만 훅을 건다. **평소 비행(PIE)에는 훅이 없어서 VR 에서도 구운 모니터 값(Convolution 블룸·렌즈 플레어)이 쓰임** → VR 쓰기 전에 2단계에서 `Content/Python/sim_client.py` 의 `apply_look` 끝(또는 `init_unreal.py`)에 훅 한 줄을 넣어야 함 (이번 단계는 Content 수정 금지라 미룸).

---

## 3. 확인 방법 (에디터를 닫은 뒤, 창 안 띄움)

PowerShell, 저장소 루트에서. 에디터 창은 `realism_v2.keep_offscreen()`(busan_check 와 같은 방법)이 화면 밖으로 옮기고 포커스를 돌려줌.
**가정**: 실행 직후 아주 잠깐(파이썬이 뜨기 전) 창이 보일 수 있음 — busan_check 때와 같음.

```powershell
$R = "C:\Users\a3162\Desktop\gyro-sim-chair"; $UE = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64"
# 1) 서버 (창 없음)
$srv = Start-Process python -ArgumentList "sim\server.py" -WorkingDirectory $R -WindowStyle Hidden -PassThru
# 2) 레벨 다시 빌드 (헤드리스, ~수 분). v1 만 원하면 먼저 $env:GYROSIM_REALISM_V2 = "0"
& "$UE\UnrealEditor-Cmd.exe" "$R\unreal\GyroSim\GyroSim.uproject" -run=pythonscript -script="$R\unreal\GyroSim\Scripts\build_level.py" -unattended -nosplash -nullrhi
# 3) 같은 세션 v1/v2 그림 (모니터·VR × 7 시점 × 2) + GPU v2 / v1, 끝나면 에디터 종료
$env:GYROSIM_SHOTS_LABEL = "v2ab"; $env:GYROSIM_SHOTS_V2 = "off,on"; $env:GYROSIM_SHOTS_QUIT = "1"
$env:GYROSIM_FPS_LABEL = "v2ab"; $env:GYROSIM_FPS_V2_AB = "1"
Start-Process "$UE\UnrealEditor.exe" -ArgumentList "`"$R\unreal\GyroSim\GyroSim.uproject`" -GyroSimShots -nosplash" -Wait
Stop-Process -Id $srv.Id
```
결과: `unreal/GyroSim/Saved/verify/realism/v2ab/{monitor,vr}_{v1,v2}_{hud,lookdown,left,right,sun,rw_lookdown,rw_chase}.png`, `shots.json`(값 표 포함), `Saved/verify/fps_v2ab.json`(v2), `fps_v2ab_v1.json`(v1).

부산 그림 (지금 그림과 같은 시점, 다른 폴더에):
```powershell
$srv = Start-Process python -ArgumentList "sim\server.py","--start","rkpk" -WorkingDirectory $R -WindowStyle Hidden -PassThru
$env:GYROSIM_SHOTS_DIR = "C:\GyroSimTiles\shots\busan_v2"
Start-Process "$UE\UnrealEditor.exe" -ArgumentList "`"$R\unreal\GyroSim\GyroSim.uproject`" -GyroSimBusan -nosplash" -Wait
Stop-Process -Id $srv.Id
```

### 판정 기준 (같은 자·같은 영역으로)
- `scratchpad/stats.py` 의 같은 영역: 위쪽 하늘 색상 215~225°, 채도 0.42~0.6, 밝기 0.55~0.68 이면 통과. 지평선 띠는 여전히 흰색(채도 < 0.15).
- 구름: 가장자리 폭(눈), 바닥이 윗면보다 어두운가, `rw_lookdown`·부산 그림에서 땅의 구름 그림자.
- 캐노피: `sun`·`hud` 시점에서 유리가 "있다" 고 느껴지나, 반대로 사포처럼 뿌옇지 않나(DCS 불만 사례, 가이드 2.4).
- 해: `monitor_v2_sun` 에서 해 둘레 번짐이 화면을 하얗게 덮지 않나(Convolution 블룸 과다 시 0.6 → 0.3).
- 조종석 밝기: `lookdown/left/right` v1 vs v2 — 하늘을 어둡게 한 만큼 SkyLight 캡처도 약 10~15 % 어두워짐(**추정**). 너무 어두우면 `sky_luminance_factor` 를 (0.88, 0.92, 1.0) 로 완화.
- GPU: `fps_v2ab.json` vs `fps_v2ab_v1.json` 의 `gpu_ms` (cockpit_1080p / chase_1080p / cockpit_vr_pixels). 실행 간 잡음 ~0.2~0.3 ms (5209af9 기록). VR 픽셀 흉내에서 +0.3 ms 넘으면 VR 프로필 다시 봄.
- 섞인 변수: 다시 빌드하면 그 사이 다른 담당이 바꾼 조종석(`model_blender.py`)도 같이 들어감 → 깨끗한 비교는 **같은 세션 v1/v2 그림**(3번)이고, 부산 전/후 비교는 참고용.

---

## 3.1 실행 결과 (11-05 밤, 조종석 v3 와 같이 넣음)
- 레벨 다시 빌드 + VR 훅 (`sim_client.apply_look` 끝 `_realism_v2`) 넣음 → VR 프리셋 그림에 별무늬·렌즈 고스트 없음 확인.
- 고친 버그: `unreal.KismetMaterialLibrary` → `unreal.MaterialLibrary` (실행 중 구름 밀도 v1/v2 전환이 안 됐음), 헤드리스(-nullrhi) 빌드에선 명령 수가 늘 0 이라 캐노피가 상수 하늘색으로 잘못 내려가던 것.
- GPU ms (`Saved/verify/fps_before_old.json` / `fps_v2ab_v1.json` / `fps_v2ab.json`, 각 1회, 잡음 ~0.2~0.3): 조종석 1080p 3.71 (옛 조종석+v1) → 4.00 (새 조종석+v1) → 4.13 (새+v2); VR 픽셀 흉내 4.74 → 4.97 → 5.09.
- 남은 것: 바다·땅 색(1.6·1.7), 캐노피 하늘 반사는 그림에서 거의 안 보임(값 키울지 판단 필요), 해 쪽 하늘의 네모 경계선(v1 부터 있음).

## 3.2 캐노피 V3 시도 (11-06, 미완 — 화면에서 확인 안 됨)
- `realism_v2.py`: `M_CkCanopyV3` (SceneColor 로 뒤 장면을 받아 색 필터 = 금색 틴트, 비스듬할수록 진해짐, 프레넬 반사에 하늘 + 밝은 실내, 얼룩 안개). 기본은 **V2 그대로**, V3 은 `GYROSIM_CANOPY=v3` 로만 켬. `build_canopy_v3()` = 레벨 재빌드 없이 재질만 만듦.
- `realism_shots.py`: `GYROSIM_SHOTS_V2=on,v3` (V2 대 V3 같은 세션), `GYROSIM_SHOTS_DIR`, `GYROSIM_SHOTS_VIEWS`, `GYROSIM_FPS_STATES`, `GYROSIM_CANOPY_BUILD`, 진단용 `GYROSIM_CANOPY_DEBUG=1`(초록 유리).
- **문제**: 그림(C:\GyroSimTiles\shots\canopy_v3, canopy_v3b, canopy_v3c, canopy_dbg2)에서 V2 와 V3 가 같음. 초록 진단 재질도 화면에 안 나옴 → 캐노피 재질 변경이 PIE 화면에 반영되지 않음. 그러므로 11-05 의 "하늘 반사 거의 안 보임" 도 값 문제가 아니라 **캐노피 메시(F16_Glass)에 바꾼 재질이 실제로 그려지지 않는 문제**일 가능성 (추정).
  - 찾은 것: ① SceneColor 를 ComponentMask 에 연결하면 연결 실패 → 컴파일 실패(고침: 바로 연결). ② 헤드리스(-nullrhi) 빌드로 만든 V3 를 에디터가 열 때 "Custom missing input 1 (LP)" 컴파일 실패 로그 — 헤드리스로 만든 재질 연결이 저장되지 않았을 수 있음. ③ 컴파일 실패해도 `get_statistics` 는 명령 수 328 을 보고 → 명령 수로 성공 판정 불가.
  - 다음: 에디터 안에서 캐노피 액터의 실제 재질(`get_material`)과 `M_CkCanopyV3` 컴파일 오류 목록을 PIE 중에 로그로 찍기, 유리 앞에 보이는 긁힘이 정말 F16_Glass 에서 오는지 (메시 숨김 A/B) 확인.
- GPU (각 1회, 잡음 ~0.2 ms): 조종석 1080p V3 4.10 / V2 4.23, VR 픽셀 5.19 / 5.20 — V3 가 실제로 그려지지 않았을 수 있어 **비용 근거로 쓰지 말 것**.

### 3.3 캐노피 V3 원인 찾음 + 다시 만듦 (11-06 오후)
- **원인**: 유리 메시·컬링·숨김 문제 아님 (단순 초록 반투명 재질을 PIE 중 직접 넣으니 화면 전체가 초록, 밖에서 본 캐노피도 초록). 진짜 원인은 `realism_v2._canopy` 가 `EditorAssetLibrary.does_asset_exist` 로 V3 를 확인했는데, 이 함수는 **PIE 중에는 거부** ("The Editor is currently in a play mode") → False → 조용히 V2 로 되돌림. 그래서 11-06 오전의 모든 V3 / 초록 진단 촬영은 실제로 V2 였음. `_load()`(load_asset) 로 고침. 추가로 ① -nullrhi 커맨드릿으로 저장한 V3 는 "Custom missing input 1 (LP)" 로 깨짐 → V3 는 GUI 에디터에서 빌드(`GYROSIM_CANOPY_BUILD=1`). ② SceneColor 노드의 첫 입력은 기본이 화면 UV 라서 오프셋을 꽂으면 화면 전체가 한 색 → 입력 모드를 Offset Fraction 으로 바꿈. ③ F-16 유리는 안·밖 두 겹 → V3(장면 대체)에서는 경계에 각진 띠 → 바깥 겹은 `M_CkCanopyNone`(불투명도 0).
- **V3 내용**: 금색 틴트(경로 길이, 가장자리 더 진함), 이방성 긁힘(`T_CkCanopyAniso`: R 긁힘, BA 긁힘 방향; 해 방향과 수직인 긁힘만 빛남), 실내 반사(코밍 높이 평면: 글레어실드 검정, 콘솔 회색, 해 높이로 밝기), 가장자리 왜곡(SceneColor 오프셋 + 반사 흔들림), 옅은 얼룩. 해 근처 **육각형 렌즈 플레어**(`T_BokehHex`, 모니터 프리셋만, 강도 0.4) — V2 에도 적용, 그림에서 육각형 확인.
- **결과 (C:\GyroSimTiles\shots\canopy_v3h, 같은 세션 V2 대 V3)**: 정면·옆에서 금색 틴트 보임, HUD 잘 읽힘, 띠 없음. **문제**: V3 에서 해가 작은 점으로 줄고 블룸·플레어·긁힘 반짝임이 사라짐 (SceneColor 로 다시 그린 값에서 해의 HDR 밝기가 잘리는 것으로 추정, 확인 안 됨). → **기본은 V2 유지**, V3 는 `GYROSIM_CANOPY=v3` 로만.
- GPU (각 1회, 잡음 ~0.2 ms, fps_canopy_v3g*.json): 조종석 1080p V3 4.15 / V2 4.19 ms, VR 픽셀 5.41 / 5.15 ms.
- 다음: V3 에서 해 HDR 유지 (해 방향 픽셀은 SceneColor 대신 원래 장면을 통과시키기 = 불투명도<1 섞기, 또는 Thin Translucent 셰이딩 모델로 바꾸기), 긁힘 Gain / AnisoPow 재조정 후 V3 기본 전환 검토.

### 3.4 캐노피 V3 = 기본 (11-06 저녁)
- 해 HDR 잃던 원인: SceneColor 로 뒤 장면을 다시 그리면 해의 밝기가 잘림 (11-06 canopy_v3h: 해가 점, 블룸·플레어 없음). → **Thin Translucent 셰이딩 모델**로 바꿈: 뒤 장면에 투과색을 곱하는 방식이라 HDR 그대로 (해 블룸·육각 플레어 살아남, canopy_v3r).
- Thin Translucent 함정 (UE 5.8): 불투명도 = 표면 덮임 비율. 1 이면 뒤가 검게 됨, 0 이면 뒤는 보이지만 Emissive 가 0 이 됨 → 반사·긁힘·얼룩은 바깥 겹(같은 곡면)에 **가산(Additive) 재질 `M_CkCanopyV3Fx`** 로 따로 그림. 재빌드 때 ThinTranslucent 출력 노드가 지워지지 않고 쌓여 컴파일 실패 → 경로로 찾아 지움. 텍스처·하늘빛 입력이 있는 Custom 노드를 투과 핀에 연결하면 투과 0 → 투과·굴절은 작은 Custom 노드로 분리.
- 값: 금색 TintAmt 0.30 / PathMax 3.0 / TintCol (1, .85, .58) — 정면(수직으로 볼 때)은 거의 투명, 비스듬한 앞유리·가장자리에서 호박색. 긁힘 Gain 4 (절대값), AnisoPow 6, GlintPow 10: 해 쪽에서 가는 원호가 반짝임. 실내 반사 LitAbs 8: 옆 유리에서 아주 옅게 (거의 안 보임 — 더 키우면 각진 넓은 면으로 보여서 약하게 둠). 가장자리 굴절 Dist 0.02.
- 기본 V3 (`GYROSIM_CANOPY=v2` 로 되돌림). F16_Glass 메시 기본 재질은 `realism_v2.set_glass_asset()` (GUI 에디터).
- GPU (각 1회, 잡음 ~0.2 ms, fps_canopy_v3q*.json, 같은 세션): 조종석 1080p V3 4.33 / V2 4.33 ms, VR 픽셀 V3 5.90 / V2 5.42 ms (+0.5 ms, Thin Translucent 의 픽셀당 조명 비용으로 추정).

## 4. 2단계로 미룬 것 / 위험

- **VR 훅**(2.2): `sim_client.apply_look` 끝에 `realism_v2.apply_profile(name, world)` (Scripts 경로 추가) 또는 `init_unreal.py` 에서 `install_hook`. 이것 전에는 VR 에서 모니터 값이 쓰임.
- **바다·땅 색**(1.6, 1.7): Cesium 타일셋 재질을 우리 인스턴스로 바꿔 채도·감마 조정, 물 반사(물 마스크가 없어 색 기반 추정 필요) — Cesium 기본 재질의 파라미터를 에디터에서 먼저 확인해야 함.
- **높이 안개를 대기가 몰게**: 프로젝트 설정 "Support Sky Atmosphere Affecting Height Fog" + 안개 색 검정 (Sky Atmosphere 문서 [확인됨]). Config 변경·재시작 필요라 이번엔 안 함. 지금 안개 색은 고정 파란 회색.
- **캐노피 컴파일 실패 대비**: `SkyLightEnvMapSample` 이 Unlit 반투명에서 안 되면 픽셀 명령 수 0 일 때 상수 하늘색으로 다시 만듦. 다만 컴파일 실패가 0 으로 보고되는지는 **확인 안 됨** → 로그 `M_CkCanopyV2 compiled` 와 그림으로 확인.
- **화면 밖 실행 중 백그라운드 감속**: `keep_offscreen` 이 에디터 "Use Less CPU when in Background"(`throttle_cpu_when_not_foreground`)를 잠시 끄고 끝에 되돌림. 속성 이름은 **확인 안 됨**(실패하면 로그만 남음 → fps 수치가 낮게 나올 수 있음).
- Convolution 블룸이 장면을 어둡게 한다는 커뮤니티 보고 있음 [커뮤니티] → 그림으로 확인, 이상하면 모니터도 Standard.

## 5. 참고
- [Epic: Sky Atmosphere](https://dev.epicgames.com/documentation/en-us/unreal-engine/sky-atmosphere-component-in-unreal-engine) — 해 120,000 lux·0.545°, Multiscattering 1, Mie 이방성 0.8, Height Fog Contribution, Cast Shadow on Atmosphere, 품질 cvar.
- [Epic: Volumetric Cloud Component Properties](https://dev.epicgames.com/documentation/unreal-engine/volumetric-cloud-component-properties-in-unreal-engine) — Stop Tracing Transmittance Threshold, Cloud Shadow Extent, Sky Light Cloud Ambient Occlusion(Strength/Extent/Aperture), 다중산란 옥타브·Ground Contribution 비용.
- [Epic: Bloom](https://dev.epicgames.com/documentation/en-us/unreal-engine/bloom-in-unreal-engine) — Standard vs Convolution(에너지 보존, 비쌈, Buffer 크면 더 비쌈).
- [Epic: Lumen GI and Reflections](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine) — 반투명 앞 한 겹 고품질 반사, 프로젝트 설정 필요, 비용 증가.
- [Epic: Convolution Bloom Settings (Python)](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/ConvolutionBloomSettings) — 파라미터 이름.
- 나머지(노출, 그림자, VR 렌즈 효과, Lumen VR 위험)는 `docs/unreal-realism-guide.md` 출처 그대로.
