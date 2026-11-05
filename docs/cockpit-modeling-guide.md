# 조종석 모델·텍스처·재질 품질 올리기 — 우리 스크립트 모델(Blender → UE)용

만든 날: 2026-11-05 · 조사 담당(웹 조사 + 읽기 전용 점검, `unreal/`·`sim/` 안 건드림)
먼저 읽을 것: `docs/cockpit-realism-spec.md`(실물과의 차이), `docs/unreal-realism-guide.md` + 사실 확인 `docs/unreal-realism-guide.check.md`(빛·렌더 설정).
이 문서는 그 둘이 다루지 않은 **"모델 자체와 텍스처·재질"** 만 다룬다.

표기: **[확인됨]** = 공식 문서(Blender·Epic·MSFS SDK) 또는 이 PC 에서 직접 돌려 봄, **[커뮤니티]** = 포럼·블로그, **추정** = 내 계산·짐작(측정 안 함).
계정 만들기 금지 조건 → Substance·Megascans/Fab·Quixel 은 쓰지 않는다. 전부 Blender(무료) + 우리 Python + CC0 텍스처.

---

## 0. 결론 먼저

**지금 조종석이 평평해 보이는 이유는 "기능이 없어서"가 아니라 "효과가 안 보일 만큼 약하거나, 면적의 92 % 에서 꺼져 있어서"다.**
`M_CkSurface` 에 cavity·모서리 닳음·그런지가 있지만 (1장 근거):

1. **면적의 92 % 에서 cavity/닳음이 꺼져 있다.** 정점색 마스크는 6 cm² 넘는 면에서 강제로 0.5(중립)다 (`model_blender.py` `to_object`, `big = calc_area() > 6e-4`).
   `ck_shell` 을 읽기 전용으로 재 보니 넓은 면 비율이 **0.92** 였다 (12.8 m² 중) **[확인됨: 이 PC 에서 FBX 측정]**. 판이 만나는 구석·글레어실드 밑 같은 "어두워야 할 곳" 은 전부 넓은 면이라 효과가 없다.
2. **정점 곡률은 AO 가 아니다.** 이웃 정점 방향만 보므로 "다른 물체에 가려진 구석" 을 모른다. VR 프리셋은 Lumen 이 꺼져 있어(SkyLight + 거리장 AO 뿐) 구석 그림자를 엔진도 못 만든다 (`unreal-realism-guide.check.md` 1번).
3. **변화 폭이 너무 작다.** 그런지는 albedo ×0.97~1.02, 거칠기 ×0.95~1.05 (`ue_cockpit.py:44-60`) — 거칠기 0.7 기준 ±0.035. 눈에 보이려면 ±0.1~0.2 가 필요 **[확인됨: Epic "변화는 Roughness 맵으로"]** + **추정**(폭).
4. **거의 모든 색이 검정에 가깝다.** `CK_Paint` 0.040, `CK_Black` 0.012, `CK_AntiGlare` 0.007 (선형). 검정에 곱하는 변화는 검정이다. 실물 F-16 통(tub)은 **FS 36231 Dark Gull Gray(중간 회색)** 이고 검정은 패널·콘솔 판뿐이다 (6장).
5. **표면 노멀이 완전히 매끈하다.** 단단한 면은 모두 `NormalAmt` 0 → 하이라이트가 장난감 플라스틱처럼 한 덩어리로 미끄러진다.
6. **눈에 띄는 큰 모서리(통 문턱·콘솔 위 테두리·글레어실드 끝)에 베벨이 없다**(작은 상자에만 있음). 빛 받는 얇은 선이 안 생긴다.

### 할 일 순위 (사실감 이득 ÷ (작업량 + VR 비용))

| # | 할 일 | 구체 값 | 작업량 | VR GPU (추정) |
|---|---|---|---|---|
| 1 | **색·거칠기 값 바로잡기** | 통·옆벽(`CK_Paint`) Tint 선형 **(0.15, 0.16, 0.16)** (FS 36231 근사), Rough 0.65. 패널 판 무광 검정 0.018, Rough 0.85. 글레어실드 0.012, Rough 0.95. 그런지 폭: 거칠기 **±0.15 절대값**, albedo ×0.85~1.10 | 반나절 (값만) | 0 |
| 2 | **AO·모서리·때 마스크를 텍스처로 굽기** (정점색 대체) | `ck_shell` 새 UV 채널(UV2) 자동 펼침 → Cycles 굽기 4096² 한 장, R=AO(거리 8 cm), G=모서리(Bevel 노드 반경 3 mm), B=때·손때(아래 7장). 약 8.6 px/cm | 1~2 일 | ≈0.05 ms, 텍스처 1장 (BC1 4096² ≈ 11 MB) |
| 3 | **큰 모서리 베벨** | Bevel 모디파이어 width **2.5 mm**, segments 2, limit ANGLE 30°, harden_normals, 마지막에 Weighted Normal(keep_sharp). 통 문턱·콘솔 테·글레어실드 끝·패널 테두리 | 반나절 | 삼각형 +10~20 % ≈ 0 ms |
| 4 | **세부 노멀(detail normal)** | 페인트: 아주 약한 오렌지필 + 미세 긁힘 노멀, 반복 5 cm, 세기 0.2~0.3. 천·가죽·양털·고무는 CC0 텍스처(5장) | 반나절 | ≈0.02~0.05 ms |
| 5 | **깊이 있는 디테일은 진짜 메시로** | 콘솔 판 고정 나사(Dzus) 지름 8~10 mm·높이 1.5 mm, 판 사이 틈 2~3 mm 깊이 3 mm, 문턱 레일 볼트 지름 8 mm 간격 4~5 cm | 1 일 | 삼각형 +10~20 k ≈ 0 ms |
| 6 | **트림 시트 + 그린 데칼**(스텐실·경고 줄무늬·명판) | `make_textures.py` 로 2048² 트림 1장(볼트 줄, 이음, 경첩, 고무 실링, 노랑/검정 줄무늬, 명판 글씨) + 높이→노멀 | 1 일 | ≈0.02 ms |
| 7 | **손 닿는 곳 닳음** | 스로틀 손잡이·스틱·문턱 위·좌우 콘솔 앞끝·발판 뒤꿈치 자리에 반경 8~15 cm 구 마스크 → B 채널 | 2 시간 | 0 |
| 8 | 좌석 천·양털·가죽 | CC0: Poly Haven `curly_teddy_natural`(양털 방석, 검게 착색), `fabric_leather_02`, ambientCG `Fabric061`, `Rubber004` | 반나절 | ≈0.02 ms |

1~4 만 해도 "검은 덩어리" → "칠한 금속" 으로 바뀔 것으로 **추정**. 합계 VR 비용 +0.1~0.2 ms (**추정**, `measure_fps.py` 로 같은 조건 전·후 측정 필요).
**하지 않을 것:** 서브디비전으로 매끈하게(삼각형 폭증, 이득 없음), 시차 차폐 맵(POM), 화면 공간 투사 데칼(DBuffer)을 대량으로, Substance·Megascans(계정 필요).

---

## 1. 왜 지금 평평한가 (코드 근거)

| 원인 | 근거(파일) | 고치는 방향 |
|---|---|---|
| cavity/닳음 마스크가 큰 면에서 0.5 고정 | `model_blender.py` `to_object` (`big = [f.calc_area() > 6e-4 ...]`, 큰 면은 `enc(0.5)`) | 텍스처 마스크(UV2)로 바꾸면 큰 면도 구석은 어둡고 가운데는 밝게 표현 가능 |
| 정점 곡률 = 국소 볼록함만 | 같은 함수 (`d.normalized().dot(v.normal)` 평균) | AO 굽기(가려짐) + Bevel 노드 굽기(모서리) 로 분리 |
| 정점색이 sRGB 두 번 인코딩되는 우회 | 같은 함수 주석(`flat 0.5 arrived as 0.886`) | 깨지기 쉬움 — 텍스처로 옮기면 사라짐 |
| 그런지 폭 ±2.5 %(albedo), ±5 %(거칠기 곱) | `ue_cockpit.py` `ck_master` (`0.97/1.02`, `0.95/1.05`) | 절대값 ±0.15 거칠기, albedo 0.85~1.10 |
| 닳음 색 0.22, 닳음 금속값 0.6 | `ck_master` `WearColor`, `WearMetal 0.6` | 금속은 0 또는 1(Epic). 칠 벗겨진 곳 = 알루미늄 (0.55, 0.56, 0.57), Metal 1, Rough 0.4 |
| 단단한 면 노멀맵 없음 | `CK_SLOTS` 에서 `NormalAmt` 는 Grip·Fabric·Webbing 만 | 세부 노멀 추가 |
| 색이 너무 어두움 | `CK_SLOTS` (`CK_Paint` 0.040 등) | 6장 실물 값 |
| 큰 모양에 베벨 없음 | `build_tub`(bm_loft, 베벨 없음), 패널 앞 테만 0.35 cm | Bevel 모디파이어 일괄 |

참고로 이미 잘 된 것: Weighted Normal 모디파이어(`keep_sharp`, weight 50), `set_sharp_from_angle(38°)`, FBX 노멀 가져오기(`FBXNIM_IMPORT_NORMALS`), UE 라이트맵 UV 자동 생성 끔(`generate_lightmap_u_vs False` — 우리 UV2 를 덮어쓰지 않음), 패널 글씨 아틀라스 20~32 px/cm(`layout.py` `PX_*`).

---

## 2. 모델링 (스크립트로 하는 하드서피스)

### 2.1 베벨
- Blender 4.5 Bevel 모디파이어 속성(이 PC 의 4.5.15 에서 직접 조회) **[확인됨]**: `width`(기본 0.1), `segments`(1), `limit_method` NONE/ANGLE/WEIGHT/VGROUP, `angle_limit`(30°), `offset_type` OFFSET/WIDTH/DEPTH/PERCENT/ABSOLUTE, `profile` 0.5, `harden_normals`, `miter_outer`, `use_clamp_overlap`.
- **크기 계산 (추정)**: 눈~판 60 cm, 헤드셋 약 20 px/도 → 1 px ≈ 0.5 mm. 하이라이트 선이 3~6 px 보이려면 베벨 **1.5~3 mm**. 지금 작은 부품 베벨(0.2~1.2 mm 대부분)은 OK, 큰 모양에 2.5 mm 를 추가.
- **세그먼트**: 2 (둥근 하이라이트, 삼각형 부담 작음). 실린더·노브는 3.
- **노멀**: 베벨 + Weighted Normal 을 **스택 맨 마지막** 에 (뒤에 오는 모디파이어가 노멀을 깨뜨림) — Blender GSoC 개발자 노트 **[커뮤니티]**, harden normals 는 과거 버그가 있었음(T58113, 해결됨) **[확인됨: 버그 트래커]**.
  우리 코드는 이미 `WEIGHTED_NORMAL` 을 붙이고 `use_mesh_modifiers=True` 로 내보내므로, 베벨 모디파이어를 그 **앞** 에 넣으면 된다.
- 주의: Bevel 모디파이어 `width` 는 객체 단위다. 우리 메시는 내보내기 전에 cm→m (/100) 변환되므로 2.5 mm = `width=0.0025`.

### 2.2 진짜 메시 vs 노멀맵 (VR)
- Polycount 합의: **깊이가 보이는 디테일은 모델링, 아주 작은 것만 노멀맵** ("normal maps just cannot make up for the lack of depth") **[커뮤니티]**.
- **우리 숫자 (계산, 추정)**: 두 눈 간격 63 mm, 거리 60 cm 에서 깊이 차 Δ 가 만드는 시차 = 63·Δ/600² rad. 1 px(≈3 각분 = 0.00087 rad)에 닿으려면 Δ ≈ **5 mm**.
  → 깊이 **5 mm 이상**(판 틈, 스위치 테, 나사 머리 높이 합, 레일 단차) = 메시. **2 mm 이하**(페인트 결, 긁힘, 천 결, 작은 리벳) = 노멀맵. 사이 값은 옆모습(실루엣)이 보이면 메시.
- 나사 머리 1.5 mm 는 깊이로는 경계지만 **실루엣·작은 그림자·하이라이트** 가 생기므로 메시 권장 (개당 24~48 삼각형, 300개 ≈ 1만 삼각형).

### 2.3 서브디비전 vs 로우폴리 + 굽기
- 고폴리를 만들어 로우폴리에 노멀을 굽는 고전 방식 대신 **"미드폴리"(베벨된 메시 + 가중 노멀, 노멀 굽기 없음)** 가 요즘 흔하다 — 80.lv UE5 인터뷰("geometry changes … without the need to re-roll on a low poly and high poly mesh"), Polycount **[커뮤니티]**.
- 우리처럼 **치수를 코드로 계속 바꾸는** 모델에는 미드폴리가 맞다 (굽기 대상 고폴리를 따로 유지할 필요 없음). 노멀 굽기 대신 AO·모서리 마스크만 굽는다.
- `subsurf()` 는 손잡이처럼 유기적 모양에만.

### 2.4 삼각형 예산
- 지금 전체 약 3.7만 삼각형(`manifest.json` 합계: shell 23,166 + 움직이는 부품) **[확인됨: 파일]**.
- 참고: DCS 포럼(2013) 조종석 약 17만 삼각형 상한 언급, Sketchfab 실시간 여객기 조종석 7.2만 **[커뮤니티, 오래됨]**. RTX 5080 급에서 조종석 20~30만 삼각형은 부담이 작다 (**추정**). → **베벨·나사·틈으로 3~5 배 늘려도 괜찮음**. 측정 기준: `stat unit` / `measure_fps.py` 전·후.
- Nanite 는 쓰지 않는다(XR 실험적, 반투명 미지원 — 기존 가이드).

---

## 3. 텍스처 (Substance 없이)

### 3.1 Blender 굽기 — 이 PC 에서 확인한 것
이 PC 의 Blender 4.5.15 에서 `bpy.ops.object.bake` 인자를 조회하고, **지금의 `ck_shell.fbx` 로 실제 AO 굽기를 시험** 했다 (출력은 임시 폴더, 프로젝트 파일 안 건드림) **[확인됨]**:
- 인자: `type` ∈ COMBINED, **AO**, SHADOW, POSITION, NORMAL, UV, ROUGHNESS, **EMIT**, ENVIRONMENT, DIFFUSE, GLOSSY, TRANSMISSION · `margin`(16) · `margin_type` ADJACENT_FACES/EXTEND · `use_selected_to_active` · `cage_extrusion` · `max_ray_distance` · `target` IMAGE_TEXTURES/VERTEX_COLORS · `uv_layer` · `use_clear`.
- **곡률(curvature) 굽기 타입은 없다.** → 재질의 Emission 에 마스크를 연결하고 `type='EMIT'` 로 굽는다.
- 시험 결과: `uv.smart_project(angle_limit=66°, island_margin=0.002)` + `average_islands_scale` + `pack_islands` 0.1 초, **2048² AO 64 샘플 CPU 26.7 초**, UV 채움 58 %, 밀도 **4.3 px/cm**. 결과 이미지에서 콘솔 판 둘레·스위치 구멍·패널 구석이 제대로 어두워짐(눈으로 확인).
  → 4096² 면 약 **8.6 px/cm**, 굽기 약 2 분 (**추정**: 4배 픽셀).
- 굽기 규칙(Blender 매뉴얼): 각 재질에 **이미지 텍스처 노드를 만들고 active 로** 지정해야 그 이미지로 구워짐. AO 거리 = `scene.world.light_settings.distance`.

### 3.2 마스크 3종 (한 장에 채널로)
| 채널 | 무엇 | Blender 방법 | 값 |
|---|---|---|---|
| R | **AO**(구석·틈 어둠) | `bake(type='AO')` | 거리 0.08 m, 샘플 64~128 |
| G | **모서리**(볼록=밝게) | Emission = `1 - dot(Bevel노드 노멀, 실제 노멀)` 을 증폭. Bevel 노드는 **Cycles 전용**, 입력 Radius, Samples 기본 4 **[확인됨: Blender 매뉴얼]** | Radius 0.003 m, Samples 8, 증폭 ×8 후 0~1 자르기 (**추정**) |
| B | **때 + 손때** | Emission = AO 노드(거리 0.3 m, 넓은 어둠) × 높이 그라데이션(바닥 쪽 진하게) + 손 닿는 점 구 마스크(7장) | 7장 |

- Pointiness(Geometry 노드 출력)도 곡률을 주지만 **정점 단위·Cycles 전용** 이라 우리 로우폴리 큰 면에서는 지금 정점색과 같은 한계가 있다 **[확인됨: Blender 매뉴얼]** → Bevel 노드 방식이 텍셀 단위라 더 낫다.
- Geometry Nodes 의 Edge Angle 도 정점/모서리 단위 — 같은 한계.

### 3.3 절차적 그런지 (우리 코드)
- 지금 `T_CkGrunge` 1024² (노이즈 3 옥타브 + 긁힘 260 줄)는 좋은 출발점. 바꿀 것: **세기**(위 1번)와 **2 채널화** — R = 큰 얼룩(20~40 cm), G = 미세 긁힘·먼지(1~3 cm). 마스크 경계는 `saturate((mask + noise*0.5 - threshold) * 6)` 같은 "높이 섞기" 로 날카롭게 (부드러운 lerp 는 흐릿한 구름처럼 보임) — 일반 관행 **[커뮤니티/추정]**.
- 긁힘은 방향이 있어야 진짜 같다: 콘솔 윗면은 앞뒤 방향(손이 미끄러지는 방향), 문턱은 길이 방향 (**추정**, 사진 c28·d03 관찰).

### 3.4 데칼·스텐실 (우리가 그린다)
- MSFS SDK: 조종석 데칼은 **메시에 매핑한 텍스처**(투사 아님), 전부 **1024² 한 장** 에 넣는 것을 권장, 글씨 가장자리에 색 여백, 알파 = 불투명도 **[확인됨: MSFS 2024 SDK Decals and Detail Maps]**.
- 우리는 이미 같은 방식(아틀라스 `T_CkPanels` 에 글씨를 그려 UV 로 붙임). 추가할 것: 노랑·검정 사출 경고 줄무늬, "NO STEP"·산소·배터리 명판, 판 번호 스텐실, Dzus 고정쇠 화살표. **실물 사진을 텍스처로 쓰지 않음**(스펙 6장, CC BY-SA).
- UE 투사 데칼(DBuffer): UE5 기본 방식, Deferred Decal 은 Translucent·Alpha Composite 만 지원, 액터별 "Receives Decals" 끄기 가능 **[확인됨: Epic Decal Materials]**. 비용은 데칼 수·화면 면적에 비례 **[확인됨: Meta Deferred 문서]**. 우리는 비행기와 함께 움직이고 VR 이라 **투사 데칼은 쓰지 않고 아틀라스에 굽는다** (**추정**: 더 싸고 두 눈에서 안정).

### 3.5 트림 시트
- 2048² 한 장에 가로 띠: 볼트 줄(지름 8 mm, 간격 4.5 cm), Dzus 줄, 판 이음(2 mm 홈), 경첩, 고무 실링, 경고 줄무늬, 미끄럼 방지 면. **높이맵을 그리고 → 노멀은 기존 `build_fabric_normal` 의 기울기 방식** 으로. 문턱 레일·패널 테두리 같은 긴 부품의 UV 를 띠 하나에 맞춤.
- UV 는 지금처럼 코드가 직접 계산(`region_uv` 와 같은 함수 `trim_uv(strip, s_along_cm, t)`), 길이 방향 반복.

### 3.6 텍셀 밀도
- MSFS SDK: 조종석 전체를 **같은 주 텍셀 비율로**, 작은 입력 장치만 예외 **[확인됨]**. Heatblur(DCS) 아티스트 인용 "약 15 texel/cm" **[커뮤니티, 출처 불확실]**, 다이얼 밀도가 낮아 흐려졌던 사례 **[커뮤니티]**.
- 계산 (**추정**, 헤드셋 20~25 px/도 가정): 60 cm 에서 1 cm ≈ 0.95° → 헤드셋이 표시할 수 있는 최대 ≈ **19~24 px/cm**. 더 높으면 밉맵이 버림.
  - 글씨·다이얼 아틀라스: 20~32 px/cm (지금 값 유지 — 맞음).
  - 색·거칠기 기본(대부분 단색 Tint): 해상도 필요 없음, 반복 텍스처로.
  - AO·모서리·때 마스크: **8~10 px/cm**(4096² 한 장, 저주파라 충분). 날카로운 모서리 선은 베벨 메시가 담당.
  - 세부 노멀·그런지: 반복 텍스처라 밀도 자유(1024² 를 5~16 cm 반복 ≈ 64~200 px/cm).

### 3.7 UV 자동화 (Blender 4.5, 이 PC 에서 조회) **[확인됨]**
- `bpy.ops.uv.smart_project(angle_limit, margin_method, rotate_method, island_margin, area_weight, correct_aspect, scale_to_bounds)` — 굽기용 UV2 에 사용.
- `bpy.ops.uv.lightmap_pack(PREF_CONTEXT, PREF_PACK_IN_ONE, PREF_NEW_UVLAYER, PREF_BOX_DIV, PREF_MARGIN_DIV)` — 빠르지만 섬 크기가 고르지 않음.
- `bpy.ops.uv.average_islands_scale()` → `bpy.ops.uv.pack_islands(rotate=True, margin=0.002)` 로 **텍셀 밀도 균일** (MSFS 권장과 맞음).
- 새 UV 는 `me.uv_layers.new(name="UV2")` — FBX 에서 UE 의 **UV 채널 2** 로 들어간다(UV0, UV1 순서 유지, 추정 — 첫 시험에서 확인).

---

## 4. CC0 텍스처 (계정 없이 받기)

두 곳 모두 **CC0**(상업 사용·무표기 가능) **[확인됨: polyhaven.com/license, docs.ambientcg.com/license]**. 아래 ID 는 2026-11-05 에 두 사이트의 공개 API 로 실제 존재를 확인했다 **[확인됨]** (Poly Haven `api.polyhaven.com/assets?t=textures` 869개, ambientCG `ambientcg.com/api/v2/full_json`). ambientCG 는 `https://ambientcg.com/get?file=<ID>_2K-JPG.zip` 이 로그인 없이 내려받기로 이어짐(302) **[확인됨]**. 우리 `Scripts/fetch_textures.py`(Poly Haven API 방식)를 그대로 늘리면 됨.

| 쓰임 | 추천 | 비고 |
|---|---|---|
| 칠한 금속(회색 통) | ambientCG `PaintedMetal002`(긁힌 칠), `Metal032`(매끈 회색) | **색은 버리고 노멀·거칠기만** 사용, 색은 FS 36231 Tint |
| 무광 검정 패널 | 같은 PaintedMetal 의 거칠기 + 우리 그런지 | 색 Tint 만 |
| 닳은 금속 모서리 | ambientCG `Metal009`(brushed, scratches) | 닳음 레이어의 거칠기/노멀 |
| 긁힘·지문·얼룩(유리·화면·반질 손잡이) | ambientCG `Scratches001/003/005`, `Fingerprints004`, `Smear003`, `SurfaceImperfections003/013` | 캐노피(스펙 P0) 에도 쓸 수 있음 |
| 고무(페달·손잡이) | ambientCG `Rubber004`, `Rubber001`; Poly Haven `rubber_tiles` | 노멀·거칠기 |
| 가죽(손잡이·좌석 가장자리) | Poly Haven `fabric_leather_02`, `brown_leather`; ambientCG `Leather037` | 검게 착색 |
| 양털 방석(사진 c06 의 검은 양털) | Poly Haven `curly_teddy_natural`, `faux_fur_geometric`; ambientCG `Fabric084`(fur) | 노멀이 핵심, 색 검정 0.02 |
| 천(좌석·하네스 덮개) | ambientCG `Fabric061`; Poly Haven `rough_linen`, `hessian_230` | 올리브/회색 Tint |
| 끈(웨빙) | 전용 CC0 없음 → 지금처럼 우리 코드로 짠 무늬(`build_fabric_normal`) 유지 | 결 방향을 끈 길이에 맞춤 |
| 나사 | 텍스처 대신 **메시**(2.2절) + 십자홈은 노멀 | — |

- UE 노멀은 DirectX 방식 → Poly Haven `nor_dx`, ambientCG `NormalDX` 파일을 받는다 (기존 `fetch_textures.py` 도 `nor_dx`).
- 그 밖의 무료 사이트(Poliigon·Textures.com·ShareTextures 등)는 계정·별도 라이선스가 있어 **쓰지 않음**(확인 안 함).
- 받은 텍스처마다 `ThirdParty/.../info.json` 에 출처·라이선스 기록(기존 방식).

---

## 5. UE 재질 설정

### 5.1 `M_CkSurface` 를 이렇게 바꾼다 (설계, 추정 값은 시험으로 조정)
```
Masks  = Tex(T_CkShellMasks, UV2)            # R=AO, G=edge, B=dirt/touch ; 없는 부품은 흰 텍스처(=효과 없음)
G      = Tex(T_CkGrunge, UV1*GrungeTile)       # R 큰 얼룩, G 미세
AOm    = lerp(1, Masks.R, AOAmt)               # AOAmt 1.0
Base   = Tex*Tint * lerp(0.85, 1.10, G.R)      # albedo 변화 ±10 %
Base   = lerp(Base, DirtColor, saturate((Masks.B + G.R*0.5 - (1-Dirt))*4))
wear   = saturate((Masks.G*EdgeGain + (G.G-0.5)*0.6 + Masks.B*TouchWear - (1-Wear)) * 6)
BaseColor = lerp(Base*AOm, WearColor, wear)    # WearColor 알루미늄 (0.55,0.56,0.57)
Metallic  = lerp(Metal, 1.0, wear)             # 0 또는 1 (Epic)
Roughness = clamp(Rough + (G.R-0.5)*RoughVar + dirt*0.15 - wear*0.25, 0.05, 1)   # RoughVar 0.3 → ±0.15
Specular  = 0.5 * AOm                          # Epic: cavity 를 BaseColor·Specular 둘 다에
Normal    = BlendAngleCorrectedNormals(lerp(flat, Tex(DetailN, UV1*DetailTile), DetailAmt), 소재 노멀)
```
- Epic: Metallic 0/1, Specular 0.5, 표면 변화는 Roughness 맵으로, cavity 맵은 BaseColor·Specular 에 곱 **[확인됨: Physically Based Materials]**.
- 세부 텍스처: Epic `DetailTexturing` 함수(반복 색·노멀을 겹쳐 가까이서 디테일; Scale = 반복) **[확인됨: Texturing Material Functions]**. 단, UE 4.27 문서는 노멀 입력이 "동작 안 함" 이라 했고 5.x 문서는 동작한다고 적어 엇갈림 → 우리처럼 Python 으로 노드를 만드는 경우 `BlendAngleCorrectedNormals` 를 직접 쓰는 게 안전 (**추정**).
- **Material Layers**(인스턴스 편집기에서 레이어 쌓기) 는 편집 편의 기능이고 성능 이점은 문서에 없음 **[확인됨: Layering Materials]** → 우리는 Python 으로 그래프를 만드니 **지금의 마스터 재질 1개 + 인스턴스** 유지.
- 샘플러: 지금 3~4 개 + 마스크 1 + 세부 노멀 1 = 6 개 정도 (한도 16, 문제없음). ALU +30 명령 내외 → VR 에서 0.05 ms 안쪽 (**추정**).
- 정점색 경로는 작은 움직이는 부품(스틱·스로틀 등)에 남겨 두거나, 그 부품도 512²~1024² 로 따로 굽는다.

### 5.2 텍스처 가져오기 설정 (에디터 Python)
| 텍스처 | `srgb` | `compression_settings` | 비고 |
|---|---|---|---|
| 색(아틀라스·CC0 색) | True | `TC_DEFAULT`(글씨는 지금처럼 `TC_BC7`) | — |
| 마스크(AO/모서리/때, 그런지) | **False** | `TC_MASKS` | TC_MASKS = 기본 압축 + sRGB 끔 **[확인됨: Python API·UE 4.27 문서, 포럼]** |
| 노멀(세부·트림·CC0) | False | `TC_NORMALMAP` | DirectX 노멀 |
- 밉맵은 켠 채로(기본) — 끄면 VR 에서 반짝임. 텍스처 그룹은 `TEXTUREGROUP_WORLD`(기본) 또는 세부 노멀은 `TEXTUREGROUP_WORLD_NORMAL_MAP`.
- 기존 `build_level.import_textures(kinds=...)` 에 `"mask"` 종류 하나를 추가하는 정도면 됨 (`linear` 는 sRGB 만 끄고 압축은 기본).

### 5.3 데칼: DBuffer vs 굽기
| | DBuffer 투사 데칼 | 아틀라스/트림에 굽기 |
|---|---|---|
| 비용 | 데칼 수·화면 면적만큼 매 프레임 | 텍스처 샘플 1번 |
| VR | 두 눈 모두 그림, 움직이는 기체에 붙여야 함 | 문제없음 |
| 바꾸기 | 런타임에 바꾸기 쉬움 | 다시 굽고 가져오기 |
→ **굽기**. 투사 데칼은 나중에 "런타임에 바뀌는 것"(예: 기체 번호 선택)에만.

---

## 6. 실물 기준 값

| 항목 | 값 | 확실도·출처 |
|---|---|---|
| 통·옆벽 색 | **FS 36231 Dark Gull Gray** — 1953년부터 미 공군·해군 조종석 표준 회색, F-16 실내 | 모형 커뮤니티 (gmodelart, Zinnfigur, f-16.net) **[커뮤니티]** |
| FS 36231 근사 RGB | sRGB ≈ (110, 120, 111) ~ (113, 121, 113) → 선형 ≈ (0.16, 0.19, 0.16) | 모형 페인트 DB(railwaymates, scalemates) — 출처마다 다름 **[커뮤니티]**. 사진 c06 의 통은 거의 중성 회색 → **Tint (0.15, 0.16, 0.16) 권장(추정)** |
| 일부 개조기 실내 | 더 밝은 FS 36270 (IRAN 재정비 기체) | f-16.net(Blackbox 인용) **[커뮤니티]** |
| 무광 검정 FS 37038 | 계기 테·장착 플랜지·노브용 무광(반사 줄이기), 계기판은 반광 검정 | gmodelart **[커뮤니티]**. 선형 0.015~0.02 (sRGB 33~38, PBR 하한 30 근처) **추정** |
| 글레어실드 | 반사 방지 무광 검정, Rough 0.9~0.95 | 기존 스펙 |
| 글씨 조명 | 낮: 흰 글씨. 밤: Block 40 개조로 흰 조명 → **"NVIS green"** 으로 교체 | f-16.net 뉴스(1998) **[커뮤니티급 보도]**, MIL-STD-3009 NVIS Green A/B (DTIC) |
| 플러드 조명 색 | NVIS white(푸르스름) vs 초록 — 포럼끼리 엇갈림 | Falcon BMS 포럼 **[커뮤니티, 불확실]** |

**닳는 곳 (사진 c06·c28·d03 관찰 + 추정):** 캐노피 문턱 윗면과 안쪽 모서리(타고 내릴 때·팔꿈치), 왼쪽 콘솔 스로틀 주변, 오른쪽 콘솔 팔걸이·스틱 주변, 좌석 방석 앞끝, 바닥 뒤꿈치 자리·러더 페달 발판, 스위치 가드·노브 머리. 검정 칠은 닳으면 **회색(밑칠)→은색 금속** 으로, 회색 칠은 은색으로.

---

## 7. 우리 모델용 파이프라인 (단계 · API · 파일)

`unreal/` 은 다른 담당이 작업 중이라 **이 문서는 설계만** 한다. 구현은 모델링 담당이 `model_blender.py`·`make_textures.py`·`ue_cockpit.py` 에.

### 단계 0 — 값만 고치기 (1번 할 일, 굽기 전)
`ue_cockpit.py` `CK_SLOTS`: `CK_Paint` Tint (0.15, 0.16, 0.16) Rough 0.65 · `CK_Panel/CK_Black` 0.018 Rough 0.85 · `CK_AntiGlare` 0.012 · `WearMetal` 1.0 · `WearColor` (0.55, 0.56, 0.57). `ck_master` 그런지 폭 0.85~1.10 / ±0.15.
→ 스크린샷 1·1b·4a·6a 다시 찍어 비교 (같은 시점·같은 프리셋).

### 단계 1 — Blender: 베벨 (`model_blender.py` `to_object` 안, Weighted Normal 앞)
```python
bv = ob.modifiers.new("bevel", 'BEVEL')
bv.width = 0.0025; bv.segments = 2; bv.limit_method = 'ANGLE'; bv.angle_limit = math.radians(30)
bv.profile = 0.5; bv.use_clamp_overlap = True; bv.harden_normals = True; bv.miter_outer = 'MITER_ARC'
m = ob.modifiers.new("wn", 'WEIGHTED_NORMAL'); m.keep_sharp = True; m.weight = 50   # 항상 마지막
```
주의: 이미 베벨된 작은 상자에도 다시 걸린다 → 각도 30° 로 이미 둥근 곳은 대부분 건너뜀 (추정). 문제가 되면 `limit_method='WEIGHT'` 로 바꾸고 큰 모양 모서리에만 bevel weight 를 준다. 베벨 뒤 **정점색 계산은 빼거나 남겨 둠**(텍스처 마스크로 대체 후 제거).

### 단계 2 — Blender: UV2 + 굽기 (`ck_shell` 만, 새 함수 `bake_masks(ob)`)
```python
bpy.ops.object.modifier_apply(modifier="bevel")             # 굽기 전에 모양 확정 (WN 은 export 때 적용)
uv2 = me.uv_layers.new(name="UV2"); me.uv_layers.active = uv2
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.002)
bpy.ops.uv.average_islands_scale(); bpy.ops.uv.pack_islands(rotate=True, margin=0.002)
bpy.ops.object.mode_set(mode='OBJECT')
me.uv_layers.active = me.uv_layers["UV2"]                   # 굽기 대상 UV
sc = bpy.context.scene; sc.render.engine = 'CYCLES'; sc.cycles.samples = 128
sc.world = sc.world or bpy.data.worlds.new("w"); sc.world.light_settings.distance = 0.08
for name, kind in (("AO", 'AO'), ("EDGE", 'EMIT'), ("DIRT", 'EMIT')):
    img = bpy.data.images.new("ck_" + name, 4096, 4096); img.colorspace_settings.name = 'Non-Color'
    for mat in me.materials:                                 # 활성 이미지 노드 + (EMIT 이면) 마스크 셰이더로 임시 교체
        set_bake_target(mat, img, mode=name)
    bpy.ops.object.bake(type=kind, margin=16, margin_type='EXTEND', uv_layer="UV2", use_clear=True)
    img.filepath_raw = os.path.join(TEX, "ck_shell_%s.png" % name.lower()); img.file_format = 'PNG'; img.save()
```
- `set_bake_target` 의 EDGE 셰이더: `Bevel(Radius 0.003, Samples 8)` 노멀과 `Geometry.Normal` 의 내적 d → Emission = clamp((1-d)·8). (Blender 4.5 에 `ShaderNodeBevel` 존재 확인 **[확인됨]**)
- DIRT 셰이더: `AmbientOcclusion(Distance 0.3, Only Local)` 의 어둠 × 높이(아래일수록 1) + 손 점 마스크: 각 점 p_i 에 `exp(-|Position - p_i|² / r²)` 합 (r 8~15 cm). 점 좌표는 `layout.py` 의 스로틀·스틱 피벗, 문턱, 페달 위치를 Blender 좌표 (x, −y, z)/100 로.
- 세 PNG 를 하나로 합치기: `make_textures.py` 마지막 또는 Blender 에서 `image.pixels.foreach_get` → numpy → R/G/B 채널 → `T_CkShellMasks.png`. 결과 JSON(manifest)에 **만든 시각·입력(layout 해시)·해상도·샘플 수** 기록 (기존 `MANIFEST["made"]` 처럼).
- **움직이는 부품은 지오메트리가 셸과 따로** 라 셸 AO 에 "스틱이 만든 그림자" 가 들어가면 안 된다 → 굽기 장면에 움직이는 부품을 넣지 않는다(지금 FBX 처럼 셸만).
- 시간: 이 PC 에서 2048²·64 샘플 26.7 초 → 4096²·128 샘플 × 3 장 약 6~10 분 (**추정**). `build_cockpit.py` 에 `--no-bake`(이전 결과 재사용) 옵션 권장.
- 내보내기 FBX 는 지금 그대로(`use_mesh_modifiers=True`), UV2 가 같이 나감.

### 단계 3 — 반복 텍스처 받기·만들기
- `fetch_textures.py` 에 4장의 CC0 ID 추가 (2k JPG, `nor_dx`/`NormalDX` + rough).
- `make_textures.py`: 그런지 2 채널화, 페인트 세부 노멀(`T_CkPaintN`, 1024², 오렌지필 = 저진폭 노이즈 + 미세 긁힘선, 세기 작게), 트림 시트(`T_CkTrim`, `T_CkTrimN`, 2048²), 데칼 추가.

### 단계 4 — UE 가져오기 (`ue_cockpit.py` `build_cockpit`)
```python
tx = import_textures(files, CK + "/Textures", {masks: "linear", paintN: "normal", trimN: "normal"})
t = tx["T_CkShellMasks"]
t.set_editor_property("srgb", False)
t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
EAL.save_loaded_asset(t)
```
- 메시 가져오기 설정은 지금 그대로(`generate_lightmap_u_vs=False` 가 UV2 를 지킴). 가져온 뒤 `sm.get_num_uv_channels(0)` 가 3 인지 로그로 확인.
- `ck_master` 에 5.1 그래프 추가: `TextureCoordinate(coordinate_index=2)` → `T_CkShellMasks`. 움직이는 부품용으로 파라미터 `Masks` 기본값 = 흰 텍스처(`/Engine/EngineResources/WhiteSquareTexture`, 지금 `Tex` 와 같은 방식).

### 단계 5 — 인스턴스 값 (시작값, 추정 → 화면 보고 조정)
| 슬롯 | Tint (선형) | Rough | RoughVar | Wear | EdgeGain | Dirt | DetailAmt | 세부 노멀 |
|---|---|---|---|---|---|---|---|---|
| CK_Paint (통) | 0.15, 0.16, 0.16 | 0.65 | 0.3 | 0.5 | 1.0 | 0.4 | 0.25 | T_CkPaintN, 5 cm 반복 |
| CK_Panel / CK_Black | 0.018 | 0.85 | 0.25 | 0.4 | 1.0 | 0.3 | 0.2 | T_CkPaintN |
| CK_AntiGlare | 0.012 | 0.95 | 0.1 | 0.1 | 0.5 | 0.2 | 0.15 | T_CkPaintN |
| CK_Frame (문턱) | 0.03 | 0.5 | 0.3 | 0.9 | 1.5 | 0.3 | 0.3 | T_CkTrimN |
| CK_Seat (방석) | 0.02 | 0.9 | 0.1 | 0 | 0 | 0.2 | 1.0 | 양털 노멀 10 cm |
| CK_Rubber | 0.014 | 0.85 | 0.15 | 0 | 0 | 0.4 | 0.6 | Rubber004 |
| CK_Metal | 0.55, 0.56, 0.57 (Metal 1) | 0.4 | 0.2 | 0 | 0 | 0.3 | 0.3 | Metal009 |
공통: `AOAmt` 1.0, `TouchWear` 1.0, `DirtColor` (0.045, 0.040, 0.032), `WearColor` (0.55, 0.56, 0.57).

### 단계 6 — 확인 (간단 시험 먼저)
1. **마스크 단독 보기**: BaseColor 에 Masks.R 만 연결한 디버그 인스턴스 → 구석이 어둡고 넓은 면 가운데가 흰지, UV 이음에 선이 없는지.
2. 스크린샷 1·1b·4a·6a 전·후 비교 + 실물 c06·c28·d03 옆에 놓고 비교.
3. `measure_fps.py` 같은 프리셋·같은 시점으로 GPU ms 전·후.
4. 헤드셋: 나사·틈이 두 눈으로 입체로 보이는지, 세부 노멀이 반짝이지(aliasing) 않는지.

---

## 8. 확인 못 한 것 / 가정
- 모든 GPU ms, 베벨·깊이 기준(1.5~3 mm, 5 mm), 헤드셋 20~25 px/도, 굽기 시간 외삽, 인스턴스 시작값: **추정**.
- FS 36231 의 정확한 RGB: 공식 FS 595 칩 값이 아니라 모형 페인트 DB 값 — 출처마다 다름.
- F-16 콘솔별 검정/회색 구분, 글씨 조명 색: 기술 교범 확인 못 함(커뮤니티).
- Blender FBX 의 세 번째 UV 가 UE 에서 채널 2 로 오는지: 아직 안 해 봄 (단계 4 에서 로그로 확인).
- Bevel 노드로 굽는 모서리 마스크의 증폭 값(×8): 시험 안 함.
- 80.lv·Polycount 의 조종석 전용 텍스처 분석 글은 찾지 못함 — 일반 하드서피스 글과 MSFS SDK 로 대신.
- 이 PC 에서 직접 한 것: Blender 4.5.15 API 조회(bake·UV·Bevel·Weighted Normal), 기존 `ck_shell.fbx` 의 면적·넓은 면 비율 측정, 2048² AO 시험 굽기(임시 폴더에 저장, 프로젝트 파일 변경 없음).

---

## 9. 출처

Blender (공식)
- Bevel 셰이더 노드(Cycles 전용, Radius, Samples 4): https://docs.blender.org/manual/en/4.5/render/shader_nodes/input/bevel.html
- Geometry 노드 Pointiness(정점 곡률 근사, Cycles 전용): https://docs.blender.org/manual/en/4.5/render/shader_nodes/input/geometry.html
- Render Baking: https://docs.blender.org/manual/en/latest/render/cycles/baking.html
- BakeSettings API: https://docs.blender.org/api/blender_python_api_current/bpy.types.BakeSettings.html
- Bake API 도입 커밋(bpy.ops.object.bake): https://developer.blender.org/rB97641a0
- Bevel harden normals 버그(해결됨): https://developer.blender.org/T58113
- GSoC 2018 Bevel 개선(가중 노멀은 스택 마지막): https://devtalk.blender.org/t/gsoc-2018-bevel-improvements/440?page=2

Epic (공식)
- Physically Based Materials (Metallic 0/1, Specular 0.5, cavity 를 BaseColor·Specular 에): https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine
- Texturing Material Functions (DetailTexturing): https://dev.epicgames.com/documentation/en-us/unreal-engine/texturing-material-functions-in-unreal-engine
- UE 4.27 Texturing 함수(노멀 입력 비동작 언급): https://docs.unrealengine.com/4.27/RenderingAndGraphics/Materials/Functions/Reference/Texturing
- Layering Materials: https://dev.epicgames.com/documentation/en-us/unreal-engine/layering-materials-in-unreal-engine
- Decal Materials (DBuffer 기본, 블렌드 모드 제한): https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine
- Decal Actors: https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-actors-in-unreal-engine
- TextureCompressionSettings (Python): https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/TextureCompressionSettings
- Texture Compression Settings (4.27, Masks = sRGB 끔): https://docs.unrealengine.com/4.27/RenderingAndGraphics/Textures/TextureCompressionSettings
- Forward Shading Renderer: https://dev.epicgames.com/documentation/en-us/unreal-engine/forward-shading-renderer-in-unreal-engine
- Meta: Unreal Deferred Shading(데칼 비용): https://developers.meta.com/vr/documentation/unreal/unreal-deferred-shading/

비행 시뮬레이터 제작 문서
- MSFS 2024 SDK Cockpit Textures and Materials (텍셀 비율 통일, 먼지·긁힘): https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/cockpit/textures/cockpit-textures-and-materials/index.md
- MSFS 2024 SDK Decals and Detail Maps (1024² 데칼 시트, 메시 매핑): https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/cockpit/textures/decals-and-detail-maps/index.md
- MSFS 2024 SDK Material Mapping: https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/cockpit/textures/material-mapping/
- MSFS 2024 SDK Cockpit modeling general principles: https://docs.flightsimulator.com/msfs2024/retail/models-and-textures/modeling/aircraft/cockpit/cockpit-and-cabin-modeling-general-principles/index.md
- DCS 포럼, Heatblur 아티스트 텍셀 밀도 질문: https://forum.dcs.world/topic/213810-a-technical-question-for-hb-artist-nicholas-dackard
- DCS 포럼, 다이얼 텍셀 밀도 부족으로 흐림: https://forum.dcs.world/topic/184403-fixed-low-resolution-on-cockpit-textures-writing
- DCS 포럼, 조종석 면 수 상한(2013): https://forum.dcs.world/topic/93372-maximum-sensible-face-count

하드서피스·텍셀 밀도 (커뮤니티)
- Polycount: VR 에서 베벨 vs 노멀맵: https://polycount.com/discussion/185509/bevel-or-use-normal-maps-in-vr
- Polycount: 고폴리 없이 미드폴리: https://polycount.com/discussion/174528/is-a-high-poly-model-needed-for-realistic-pbr-game-assets
- 80.lv: UE5 미드폴리 작업 방식: https://80.lv/articles/creating-assets-within-the-mid-poly-workflow-in-ue5/
- Polycount: texel density: https://polycount.com/discussion/216821/texel-density
- Maxon: Texel Density(가까울수록 높게, 장면 안 통일): https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html
- UE 포럼: VR 에서 노멀맵: https://forums.unrealengine.com/t/normal-maps-dont-look-good-in-vr-yet-every-single-demo-is-using-them/66185

텍스처 라이선스·목록
- Poly Haven License (CC0): https://polyhaven.com/license · API: https://api.polyhaven.com/assets?t=textures
- ambientCG License (CC0): https://docs.ambientcg.com/license/ · API: https://ambientcg.com/api/v2/full_json
- 예: https://polyhaven.com/a/curly_teddy_natural, https://polyhaven.com/a/fabric_leather_02, https://ambientcg.com/view?id=PaintedMetal002, https://ambientcg.com/view?id=Rubber004

실물 색·조명 (커뮤니티)
- gmodelart NATO Cockpits (FS 36231·37038 역사): https://forum.gmodelart.com/nato-cockpits-and-interiors-1947-current/amp , https://forum.gmodelart.com/?p=16880
- f-16.net 조종석 색: https://www.f-16.net/forum/viewtopic.php?p=72687
- Zinnfigur USAF 회색 계열(F-16 실내 FS 36231): https://www.zinnfigur.com/en/Paints-Tools/Painting-sets/Airplanes/America/USAF-Colors-Gray-Schemes-from-70-s-to-present.html
- 페인트 DB (FS 36231 근사 RGB): https://www.railwaymates.com/colors/rgb.php?id=6e786f , https://www.scalemates.com/colors/rgb.php?id=717971
- DCS 포럼 패널 페인트: https://forum.dcs.world/topic/343287-paint-recommendations-for-panels
- f-16.net 뉴스: Block 40 NVIS green 조명: https://www.f-16.net/f-16-news-article383.html
- Falcon BMS 포럼 조명 색: https://forum.falcon-bms.com/post/29704?page=2
- DTIC NVIS 호환 조명: https://apps.dtic.mil/sti/pdfs/ADA517298.pdf
