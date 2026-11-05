# 시뮬레이터 프로토타입 (Python + 브라우저)

언리얼로 가기 전에 빠르게 만든 첫 버전. 비행 모델은 JSBSim F-16 (언리얼로 옮겨도 같은 JSBSim 을 쓸 수 있음).

```
pip install jsbsim websockets pygame pillow
python sim/server.py          # → http://127.0.0.1:8780/
```

- `airfield.py`: 시작 비행장 = 청주 기지 RKTU 활주로 06R (실제 좌표, 방위 052.38°, 표고 191 ft, 지오이드 25.08 m — 출처는 파일 안).
  JSBSim 땅 높이 = 191 ft (어디나 평지). 활주로 시작·착륙 접근(9 km 앞, 1740 ft)이 이 활주로 기준.
- `server.py`: JSBSim 120 Hz, 공중 시작은 수평 비행 트림 (6000 ft, 350 kt, 방위 000). WebSocket 8781 로 상태 60 Hz 전송, 조종 입력 받음.
- 의자 명령 (`simcore.py`): 기체 자세·가속에서 만든 목표를 실제 의자 한계로 제한 — 좌우 ±18° / 앞뒤 ±14°, 최대 속도 1.3 / 0.95 °/s,
  가속 0.6 / 0.48 °/s², 0.5 s 저역 통과 (하드웨어 담당 값, 11-04). UDP JSON `{"roll":..,"pitch":..}` 을 127.0.0.1:4210 으로 보냄.
- `web/index.html`: three.js 화면 + HUD, 조이스틱(Gamepad API, 축 매핑은 패널에서 고르고 브라우저에 저장) 또는 키보드.
  키보드: ← → 롤, ↑ ↓ 피치 (↓ = 당기기), A D 러더, W S 스로틀, B 브레이크, G 바퀴, V 시점, P 일시정지.
- 언리얼 화면 (`unreal/README.md`): 같은 상태를 UDP JSON 127.0.0.1:4220 으로 60 Hz 전송 (실제 적용된 조종 입력 ail/elev/rud/thr/brk_l/brk_r, 바퀴 접지 wow,
  강의 상태 tut 포함), UDP 4221 로 조종/명령 JSON 받음 (`{"cmd":"pause"}` = 토글, `{"cmd":"pause","on":true|false}` = 지정 — 언리얼 Play 시작 때 씀).
- `training/`: 교관. 강의 0~10 (오리엔테이션 · 자세 · 수평 직진 · 출력 · 상승강하 · 선회 · 복합 · 이륙 · 장주 · 착륙 · G/롤), 강의마다
  브리핑 → 시범 (자동 조종이 실제 조종 장치를 움직임, `autopilot.py`) → 연습 (코칭: 틀린 방향 경고, 칭찬, 다시 말하기 간격) → 단독 점검 (점수) → 결과 (잘한 점 · 고칠 점 · 그래프).
  메뉴 (키보드 / 스틱 + 버튼), 훈련생 기록 `profiles/<이름>.json` (git 제외), 쉬운 모드 (자세 보조) · 느린 시간, 사고 설명 + 바로 다시, 키보드 / 조종 장치 말투 자동.
  `lessons.py` = 강의 내용 (한 곳), `engine.py` = 진행, `render.py` = 한글 훈련 화면 PNG (`out/tut_panel_*.png`, 언리얼 가운데 화면·브라우저), `voice.py` = SAPI 음성.
  `tutorial.py` 는 예전 이름 호환용.
- 시험: `playtest/run.py` (학생 봇 잘함 · 서툼 · 반대로, 오프라인, `playtest/README.md`), `test_live.py` (켜진 서버), `playtest/soak.py` (1 시간, 서버 재시작 포함).
  설명서: `docs/sim-tutorial.html` (훈련생), `docs/sim-operator.html` (운영자).
- `key_panel.py`: 언리얼 조종석 오른쪽 키 안내판 그림 `key_panel.png` 를 만듦 (한 번, git 에 있음). 키를 바꾸면 다시 실행.
- `vworld_proxy.py`: 브이월드 항공사진 로컬 타일 프록시 (127.0.0.1:8790, 키·캐시·하루 예산·약관 3일 캐시). `server.py` 가 언리얼 땅 모드가 `vworld` 일 때 같이 켬.
  `--status` 상태, `--selftest` 규칙 점검 (실제 호출 없음). 자세히: `../unreal/README.md` "V-World 모드", `../docs/vworld-integration.md`.
- 조이스틱: pygame (`pip install pygame`), 축 매핑은 `controls.json`. 꽂혀 있으면 그 축은 브라우저/언리얼 입력보다 우선.
  언리얼 창이 앞에 있어도 동작 (SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1).

남은 것: 의자 큐 값 실제 탑승으로 조정, 강의 조건값을 실제 초보자로 조정 (지금은 학생 봇으로만 확인함).
