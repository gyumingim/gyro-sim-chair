# 나무 에셋 (Fab / Megascans) — 받을 것과 넣는 법 (11-10)

결론: **소나무 팩이 아직 없다.** 아래 1번(Baltic Pine)만 더 받으면 소나무도 실제 모델 모양으로 바뀐다. 활엽수는 이미 받은 참나무·오리나무를 쓴다.

## 받을 것 (Fab, 무료로 표시됨 — 11-10 목록 페이지 확인, 라이선스 칸은 비어 있음 → Fab 표준 라이선스로 봄, 저장소에 올리지 않음)
| 순서 | 이름 | 왜 | 링크 |
|---|---|---|---|
| 1 | Megaplants: Baltic Pine (*Pinus sylvestris*, 구주소나무) | 소나무(*P. densiflora*)와 가장 닮음: 주황빛 위쪽 껍질, 늙으면 납작하고 불규칙한 수관. USD 있음 | https://www.fab.com/listings/a2b04e81-5075-479f-a9d2-4940022f330a |
| 2 | Megaplants: Baltic Pine Saplings | 어린 소나무·숲 가장자리 | https://www.fab.com/listings/ae732b47-14db-422e-b11d-c93537cb5165 |
| 3 | Megaplants: Aleppo Pine (*Pinus halepensis*) | 바닷가 곰솔 대신 (바람 맞은 비뚤어진 수관) | https://www.fab.com/listings/a441387b-c3e0-4982-82c4-5f661ccca6dd |

받을 때 형식은 **USD** 를 고른다 (이미 받은 English Oak Forest / Black Alder 와 같은 꼴이라 도구가 그대로 읽음).
가격·라이선스는 페이지 표시 기준 (가정, 로그인해서 다시 확인 필요).

## 넣는 법 (명령 두 줄, 에디터 안 열어도 됨)
1. zip 을 `C:\GyroSimTiles\assets\trees_src\<이름>\` 에 풀기 (저장소 밖).
2. 모양만 뽑기 (`sim/veg_proxy.py`: 잎 위치 → 잎 덩어리 14 개, 줄기 축. 모델 자체는 타일에 안 들어감):
   ```
   python -I sim/veg_proxy.py --out C:\GyroSimTiles\veg\protos_fab pine=<Baltic_Pine_A.usd> pine=<..._B.usd> broad=<참나무 A.usd> ...
   python -I sim/veg_v2.py --tiles
   ```
   - `GYROSIM_TREES_PROTOS` = 이 폴더 바꾸기 (기본 `C:\GyroSimTiles\veg\protos_fab`, `none` = 절차 생성 나무만).
   - `GYROSIM_TREES_PROTO_PICK` = 활엽수 3 종에 쓸 `broad_<k>` 번호 (기본 `1,2,5` = 참나무 B·C, 오리나무 B).
   - `pine_*.npz` 가 있으면 소나무 2 종도 그 모양을 씀 (곰솔 자리 포함).
   - 낮은 다각형 glb (y 위쪽, 한 나무) 도 `pine*.glb / broad*.glb / shrub*.glb` 이름으로 같은 폴더에 두면 그대로 씀 (텍스처는 안 씀).

## 받은 것 점검 (11-10)
| 파일 | 쓰나 | 이유 |
|---|---|---|
| tree_english_oak_forest_01_usd.zip (Megascans English Oak Forest A–D) | 씀 (모양만) | USD, 잎 위치 = 가지 인스턴서. 라이선스 Fab (UE 안에서만) → 결과는 git 밖 |
| tree_black_alder_01_usd.zip (Black Alder A–D) | 씀 (모양만) | 같음 |
| av_acer_x_freemanii_freeman_max.zip | 안 씀 | 3ds Max `.max` 만 있음 (열 도구 없음), 라이선스 파일 없음 ("Pandora Land" 출처 불명) |
| christmass_trees_pack.blend | 안 씀 | 라이선스 표시 없음, Blender 파일 (Blender 없음), 크리스마스트리 = 전나무·가문비 모양 |
| mobile_trees_model.zip (Tree Master, Fab) | 안 씀 | 잎 카드 + 투명 텍스처 방식: 지금 3D Tiles 길은 텍스처를 안 씀. PDF 에 라이선스 문구 없음 |

## 왜 모델을 그대로 안 쓰나
Megaplants 는 나무 한 그루가 수십만~수백만 꼭짓점 (Nanite 잎). 부산 나무 1650 만 그루를 비행기 둘레에서 스트리밍하는 지금 길
(Cesium 3D Tiles, 나무당 150–400 삼각형) 에는 그대로 못 넣는다. 그래서 모양(잎 덩어리 위치·크기, 줄기 축)만 뽑아 쓴다.
더 가까이(100 m 아래) 진짜 잎을 보이려면 UE 쪽 Nanite 인스턴스(HISM)로 가까운 나무만 바꾸는 다음 단계가 필요 (안 함).
