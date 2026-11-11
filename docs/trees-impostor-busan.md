# 부산 나무 — 받은 실제 모델로 만든 임포스터 (11-11)

결론: 나무 약 1960 만 그루를 **카드 1 장 (삼각형 2 개)** 으로 그린다. 카드에는 받은 실제 나무 모델을 64 방향에서 찍은 그림 묶음 (임포스터) 을 붙인다.
**기본값으로 켜져 있다.** `GYROSIM_TREES_IMPOSTOR=0` 이면 예전 둥근 덩어리 나무 (blob 타일) 로 돌아간다.
측정 결과 (GPU ms, 삼각형) 는 아래 "측정" 표에 있다.

## 무엇을 했나
1. **굽기 (Blender, 창 없음)**: `sim/impostor/bake_blender.py` + `pipeline.py --bake --assemble`
   - 원본은 전체 메시 그대로 썼다. 잎을 줄이지 않았고, 그래서 이전 시도처럼 잎이 빠지지 않는다.
   - 위쪽 반구를 8×8 = 64 방향으로 나눠 직교 카메라로 찍는다 (Cycles GPU). 방향마다 256 px, 그림 묶음은 2048².
   - 그림 A: sRGB 색 + 투명도.
   - 그림 B: 법선 (oct 인코딩 2 채널) + 깊이 (경계 구 지름 기준) + AO (Cycles, 2.5 m).
   - 종류 8 개:
     - 소나무 a/b/c, 어린 소나무, 전나무 (Poly Haven, CC0)
     - 참나무 B/C, 오리나무 B (Megascans, Fab 라이선스 = UE 안에서만)
     - 게임에서는 7 종을 쓴다. 전나무는 미리보기에만 썼다.
2. **Unreal 자산**: `unreal/GyroSim/Scripts/trees_imp_assets.py` (헤드리스 commandlet, 잠금 파일 잡고 실행)
   - `/Game/ThirdParty/Trees/Impostor/T_Imp_*`: 그림 묶음. BC7, git 제외 폴더.
   - `/Game/Trees/Imp/SM_GyroImpCard`: 사각형 1 장. 경계 상자가 ±1 m 정육면체가 되도록 대각면에 놓았다.
   - `/Game/Trees/M_GyroTreeImp`: Masked, 양면 재질.
     - 정점 단계 (`Scripts/trees_imp_card.hlsl`): 카드를 카메라 쪽으로 돌린다 (World Position Offset).
     - 화소 단계 (`Scripts/trees_imp.hlsl`): 시선에 가장 가까운 4 방향 그림을 섞는다. 각 방향 그림은 자기 그림면으로 다시 투영해서 읽는다.
     - 투명도는 디더로 처리한다. TSR 이 여러 프레임을 평균하므로, 먼 나무도 얇아지지 않는다.
   - 좌표 공간은 ISM 의 **인스턴스 공간** (Instance & Particle) 을 쓴다.
     - 처음에 'Local' (컴포넌트 공간) 으로 만들었더니 카드가 컴포넌트 원점 근처로 모여 나무가 안 보였다. 이 상태로 잰 첫 GPU 수치는 버렸다.
3. **실행 중 (Play)**: `Content/Python/trees_imp.py`
   - 나무 위치·키·수관 폭·수종 = `C:/GyroSimTiles/veg/near/trees_near.bin`. blob 타일과 같은 나무다.
   - 지도에 이미 있는 `GyroTreesNear` 액터 (슬롯 64 × 컴포넌트 8) 를 다시 쓴다. 지도 파일은 고치지 않았다.
   - 슬롯 1 개 = 1.25 km 블록 (데이터 칸 5×5), 컴포넌트 1 개 = 나무 종류 1 개.
   - 반경 3.9 km (blob 타일이 닿던 거리) 안을 프레임마다 4 ms 씩 나눠 채운다.
   - 2 km 밖 블록은 가장 가까운 한 방향 그림만 쓴다 (Far=1, 더 쌈).
   - 그림자는 1.5 km 안 블록만 드리운다.
   - `trees_look.apply` 가 이것을 먼저 켜고, 켜지면 blob 타일을 숨긴다.

## 경로 선택: 인스턴스 카드 (Cesium 타일 쪽은 재지 않음)
- 임포스터 화소 셰이더는 나무마다 중심·회전·크기가 필요하다.
  - 인스턴스 카드는 이 값을 인스턴스 변환에서 그대로 얻는다.
  - Cesium 3D Tiles 는 정점 색 (COLOR_0) 만 재질로 넘기는 것으로 확인했다 (blob 타일이 그렇게 씀). 다른 정점 속성이 넘어가는지는 **확인하지 않았다 (가정)**. 넘어가지 않으면 나무 중심을 실을 칸이 없다.
- 타일 쪽을 하려면 1960 만 그루 타일 전체를 다시 만들어야 한다.
- 그래서 타일 쪽은 측정하지 않았다. 사용자 요청 ("재서 싼 쪽") 과 다르다: 비용으로 고른 게 아니고 구조 때문에 골랐다. 인스턴스 카드 쪽 비용은 아래에 쟀다.

## 색 맞추기
- 미리보기에서는 조금 누렇고 어두웠다.
- 종류마다 색 배수 = sim/veg_v2 의 수종 반사율 (blob 나무 색, 부산 사진으로 맞춘 값) ÷ 그림 묶음의 평균 색.
- 전체 밝기 (gain) 와 RGB 균형은 hwang_low 화면에서 맞췄다. 기준은 같은 자리에서 나무가 덮은 화소의 평균 색이다 (blob 화면과 비교, `sim/impostor/calib.py`). 결과: gain 4.2, 균형 R 1.04 / G 0.97 / B 0.62.
- 값은 `C:/GyroSimTiles/assets/trees_impostor/imp_info.json` 에 있다. 실행 중에 읽으므로 자산을 다시 만들지 않고 바꿀 수 있다. `GYROSIM_TREES_IMP_GAIN` 으로 곱할 수도 있다.

## 측정
(아래 표는 측정 후 채움 — `C:/GyroSimTiles/shots/trees_imp/shots.json`, `view_tris.json`)

## 끄기·조절 (env)
| 변수 | 기본 | 뜻 |
|---|---|---|
| `GYROSIM_TREES_IMPOSTOR` | 1 | 0 = 예전 blob 타일 |
| `GYROSIM_TREES_IMP_R` | 3900 | 반경 m |
| `GYROSIM_TREES_IMP_FAR` | 2000 | 이 거리 밖 블록은 한 방향 그림만 |
| `GYROSIM_TREES_IMP_SHADOW_M` | 1500 | 그림자 드리우는 거리 (0 = 그림자 없음) |
| `GYROSIM_TREES_IMP_GAIN` | 1 | 밝기 곱 |
| `GYROSIM_TREES_IMP_PARAMS` | - | 시험용 재질 값 (예 `AoAmt=0.5,Dither=0`) |
`GYROSIM_TREES_NEAR=1` (가까운 실제 잎 나무, 시험용) 을 켜면 그쪽이 우선이다.

## 다시 만들기
```
python -I sim/impostor/pipeline.py --bake          # Blender 헤드리스 (잠금 잡음), 약 1.5 분
python -I sim/impostor/pipeline.py --assemble      # 그림 묶음 PNG
python -I sim/impostor/pipeline.py --ue            # 카드 glb + imp_info.json (색 배수)
UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=Scripts/trees_imp_assets.py -unattended -nosplash -nullrhi   (잠금 잡고, 에디터 닫힌 상태)
bash sim/impostor/ue_shots.sh none,blob,imp         # 화면 + GPU ms (잠금 잡음, 다른 UnrealEditor 가 떠 있으면 시작 안 함)
python -I sim/impostor/view_tris.py                 # 화면 안 삼각형 추정
python -I sim/impostor/pick_page.py <shots> <page> <key.json>
```
미리보기 (실제 모델 vs 임포스터 소프트웨어 렌더): `pipeline.py --scenes --real --imp`, `page.py`.

## 라이선스
- Megascans (참나무·오리나무) 에서 구운 그림 묶음은 Fab 표준 라이선스라 UE 안에서만 쓸 수 있다. 그래서 git 에 넣지 않는다 (`Content/ThirdParty/` 는 .gitignore).
- Poly Haven 소나무·어린 소나무·전나무는 CC0 이다. 원본과 구운 그림 묶음은 `C:/GyroSimTiles/assets/` 아래에 두고, 저장소에는 넣지 않는다.
- 저장소에는 스크립트·HLSL·재질·카드 메시 (모두 직접 만든 것) 만 들어간다.
