# 부산 나무: 비행기 둘레 실제 잎 나무 (near trees), 2026-11-11

**선택 기능, 기본 꺼짐** (`GYROSIM_TREES_NEAR=1` 로 켬). 11-11 에 줄인 메시의 잎이 빠져 회색 막대처럼 보여 기본에서 뺐다.
기본 나무는 잎 카드 타일이다 ([trees-cards-busan.md](trees-cards-busan.md)).

## 켜고 끄기 (코드 기준: `unreal/GyroSim/Content/Python/trees_near.py`)
| 환경 변수 | 기본 | 뜻 |
|---|---|---|
| `GYROSIM_TREES_NEAR` | `0` | `1` = 켬 (`GYROSIM_TREES=0` 이면 꺼짐) |
| `GYROSIM_TREES_PROXY` | `1` | `0` = 타일 나무를 숨기고 가까운 나무만. 기본은 타일 나무도 같이 (겹침은 의도) |
| `GYROSIM_TREES_NEAR_R` | 900 m (헤드셋 또는 `GYROSIM_TREES_NEAR_VR=1` 이면 450 m) | 반경 |
| `GYROSIM_TREES_NEAR_LITE` | `1` | 가벼운 모델 하나(참나무 D, 35 만 삼각형)를 종류별로 색·모양만 바꿔 씀. `0` = 8 개 모델 |
| `GYROSIM_TREES_NEAR_SHADOW` | `1` | `0` = 그림자 끔 |
| `GYROSIM_TREES_NEAR_BUDGET_MS` | 4 | 한 프레임에 채우기에 쓰는 Python 시간 (ms) |

## 만들기
```
python -I sim/trees_near_build.py --db        나무 목록 (v2 나무와 같은 나무) -> C:/GyroSimTiles/veg/near/
python -I sim/trees_near_build.py --meshes    줄인 모델
```
무거운 CPU 작업이라 `C:/GyroSimTiles/ue_offscreen.lock` 을 잡고 코어 절반, 낮은 우선순위로 돈다 (`sim/power_rule.py`).

## 자료와 라이선스 (모두 git 밖)
| 모델 | 라이선스 |
|---|---|
| Poly Haven `pine_tree_01` (소나무 a / b / c) | CC0 1.0 |
| Quixel Megascans "Tree English Oak Forest 01" A-D, "Tree Black Alder 01" C (Fab, 사용자가 받음) | Fab 표준 라이선스 — UE 안에서만. 그래서 줄인 메시(`/Game/ThirdParty/Trees/Near/`)도 git 에 넣지 않음 |
