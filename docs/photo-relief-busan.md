# 땅 사진 입체 (photo relief) — 부산, 2026-11-11

V-World 정사 위성사진에서 높이를 추정해 저공에서 땅이 납작해 보이지 않게 한다. 조명(노멀)과 높이장 그림자만 바꾼다.
사진 자체는 바꾸거나 저장하지 않는다.

## 결론
- 켜짐이 기본. `GYROSIM_PHOTO_DEPTH=0` 으로 끄면 예전 모습.
- 높이 = max(AI 깊이, 작은 물체 범프).
  - AI 깊이 (Depth Anything V2 Small): 나무, 담, 헛간, 3D 메시에 없는 작은 집이 솟는다.
  - 0.24 m/px 사진에서는 **AI 가 차와 파라솔을 못 본다** (11-11 실측, 입력을 2배·3배로 키워도 같음).
    그래서 차·파라솔은 사진 밝기 덩어리로 따로 찾는다 (아래 "작은 물체").
- **3D 건물 메시가 있는 곳은 높이·노멀·그림자 모두 0** (건물 타일과 같은 GIS 외곽선 + 1.5 m).
  타일에 없는 건물은 마스크되지 않아 AI 높이가 그대로 남는다.
- 도로·모래 면은 평평하게 둔다: 국소 열림(opening) 기준선 + 0.5 m 사각지대 (dead zone, 배율 20 기준).
- 측정값은 아래 "측정" 절에 적었다. 적힌 것 말고는 측정하지 않은 "추정" 이다.

## 약관 (저장 안 함)
| 조항 | 내용 |
|---|---|
| 이용약관 13조 10항 | 서비스 내용 삭제·변경 금지 |
| 19조 4항 | 얻은 정보를 사전 승낙 없이 복사·복제·**변경**해 사용 금지 |
| 19조 6항 | 데이터 무단 저장 금지 |
| 저작권정책 | 2차적 저작물·파생 데이터·지도 타일의 공공누리 유형은 **언급 없음** |

출처: https://www.vworld.kr/v4po_prcint_a001.do , https://www.vworld.kr/v4po_prcint_a006.do

사진에서 만든 깊이·노멀 맵을 직접 다루는 조항은 없다 → 불명확 → **저장하지 않는다**.
- 작업 프로세스가 메모리에서만 계산한다 (결과 LRU 96 장, 사진 LRU 256 장).
- UE 는 GPU 렌더 타깃에만 그린다. 렌더 타깃 에셋에는 화소가 저장되지 않는다.
- 디스크·git 에는 아무것도 쓰지 않는다. 비교 그림은 git 밖 `C:\GyroSimTiles\shots\relief` 에만 둔다.

## 흐름
```
Cesium overlay URL (프록시 /vworld/sat/z19) ──▶ sim/photo_relief.py (venv, torch, 127.0.0.1 임의 포트, UE 와 함께 종료)
   GET /relief/{x18}/{y18}.png  = 512² RGBA 16bit (R 높이/32 m, G 숲 밝기 결 ±1 m, A 허용(건물 0))
        ▲ 요청 2개씩 (스레드)
Content/Python/relief_look.py ──▶ RT_GyroRelief (4096² RGBA16F, z18 8×8 장, 토러스 슬롯, 카메라 앞 300 m 중심)
                              ──▶ MPC_GyroTune 의 Rel* 벡터 (재질당 MPC 2개 한도: Coast + Tune) (RelU/V 2차식 world→창 픽셀, RelWin, RelSun, RelK, RelF)
Scripts/ground_look.hlsl 'photo relief' ──▶ 4탭 노멀 + 태양 방향 20걸음 높이장 그림자 (땅만, 바다 X)
```
- 작업 프로세스는 Play 때 `atmos_look.apply_ground` → `relief_look.start` 가 띄운다.
  - 파이썬: `GYROSIM_RELIEF_PY` (기본 `C:/Users/a3162/venvs/photodepth/Scripts/python.exe`).
  - 가중치: `GYROSIM_RELIEF_HF` (`HF_HUB_OFFLINE=1`, 로그인 없음).
  - 없으면 relief 는 꺼진 채로 둔다.
- AI 는 타일 + 사방 128 px 문맥 (768 px 창) 으로 추론한다.
  - 256 타일을 따로 추론하면 경계에 2–4 m 계단이 생겼다 (1단계 실측). 512 모자이크로는 0.03–0.08 m.

## 높이 만들기 (sim/photo_relief.py)
| 단계 | 값 |
|---|---|
| AI | Depth Anything V2 Small (Apache-2.0), 입력 770², fp16 |
| 기준선 | 깊이의 grey opening 12 m + 평활 → 12 m 보다 좁은 것만 솟음 (도로·광장 0) |
| 배율 | 20 m / 모델 단위 (사용자 11-11: 처음 5 의 4 배, **가정**: 모델은 미터를 모름) |
| 사각지대 | 0.025 × 배율 = 0.5 m 빼고 0 아래는 0 (배율을 올려도 도로 바닥 잡음 기준은 모델 단위로 같게) |
| 작은 물체 | \|밝기 − 9 m 중앙값\| > 0.12, 1.2 m 정사각 열림 (차선·횡단보도 줄 제거), 2–40 m², 식생·AI 높이 위 제외 → 1.5 m |
| 숲 결 | 식생 화소에서 밝기 − 1.7 m 평균 × 4 m (±1 m), 셰이더 `RelLum` 배 |
| 건물 마스크 | `C:\GyroSimTiles\buildings\work\_merged` (건물 타일 원본) 외곽 고리 + 1.5 m, 1 px 부드럽게 |

## 조절 (튜닝 페이지)
`RelGain` (m/단위, 기본 20), `RelNormal` (1.0), `RelShadow` (0.6), `RelLum` (0.5 m).
- 슬라이더 범위는 `sim/tune_server.py`, 기본값은 `Content/Python/tune_defaults.json` 에 있다.
- 거리 페이드 500–1100 m. 화면 화소가 0.8 m 보다 크면 점점 끈다 (반복 무늬 방지).

## 다시 만들기
- `Scripts/ground_material.py` 에 RT_GyroRelief, MPC_GyroTune 의 Rel* 벡터, Custom 입력이 추가됐다.
- 다시 만들 때는 에디터가 꺼진 상태에서 잠금을 잡고 commandlet 으로 돌린다.
- 비교 촬영: `Scripts/relief_shots.py` (아래 명령, 잠금 필요).
```
MSYS_NO_PATHCONV=1 UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -RenderOffscreen -nosplash -nosound -unattended
  "-ExecCmds=py <repo>/unreal/GyroSim/Scripts/relief_shots.py" -ABSLOG=C:/GyroSimTiles/shots/relief/ue.log
```
(Git Bash 는 `/Game/...` 를 `C:/Program Files/Git/Game/...` 으로 바꾼다 → `MSYS_NO_PATHCONV=1` 필수.)

## 측정 (11-11, RTX 5080, 화면 밖 에디터, 각 1 회)
| 항목 | 끔 | 켬 | 비고 |
|---|---|---|---|
| GPU 프레임 (해운대 해변로, 1920×1080 화소, fpschart 10 s, 배율 10 때) | 3.60 ms | 3.64 ms | 차이 +0.04 ms 는 잡음 수준. 반복 1 회라 확정 아님 |
| 비행 80 m/s, 20 s 프레임 시간 평균 / p95 / p99 | 8.71 / 9.31 / 10.9 ms | 9.87 / 16.0 / 38.2 ms | 새 타일 122 장. **끊김 있음** (아래) |
| 타일 하나: 작업 프로세스 (사진 16 장 + AI + 후처리 + PNG) | — | 평균 139 ms | GPU 추론만은 약 20 ms |
| 타일 하나: UE 게임 스레드에서 PNG 읽기 + RT 그리기 | — | 11–16 ms | 16-bit RGBA (~0.3–0.9 MB) 일 때 41–45 ms → 회색 1 채널로 줄임 |
| 월드→타일 픽셀 맞춤 오차 | — | 0.002 px | ±3 km 2차식 |

- 비행 중 끊김: 타일을 그리는 프레임마다 UE 게임 스레드가 PNG 를 디코드한다 (`import_buffer_as_texture2d`, 파이썬에서 다른 스레드로 못 옮김).
  - 프레임당 1 장으로 줄여도 p99 는 그대로였다 (37.8 ms).
  - 남은 방법: 타일을 256² (0.5 m) 로 줄이기, 창 크기·앞당김 거리 조정, C++ 비동기 업로드.
- 1단계 미리보기 (gain 5 기준): 256 타일을 따로 추론하면 경계 계단 2–4 m, 512 모자이크면 0.03–0.08 m.
  해변 대조군은 노멀 99.97 % 평평.
- 처음 두 번의 실행은 무효였다.
  1. 재질 컴파일 실패: MPC 3개 참조. 재질당 2개 한도라 Rel* 는 MPC_GyroTune 으로 옮겼다.
  2. RT 가 2048 이었다: 에셋 크기 설정이 commandlet 에서 적용되지 않았다. 이제 Play 때 4096 으로 다시 맞춘다.
- R16F RT 는 읽어 보면 값이 틀렸다. 그래서 RGBA16F 를 쓴다.

## 비교 화면
A/B 고르기 페이지: http://127.0.0.1:8767/today/busan_photo_relief_ab/ (로컬 임시 폴더, V-World 사진 포함 → git 밖).
- 장면:
  - 해운대 해변로 (차·중앙분리대 나무)
  - 광안리 해변 (파라솔)
  - 기장 주택단지 (3D 건물 타일에 없는 집들): 외곽선 마스크와 사진을 비교해 찾았다.
  - 우동 주택가 (3D 건물 많음)
- 각 장면은 전체 + 2배 확대 2장이다.

## 남은 일
- 비행 중 끊김 줄이기 (위).
- 높이 배율 20 은 **가정**이다. 실제 높이와 맞춰 보지 않았다. 차 1.5 m 는 고정값이다.
- 연석·도로 가장자리 단차는 AI 가 못 본다 (0.24 m/px 에서 연석 높이 0.15 m).
- 파라솔·차 검출은 밝기 규칙이라 놓치거나 잘못 잡는 것이 있다.
  - 길게 끊긴 차선 일부가 잡힌다.
  - 색이 바닥과 비슷한 차는 놓친다.
- 작업 프로세스는 GPU 메모리를 쓴다. torch 할당 최대 341 MB (1단계 실측) + CUDA 문맥으로 약 1 GB 이하 (**추정**). Play 를 끝내도 에디터가 꺼질 때까지 남는다.
