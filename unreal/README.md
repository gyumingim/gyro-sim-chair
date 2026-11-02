# 언리얼 5.8 화면 (GyroSim)

비행 계산은 그대로 `sim/server.py` (JSBSim F-16). 언리얼은 **화면만** 그린다. C++ 없음 (Visual Studio 없어도 됨), 에디터 Python 으로 동작.
모니터와 VR 둘 다 된다. 강의(튜토리얼)·조종석 스틱/스로틀/페달 포함. 설명서: `docs/sim-tutorial.html` (서버 켜면 http://127.0.0.1:8780/docs/sim-tutorial.html).

## 실행
1. `python sim/server.py` (브라우저 http://127.0.0.1:8780/ 은 계속 됨 — 교관/강의 화면으로 쓰기)
2. `unreal/GyroSim/GyroSim.uproject` 더블클릭 (UE 5.8). 처음 열 때 셰이더 컴파일로 몇 분 걸릴 수 있음.
3. **모니터**: 위쪽 **Play** (▶). **VR**: Play 옆 ▾ → **VR Preview** (헤드셋 + OpenXR 런타임 필요: SteamVR / Meta Quest Link / WMR 중 하나를 "활성 OpenXR 런타임"으로).
   끝내기는 Esc.

## 조종 (언리얼 창이 앞에 있을 때)
| 키 | 동작 |
|---|---|
| ← → / ↑ ↓ | 스틱 좌우 / 밀기·당기기 (↓ = 당기기). 누르고 있으면 천천히 끝까지, 놓으면 가운데로 |
| A D | 러더 페달 |
| W S | 스로틀 |
| B | 브레이크 (페달 윗부분 기울어짐) |
| G | 바퀴 올림/내림 |
| R / T | 공중 시작 (6000 ft, 350 kt) / 활주로 시작 |
| V | 조종석 ↔ 뒤쪽 추적 시점 |
| C / Q E | (모니터) 아래 보기 — 스틱·페달·스로틀 확인 / 왼쪽·오른쪽 보기 |
| P / H | 일시정지 / HUD 글자 끄기 |
| F1, 1~6, N, M, F2 | 강의 메뉴, 강의 시작, 다음 단계, 다시, 강의 끄기 |
| F3 / F9 | VR 정면 다시 맞추기 / VR 스테레오 켜기·끄기 (`stereo on/off`) |

조이스틱이 꽂혀 있으면 그 축이 먼저 (`sim/controls.json`). 우선순위: 조이스틱 > 언리얼 키보드 > 브라우저.

## 무엇이 어떻게
```
sim/server.py (JSBSim 120 Hz) ─ UDP 4220, 60 Hz 상태 JSON (조종 입력 ail/elev/rud/thr/brk, 강의 상태 tut 포함) → 언리얼 (Content/Python/sim_client.py)
        ↑ └ UDP 4221 조종/명령 JSON ({"ctrl"}, {"cmd":"reset"|"pause"|"tut"})  ←──────┘
        ├─ sim/tutorial.py : 강의 판정 + 한글 강의판 PNG (sim/out/) → 언리얼 조종석 판에 텍스처로
        ├─ WebSocket 8781 / HTTP 8780 : 브라우저 화면 (강의 버튼 포함)
        └─ UDP 4210 : 의자 명령 {"roll","pitch"}
```
- **부드러운 움직임**: 패킷의 sim 시간 t 로 보간 (약 20 ms 뒤를 그림, 늦으면 50 ms 까지 외삽). 120 fps 화면에서 프레임마다 움직임
  (점검: 보간 켬 = 프레임당 이동 변동계수 0.06~0.17, 끔 = 1.0 / 절반 프레임이 멈춤).
- **조종석**: 기체 기준점 = JSBSim 위치. 눈 위치 `EYE = (430, 0, 100) cm`. 카메라 리그(`SimCamera`)가 눈 위치·기체 자세로 움직이고,
  그 위에 HUD 글자(TextRender)와 강의판이 붙어 있어서 **VR 에서도 보인다** (print_string 은 VR 에서 안 보임).
  VR 에서는 헤드셋이 카메라(`SimView`)를 움직여 고개 돌리기가 그 위에 더해진다 (트래킹 원점 = 앉은 머리 위치, F3 로 다시 맞춤).
- **움직이는 조종 장치**: 서버가 실제로 적용한 값으로 움직임 (조이스틱도 반영). 스틱 ±18°/±14°, 스로틀 레버 ±25°, 페달 ±6 cm, 토 브레이크 18°.
- **화질 설정** (`sim_client.apply_preset`): 헤드셋이 켜지면 자동 전환.
  - 모니터: Lumen GI·반사, 가상 그림자맵(VSM), TSR, 볼류메트릭 구름.
  - VR: Lumen 끔(스카이라이트+SSR), 일반 그림자맵, TAA, 구름 샘플 줄임. Forward 렌더링은 안 씀 (셰이더 전체 재컴파일, 구름·안개 품질 손해). Instanced Stereo 켬.
- **지형** `Scripts/build_level.py`: 160 km 높이 지형 (Geometry Script, 산 최대 약 1200 m, 활주로 주변은 평지), 밖은 평지 400 km,
  밭·숲·마을 (합친 메시 한 개씩), 활주로 표시, 재질은 마스터 재질 `M_Surface` + 인스턴스 (MI_Grass/Terrain/Asphalt …, 월드 좌표 큰 무늬 + 세부 노이즈).
  기체는 Geometry Script 회전체 동체 + 날개 평면형 + 캐노피 + 조종석 (계기판, 의자, 스틱, 스로틀, 페달).
  다시 만들기: 에디터 닫고 `UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<경로>\Scripts\build_level.py`
  (또는 열린 에디터 Python 콘솔에서 `exec(open(r"...\Scripts\build_level.py").read())`).

## 점검 도구 (server.py 켠 상태에서)
- `UnrealEditor.exe GyroSim.uproject -GyroSimVerify` : 45 초 뒤 Play → 위치·자세 부호, 조종 장치 각도, 강의판, 보간 매끄러움 점검 →
  스크린샷·`verify_result.json` 을 `Saved/verify/` 에 저장 → Play 종료.
- `Scripts/measure_fps.py` : GPU 시간 측정 → `Saved/verify/fps_<이름>.json`. `Scripts/keyboard_test.py` : 키 입력 경로 점검 (OS 키 이벤트 합성).
- 에디터 Python 원격 실행 켜 둠 (`DefaultEngine.ini`, 127.0.0.1 만) — 외부 스크립트가 열린 에디터에 명령을 보낼 수 있음.

## 성능 (RTX 5080, 에디터 PIE, 2026-11-02)
에디터 PIE 는 120 fps 로 묶여 있어서 GPU 시간으로 본다 (`fps_before.json` / `fps_after.json`). 해상도는 화면 비율(r.ScreenPercentage)로 맞춘 값.
| 장면 | 이전 GPU | 지금 GPU |
|---|---|---|
| 조종석 ~1080p (모니터 설정) | 2.8 ms | 3.3 ms |
| 추적 시점 ~1080p | 2.7 ms | 3.2 ms |
| 조종석, VR 두 눈 픽셀 수 (~7 M 픽셀, VR 설정) | 6.3 ms (모니터 설정) | 4.5 ms |

VR 90 Hz 예산 11.1 ms 안 (추정 — 픽셀 수로 흉내 낸 값, 헤드셋 실측 아님). 게임 스레드 약 4 ms (에디터 Python 포함).

## 한계
- 에디터 안 Play (PIE) 에서만 동작 (Python 은 패키지 게임에서 안 됨).
- **VR 은 실제 헤드셋으로 시험하지 않음** (이 PC 에 OpenXR 런타임·헤드셋 없음). 코드 경로(HMD 감지, 트래킹 원점, 재중심, 화질 전환)만 넣음.
- 지형은 보이기만 함 — JSBSim 땅은 해발 0 평지라 산에 부딪히지 않음. 산은 활주로·접근로에서 3.5 km 밖부터.
- 키보드는 Windows `GetAsyncKeyState` (언리얼 창이 앞에 있을 때만). 점검은 합성 키 이벤트로 함 (사람이 직접 누른 시험은 아님).
- 강의판 한글은 서버가 PIL + 맑은 고딕으로 그린 PNG (pip `pillow` 필요).

## 다음 단계
- 헤드셋 연결 후 VR Preview 실측 (fps, 눈 높이, 멀미), 필요하면 VR 설정 조정.
- Visual Studio 설치 → C++ 프로젝트 + JSBSim 언리얼 플러그인, 지형 충돌.
- 의자 제어기: UDP 4210 `{"roll","pitch"}` 수신 → 모터.
