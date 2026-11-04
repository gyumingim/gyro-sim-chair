# 시뮬레이터 프로토타입 (Python + 브라우저)

언리얼로 가기 전에 빠르게 만든 첫 버전. 비행 모델은 JSBSim F-16 (언리얼로 옮겨도 같은 JSBSim 을 쓸 수 있음).

```
pip install jsbsim websockets pygame pillow
python sim/server.py          # → http://127.0.0.1:8780/
```

- `airfield.py`: 시작 비행장 = 청주 기지 RKTU 활주로 06R (실제 좌표, 방위 052.38°, 표고 191 ft, 지오이드 25.08 m — 출처는 파일 안).
  JSBSim 땅 높이 = 191 ft (어디나 평지). 활주로 시작·착륙 접근(9 km 앞, 1740 ft)이 이 활주로 기준.
- `server.py`: JSBSim 120 Hz, 공중 시작은 수평 비행 트림 (6000 ft, 350 kt, 방위 000). WebSocket 8781 로 상태 60 Hz 전송, 조종 입력 받음.
- 의자 명령: 롤 = 0.35·기체 롤 + 25·옆 가속(g), 피치 = 0.30·기체 피치 + 20·앞 가속(g), ±20° / ±15° 제한, 8°/s 속도 제한.
  UDP JSON `{"roll":..,"pitch":..}` 을 127.0.0.1:4210 으로 보냄 (의자 제어기는 아직 없음).
- `web/index.html`: three.js 화면 + HUD, 조이스틱(Gamepad API, 축 매핑은 패널에서 고르고 브라우저에 저장) 또는 키보드.
  키보드: ← → 롤, ↑ ↓ 피치 (↓ = 당기기), A D 러더, W S 스로틀, B 브레이크, G 바퀴, V 시점, P 일시정지.
- 언리얼 화면 (`unreal/README.md`): 같은 상태를 UDP JSON 127.0.0.1:4220 으로 60 Hz 전송 (실제 적용된 조종 입력 ail/elev/rud/thr/brk_l/brk_r, 바퀴 접지 wow,
  강의 상태 tut 포함), UDP 4221 로 조종/명령 JSON 받음 (`{"cmd":"pause"}` = 토글, `{"cmd":"pause","on":true|false}` = 지정 — 언리얼 Play 시작 때 씀).
- `tutorial.py`: 초보 비행 강의 6 개 (조종 장치 · 수평 직진 · 선회 · 상승/강하 · 이륙 · 착륙 접근), 비행 상태로 조건 판정·점수.
  명령 `{"cmd":"tut","op":"menu|start|next|restart|stop","lesson":1..6}` (브라우저 버튼, 언리얼 F1/1~6/N/M/F2).
  한글 강의판을 `out/tut_panel_*.png` 로 그려 언리얼 조종석에 보여 줌 (PIL + 맑은 고딕). 최고 점수 `out/tutorial_scores.json`.
  착륙 강의용 시작 모드 `approach` (활주로 9 km 앞, 1550 ft, 180 kt). 설명서: `docs/sim-tutorial.html` (= http://127.0.0.1:8780/docs/sim-tutorial.html).
- `key_panel.py`: 언리얼 조종석 오른쪽 키 안내판 그림 `key_panel.png` 를 만듦 (한 번, git 에 있음). 키를 바꾸면 다시 실행.
- 조이스틱: pygame (`pip install pygame`), 축 매핑은 `controls.json`. 꽂혀 있으면 그 축은 브라우저/언리얼 입력보다 우선.
  언리얼 창이 앞에 있어도 동작 (SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1).

남은 것: 의자 큐 값 실제 탑승으로 조정, 강의 조건값을 실제 초보자로 조정 (자동 조종 스크립트로만 끝까지 가는지 확인함).
