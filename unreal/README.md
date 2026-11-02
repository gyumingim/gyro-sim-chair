# 언리얼 5.8 화면 (GyroSim)

비행 계산은 그대로 `sim/server.py` (JSBSim F-16). 언리얼은 **화면만** 그린다. C++ 없음 (Visual Studio 없어도 됨).

## 실행
1. `python sim/server.py` (브라우저 화면 http://127.0.0.1:8780/ 도 계속 됨 — 교관/HUD 화면으로 쓰기)
2. `unreal/GyroSim/GyroSim.uproject` 더블클릭 (UE 5.8). 처음 열 때 셰이더 컴파일로 몇 분 걸릴 수 있음.
3. 위쪽 **Play** (▶) 누르기. 끝내기는 Esc.

## 조종
| 입력 | 동작 |
|---|---|
| 조이스틱 (꽂혀 있으면 우선) | 축 매핑은 `sim/controls.json` (기본: 축0 롤, 축1 피치(반대), 축2 스로틀, 축3 러더). 고친 뒤 server.py 다시 시작 |
| ← → | 롤 |
| ↑ ↓ | 피치 (↓ = 당기기, 기수 올림) |
| A D | 러더 |
| W S | 스로틀 |
| B / G | 브레이크 / 바퀴 |
| R / T | 공중 시작 (6000 ft, 350 kt) / 활주로 시작 |
| V | 조종석 ↔ 뒤쪽 추적 시점 |
| P | 일시정지 |
| H | 화면 위 글자(HUD) 켜기/끄기 |

키보드는 언리얼 창이 앞에 있을 때만 읽는다 (그 동안은 브라우저 키보드가 무시됨, 0.5 초 뒤 다시 브라우저로).
우선순위: 조이스틱 > 언리얼 키보드 > 브라우저.

## 구조
```
sim/server.py (JSBSim 120 Hz) ──UDP 4220, 60 Hz 상태 JSON──▶ 언리얼 에디터 Python (Content/Python/sim_client.py)
        ▲  ◀──UDP 4221 조종/명령 JSON (웹소켓 메시지와 같은 형식)──┘      Play 중 기체·카메라 이동
        ├─ WebSocket 8781 / HTTP 8780 : 브라우저 화면
        ├─ pygame 조이스틱 (controls.json)
        └─ UDP 4210 : 의자 명령 {"roll","pitch"}
```
- `Content/Python/init_unreal.py`: 에디터가 열리면 자동으로 `sim_client.start()`.
- `sim_client.py`: 매 프레임 (Slate tick) Play 월드가 있으면 UDP 를 읽고, 위경도 → 언리얼 좌표
  (X = 북, Y = 동, Z = 위, cm, 원점 = 패킷의 lat0/lon0), 자세 (NED 오일러) → Rotator(roll=φ, pitch=θ, yaw=ψ).
  `SimCamera` 카메라 액터를 플레이어 시점으로 쓰고 조종석/추적 위치로 옮긴다.
- 맵 `/Game/Maps/FlightMap` 은 `Scripts/build_level.py` 가 기본 도형으로 만든다 (지면 400 km, 활주로 3 km × 45 m 남북,
  남쪽 끝은 원점에서 150 m 남쪽, 언덕 68 개, 하늘·태양·구름·안개, 기본 도형 비행기). 다시 만들기:
  `UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<경로>\Scripts\build_level.py` (에디터 닫고).
- `Scripts/verify_pie.py`: 자동 점검. `UnrealEditor.exe GyroSim.uproject -GyroSimVerify` 로 열면 45 초 뒤 Play 시작 →
  위치·자세 부호 확인 → 스크린샷·결과 `Saved/verify/` → Play 종료 (server.py 켜 둔 상태에서).

## 한계
- 에디터 안 Play (PIE) 에서만 동작 (Python 은 패키지 게임에서 안 돎). 에디터 Python 이 매 프레임 돌아 약간 무거움.
- 위치는 받은 최신 값 그대로 (보간 없음) — 60 Hz 라 대부분 괜찮지만 화면 주사율이 높으면 살짝 떨릴 수 있음.
- 지면은 해수면 높이 평면 (언덕은 보기용, 충돌 없음 — JSBSim 지면 고도 0 ft).
- 계기판·조종석 내부 없음. 숫자 HUD 는 화면 위 한 줄 글자 (디버그 글자라 스크린샷에는 안 찍힘).
- 지면은 20 km 판 400 장 (400 km 판 한 장은 높은 곳에서 안 그려지는 문제가 있었음).

## 다음 단계
- Visual Studio 설치 후 C++ 프로젝트로 바꾸고 JSBSim 언리얼 플러그인 (JSBSimFlightDynamicsModel) 으로 비행 계산을 언리얼 안으로.
- VR: OpenXR 플러그인은 이미 켜 둠 — 헤드셋 연결 후 VR Preview, 카메라를 조종석 시점에 붙이기.
- 의자 제어기: UDP 4210 `{"roll","pitch"}` 를 받아 모터로 보내기, 탑승해서 큐 값 조정.
- 실제 지형 (Cesium for Unreal 또는 하이트맵), 공항 모델, 계기판 UMG.
