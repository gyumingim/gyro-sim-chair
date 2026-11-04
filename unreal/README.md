# 언리얼 5.8 화면 (GyroSim)

비행 계산은 그대로 `sim/server.py` (JSBSim F-16). 언리얼은 **화면만** 그린다. C++ 없음 (Visual Studio 없어도 됨), 에디터 Python 으로 동작.
모니터와 VR 둘 다 된다. 시작 위치 = **청주 기지(RKTU) 활주로 06R** (실제 좌표·방향 052°, 표고 191 ft).
설명서: `docs/sim-tutorial.html` (서버 켜면 http://127.0.0.1:8780/docs/sim-tutorial.html). 외부 자료 출처·라이선스: `GyroSim/ATTRIBUTION.md`.

## 처음 한 번 (설치)
git 에는 스크립트만 있다. 큰 파일·외부 자료는 각자 받는다 (모두 .gitignore).
```
powershell -ExecutionPolicy Bypass -File unreal\GyroSim\Scripts\install_cesium.ps1   # Cesium for Unreal 2.31 (UE 5.8, 약 1.3 GB 받음)
python unreal\GyroSim\Scripts\fetch_f16_model.py                                     # FlightGear F-16 모델 → OBJ (GPL-2.0, 약 30 MB)
python unreal\GyroSim\Scripts\fetch_textures.py                                      # Poly Haven 사진 텍스처 (CC0)
"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" unreal\GyroSim\GyroSim.uproject -run=pythonscript -script=<전체경로>\unreal\GyroSim\Scripts\build_level.py -unattended -nosplash -nullrhi
```
(마지막 줄 = 맵 다시 만들기. 에디터를 닫고 돌린다 — 열린 에디터 안에서 돌리면 맵을 다시 읽다가 에디터가 죽은 적 있음.)

## 실제 지형 켜기 — Cesium ion 토큰 (사용자가 할 일)
토큰이 없으면: **평평한 땅 + 위성사진**(Sentinel-2, 10 m 해상도) 으로 돈다. 산은 안 보임. HUD 위쪽과 오른쪽 MFD 에 노란 글씨로 알려 줌.
토큰을 넣으면: **Cesium World Terrain (실제 산) + Bing 항공사진**.
1. https://ion.cesium.com 에서 무료 가입 (Community 요금제, 카드 필요 없음).
2. 로그인 후 위 메뉴 **Access Tokens** → **Create token** → 이름 아무거나, 권한은 기본값(assets:read) 그대로 → Create.
   (기본으로 있는 "Default" 토큰을 써도 된다.)
3. 토큰 문자열(eyJ… 로 시작하는 긴 글자)을 복사해서 새 텍스트 파일 `unreal/GyroSim/Config/cesium_token.txt` 의 **첫 줄**에 붙여 넣고 저장.
   (git 에 안 올라가게 막아 둠. 둘째 줄에 `photoreal` 이라고 쓰면 Google 사실적 3D 타일 — 더 무겁다.)
4. Play 를 다시 누른다. 토큰이 틀렸거나 인터넷이 안 되면 20 초 뒤 자동으로 평평한 땅으로 돌아가고 HUD 에 "CESIUM TERRAIN FAILED" 가 뜸.

## 실행
1. `python sim/server.py` (브라우저 http://127.0.0.1:8780/ 은 계속 됨 — 교관/강의 화면으로 쓰기)
2. `unreal/GyroSim/GyroSim.uproject` 더블클릭 (UE 5.8). 처음 열 때 셰이더 컴파일로 몇 분 걸릴 수 있음.
3. **모니터**: 위쪽 **Play** (▶) → **새 창**으로 열리고 화면 크기로 커짐. **F11** = 전체 화면. **VR**: Play 옆 ▾ → **VR Preview**. 끝내기는 Esc.

## 조종 (언리얼 창이 앞에 있을 때)
| 키 | 동작 |
|---|---|
| ← → / ↑ ↓ | 스틱 좌우 / 밀기·당기기 (↓ = 당기기). 누르고 있으면 천천히 끝까지, 놓으면 가운데로 |
| A D / W S / B / G | 러더 페달 / 스로틀 / 브레이크 / 바퀴 올림·내림 |
| R / T | 공중 시작 (6000 ft, 350 kt, 방위 000) / 활주로 06R 시작 |
| V | 조종석 ↔ 뒤쪽 추적 시점 |
| C / Q E | (모니터) 아래 보기 / 왼쪽·오른쪽 보기 |
| P | 일시정지 |
| **H** | 강의판 켜기/끄기 (왼쪽 아래 작은 판) |
| **K** | 키 안내판 켜기/끄기 (오른쪽 아래 작은 판, 처음엔 켜짐. 그림 = `sim/key_panel.png`, 고치면 `python sim/key_panel.py`) |
| **U** | HUD 켜기/끄기 |
| F1, 1~6, N, M, F2 | 강의 메뉴, 강의 시작, 다음 단계, 다시, 강의 끄기 |
| F3 / F9 / F11 | VR 정면 다시 맞추기 / VR 스테레오 켜기·끄기 / 전체 화면 |

조이스틱이 꽂혀 있으면 그 축이 먼저 (`sim/controls.json`). 우선순위: 조이스틱 > 언리얼 키보드 > 브라우저.

## 무엇이 어떻게
```
sim/server.py (JSBSim 120 Hz) ─ UDP 4220, 60 Hz 상태 JSON → 언리얼 (Content/Python/sim_client.py)
        ↑ └ UDP 4221 조종/명령 JSON  ←───────────────────────────────────────────┘
        ├─ sim/airfield.py : 청주 활주로 좌표·표고·지오이드 (서버·언리얼 공용)
        ├─ sim/tutorial.py : 강의 판정 + 한글 강의판 PNG → 조종석 판
        └─ WebSocket 8781 / HTTP 8780 : 브라우저 화면, UDP 4210 : 의자 명령
```
- **좌표**: 시작점(활주로 06R 문턱에서 150 m) = 원점, X 북 / Y 동 / Z 위, WGS84 타원체 기준 정확한 접평면 (`geo.py`) = Cesium 좌표계를 90° 돌린 것.
  그래서 기체·활주로·Cesium 지구가 같은 곡률 위에 있다 (50 km 가면 땅이 196 m 내려감). JSBSim 고도 + 지오이드 25.08 m = Cesium 높이.
- **기체**: FlightGear F-16 (GPL-2.0) 의 겉모습 + 조종석 안 (계기판, MFD, ICP, 콘솔, 사출좌석, HUD 틀). 사이드 스틱(오른쪽 콘솔)·스로틀(왼쪽)·페달이 실제 조종 값으로 움직임.
  실제 F-16 스틱은 몇 mm 만 움직이는 힘 감지식이라, 보이게 ±12°/±10° 로 키워서 보여 줌. 스로틀 80°, 페달 ±6 cm, 토 브레이크 15°.
- **HUD** (`hud.py`): 초록 전투기식 — 피치 사다리(5° 간격, 아래쪽 점선), 수평선, 비행경로 표시(FPM, 받음각·옆미끄럼으로), 보어사이트, 방위 테이프(아래), 속도·고도 상자,
  G, 마하, AOA, 수직속도, 전파고도(R), 스로틀, 기어, 브레이크, 강의 한 줄, 경고(PULL UP / TERRAIN).
  조종석 앞 20 m 에 놓인 판에 그리고 깊이 검사 없이 TSR 뒤에 합성 → 번짐 없음, 바깥 세상과 각도가 맞음 (콜리메이트), VR 에서도 보임.
  피치 사다리는 한 번 그려 둔 그림을 재질이 매 프레임 롤·피치로 찾아 그림 (Python 부담 없음). 글자·테이프·FPM 은 30 Hz.
- **MFD**: 왼쪽 = 비행 값 표 + 스로틀 막대, 오른쪽 = 기수 위 지도 (활주로 두 개, 10 km 원, RKTU 거리·방위, 지형 모드). 5 Hz.
- **활주로**: 06R/24L(45 m), 06L/24R(60 m) 두 개를 실제 좌표에 콘크리트 사진 텍스처로, 표시선(문턱, 중심선, 조준점, 접지구역, 번호). 지구 곡률을 따라 휨.
- **부드러운 움직임**: 패킷 sim 시간으로 보간 (점검: 보간 켬 = 프레임당 이동 변동계수 0.18, 끔 = 1.0 / 절반 프레임 멈춤).
- **화질 설정** (`sim_client.apply_preset`): 모니터 = Lumen·VSM·TSR·볼류메트릭 구름, VR = Lumen 끔·TAA 등 (헤드셋 켜지면 자동).

## 점검 도구 (server.py 켠 상태에서)
- `UnrealEditor.exe GyroSim.uproject -GyroSimVerify` : 45 초 뒤 Play → 위치·자세 부호, 조종 장치 각도, 강의판·H 토글, 키 안내판·K 토글, HUD 그림 수, 보간 매끄러움 →
  스크린샷·`verify_result.json` 을 `Saved/verify/` 에 저장 → Play 종료.
- `Scripts/measure_fps.py` : GPU 시간 측정 → `Saved/verify/fps_<이름>.json`. `Scripts/keyboard_test.py` : 키 입력 경로 점검.

## 성능 (RTX 5080, 에디터 PIE, 2026-11-03, 토큰 없는 평지 모드)
| 장면 | 이전 (11-02) GPU / 게임 스레드 | 지금 GPU / 게임 스레드 |
|---|---|---|
| 조종석 ~1080p | 3.3 ms / 3.9 ms | 3.4 ms / 5.2 ms |
| 추적 시점 ~1080p | 3.2 ms / 4.1 ms | 3.3 ms / 4.7 ms |
| 조종석, VR 픽셀 수 (VR 설정) | 4.5 ms / 4.1 ms (약 7.0 M 픽셀) | 4.1 ms / 5.0 ms (약 5.7 M 픽셀 — 창 비율이 달라 픽셀 수가 다름) |

모두 120 fps 상한 유지. 게임 스레드 +1 ms = HUD/MFD 그리기(Python). Cesium 실제 지형 모드는 토큰이 없어 **측정 못 함**.

## 한계
- 에디터 안 Play (PIE) 에서만 동작 (Python 은 패키지 게임에서 안 됨).
- **JSBSim 땅은 어디나 191 ft 평지**. 실제 지형 모드에서 산은 보이기만 하고 비행 모델은 모른다.
  대신 언리얼이 10 Hz 로 기체 아래를 레이 캐스트해서 HUD 전파고도(R)를 실제 지형 기준으로 보여 주고, 지형 아래로 들어가면 일시정지 + "TERRAIN" (R/T 로 다시 시작).
  착륙·이륙은 활주로(=JSBSim 땅)에서만 맞다.
- 토큰 없는 평지 모드의 위성사진은 10 m 해상도라 낮게 날면 흐림. 활주로 주변만 사진 텍스처.
- **VR 은 실제 헤드셋으로 시험하지 않음** (OpenXR 런타임·헤드셋 없음).
- Play 새 창: 기본값을 "새 에디터 창"으로 해 두고, 창이 뜨면 `sim_client` 가 창 제목 `[NetMode:` 로 찾아 최대화 (Alt+P 합성 키로 확인: 1080×1920 화면에서 최대화됨).
  점검 스크립트(-GyroSimVerify)는 Python 으로 Play 를 시작해서 뷰포트 안 Play 를 쓴다.
- F-16 모델의 계기 바늘은 기본 위치에 멈춰 있다 (MFD 두 개와 HUD 만 실제 값). 고도계 계기 하나는 FlightGear 기본 데이터라 없음.
