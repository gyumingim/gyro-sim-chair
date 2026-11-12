# 부산 나무: 잎 카드 타일 (leaf-card trees), 2026-11-12

부산 3D 나무의 **기본 모습**. 나무 자리·높이·종류는 v2 나무(`sim/veg_v2.py`, 약 1,990 만 그루)와 같고,
소나무·해송·활엽수 모양만 잎 카드 나무(`sim/veg_cards.py`)로 바꾼 타일이다. 관목·바위는 v2 모양 그대로.

## 켜고 끄기 (코드 기준: `unreal/GyroSim/Content/Python/trees_look.py`, `trees_near.py`)
| 환경 변수 | 기본 | 뜻 |
|---|---|---|
| `GYROSIM_TREES_CARDS` | `1` (켜짐) | `0` = 예전 v2 덩어리 나무 (`tiles_v2` + `M_GyroTree2`). 카드 타일(`C:/GyroSimTiles/veg/tiles_cards/tileset.json`)이나 재질 `/Game/Trees/M_GyroTreeCard` 가 없으면 로그 한 줄 남기고 저절로 덩어리 나무 |
| `GYROSIM_TREES_TILES` | 없음 | 다른 타일 폴더를 쓰면 카드는 꺼짐 |
| `GYROSIM_TREES_V2` | `1` | `0` = v1 나무 (카드도 안 씀) |
| `GYROSIM_TREES` | `1` | `0` = 나무 전부 끔 |
| `GYROSIM_TREES_NEAR` | `0` (꺼짐) | `1` = 비행기 둘레 실제 잎 나무 (`trees_near.py`, [trees-near-busan.md](trees-near-busan.md)) |
| `GYROSIM_TREES_PROXY` | `1` | `GYROSIM_TREES_NEAR=1` 일 때만 뜻이 있음: `0` = 타일 나무(카드 또는 덩어리)를 숨기고 가까운 나무만 |

## 만들기
```
python -I sim/veg_cards_tiles.py      -> C:/GyroSimTiles/veg/tiles_cards (임시 폴더 -> 교체, 전 판은 tiles_cards_prev)
```
- 무거운 CPU 작업: 스크립트가 스스로 코어 절반 이하·낮은 우선순위로 돌지만 잠금은 직접 잡지 않는다.
  `C:/GyroSimTiles/ue_offscreen.lock` 을 잡은 상태에서 돌린다 (전원 규칙, 11-11).
  교체는 UnrealEditor 가 떠 있으면 건너뛴다.
- 가까운 타일(약 1 km 안): 큰 카드 나무, 나무당 약 370-600 삼각형. 먼 타일(1-3.9 km): 같은 나무의 카드 8 장, 32 삼각형.
- 잎 그림 묶음(atlas)은 `C:/GyroSimTiles/veg/cards_atlas.png` 에 쓰고 UE 텍스처 `T_GyroTreeCards` 로 들여온다 (타일 안에는 없음).

## 자료
잎 카드·나무 모양은 우리 코드가 그린 것 (외부 텍스처·모델 없음). 나무 자리·높이 자료는 `unreal/GyroSim/ATTRIBUTION.md`
(Meta·WRI 수관고 CC BY 4.0, ESA WorldCover CC BY 4.0, OpenStreetMap ODbL). 타일은 git 밖.
