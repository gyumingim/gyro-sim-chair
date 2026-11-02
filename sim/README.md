# 시뮬레이터 프로토타입 (Python + 브라우저)

언리얼로 가기 전에 빠르게 만든 첫 버전. 비행 모델은 JSBSim F-16 (언리얼로 옮겨도 같은 JSBSim 을 쓸 수 있음).

```
pip install jsbsim websockets pygame
python sim/server.py          # → http://127.0.0.1:8780/
```

- `server.py`: JSBSim 120 Hz, 공중 시작은 수평 비행 트림 (6000 ft, 350 kt). WebSocket 8781 로 상태 60 Hz 전송, 조종 입력 받음.
- 의자 명령: 롤 = 0.35·기체 롤 + 25·옆 가속(g), 피치 = 0.30·기체 피치 + 20·앞 가속(g), ±20° / ±15° 제한, 8°/s 속도 제한.
  UDP JSON `{"roll":..,"pitch":..}` 을 127.0.0.1:4210 으로 보냄 (의자 제어기는 아직 없음).
- `web/index.html`: three.js 화면 + HUD, 조이스틱(Gamepad API, 축 매핑은 패널에서 고르고 브라우저에 저장) 또는 키보드.
  키보드: ← → 롤, ↑ ↓ 피치 (↓ = 당기기), A D 러더, W S 스로틀, B 브레이크, G 바퀴, V 시점, P 일시정지.
- 언리얼 화면 (`unreal/README.md`): 같은 상태를 UDP JSON 127.0.0.1:4220 으로 60 Hz 전송, UDP 4221 로 조종/명령 JSON 받음.
- 조이스틱: pygame (`pip install pygame`), 축 매핑은 `controls.json`. 꽂혀 있으면 그 축은 브라우저/언리얼 입력보다 우선.
  언리얼 창이 앞에 있어도 동작 (SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1).

남은 것: 의자 큐 값 실제 탑승으로 조정, 지형/공항 실제화, 훈련 과제(이륙·선회·착륙 채점), 언리얼 이전.
