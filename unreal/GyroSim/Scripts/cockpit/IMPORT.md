# 조종석 v3 (11-05) 언리얼에 넣기

새 형상은 **대기 폴더** `unreal/GyroSim/Art/Cockpit_v2/` 에만 있다 (지금 쓰는 `Art/Cockpit/` 는 그대로).
에디터를 **닫은 뒤** 아래 순서로 넣는다. 열린 에디터에서 맵을 다시 만들면 에디터가 죽은 적이 있다 (README).

## 바뀐 것 / 안 바뀐 것
- 바뀜: 글레어 실드(위에서 보면 U 자로 패널 위로 튀어나온 덮개, 무광 검정, 고무 테두리), HUD (받침대 + 팔각 결합 유리 + 얇은 금속 테두리 + 가는 버팀대 2 개),
  화면 3 개 테두리에 네모 버튼 줄, 가운데 화면 양옆 키패드 3x3, 패널 바깥쪽 30° 접힘, 다리 사이 좁은 가운데 받침, 왼쪽 노랑·검정 비상 손잡이.
- 그대로: 파트 이름 (`ck_shell`, `ck_glass`, `ck_stick` …), 피벗·바늘·ADI 축·화면 사각형·경고등 (`manifest.json` 의 pivots / needles / screens / lights / travel 이 기존과 같음 — 비교 확인함),
  HUD 광학면 (`hud_combiner` 의 base / fwd / up / w / h0 / h1 / r 같음 → `build_level.py` 의 HUD 자르기 그대로 맞음). 새 키 `hud_combiner.poly` (유리 팔각형) 만 추가.
- 재질 칸: 새 칸 없음 (`CK_White` 가 ck_shell 에 새로 쓰였지만 `ue_cockpit.CK_SLOTS` 에 이미 있음).
- 삼각형: 내보낸 파일 기준 103,825 개 (지금 쓰는 것 84,193 개, +23%).

## 순서 (에디터 닫은 뒤, 저장소 루트에서)
```
# 1) 대기 폴더 → 실제 폴더 (텍스처 아틀라스·라벨은 안 바뀜, 구운 마스크만 바뀜)
copy /Y unreal\GyroSim\Art\Cockpit_v2\*.fbx            unreal\GyroSim\Art\Cockpit\
copy /Y unreal\GyroSim\Art\Cockpit_v2\manifest.json    unreal\GyroSim\Art\Cockpit\
copy /Y unreal\GyroSim\Art\Cockpit_v2\tex\T_CkShellMasks.png unreal\GyroSim\Art\Cockpit\tex\

# 2) 맵 다시 만들기 (README "처음 한 번" 마지막 줄과 같음)
"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" unreal\GyroSim\GyroSim.uproject -run=pythonscript -script=<전체경로>\unreal\GyroSim\Scripts\build_level.py -unattended -nosplash -nullrhi
```
피벗·화면 위치가 안 바뀌었으므로 2) 대신 에디터를 연 뒤 `exec(open(r"<project>/Scripts/cockpit/ck_reimport.py").read())` 로 메시만 다시 가져와도 된다
(HUD 재질은 그대로 두는 것이라 이때는 새 `poly` 키가 안 쓰임 — 원래도 안 씀).

되돌리기: `git checkout -- unreal/GyroSim/Art/Cockpit` 후 같은 2) 단계.

## 확인할 것
1. 가져오기 로그: `ck_shell UV channels: 3`, `cockpit: no material for slot` 이 **없을 것**, `cockpit placed:` 목록에 파트 21 개.
2. `UnrealEditor.exe GyroSim.uproject -GyroSimVerify` (server.py 켠 상태) → `Saved/verify/verify_result.json` 전부 통과: 바늘·ADI·기어 손잡이·바퀴 등·경고등.
3. 눈 시점 스크린샷: HUD 글자가 유리 안에 있고 옆·위 가장자리에서 잘리는지 (유리가 팔각형이라 **아래 모서리·위 모서리 삼각형 부분에서는 글자가 유리 밖에 조금 보일 수 있음** — 자르기는 아직 둥근 사각형 기준).
   가운데 화면 맨 위 버튼 줄이 덮개 테두리 아래로 보이는지 (Blender 렌더에서는 보임, 테두리 위 끝 시선 여유 약 0.7 cm 계산값 — 눈 위치 `RIG_EYE` 는 추정값이라 VR 에서 머리를 낮추면 가릴 수 있음).
4. 화면 3 개 그림이 새 테두리 구멍 안에 딱 맞는지 (화면 판 위치 그대로, 구멍 15.3 / 24.3 cm).
5. 초보자 모드 한글 이름표 (adi·asi·alt·vsi·gear·wheels·lights) 가 버튼·테두리에 안 가리는지 (스크립트가 겹침 검사함: 경고 0 개).
6. `Scripts/measure_fps.py` 로 GPU / 게임 스레드 시간 (삼각형 +23%) — README 성능 표와 비교.

## 남은 선택 (안 한 것)
- HUD 자르기를 팔각형에 정확히 맞추려면 `build_level.py` 의 `HUDCLIP_HLSL` 을 `hud_combiner.poly` (유리면 좌표 (가로, 위로) cm, base 기준) 로
  다각형 안팎 판정하도록 바꾸면 된다. 지금은 바깥 사각형 그대로라 글자가 잘리는 일은 없고, 모서리에서 유리 밖에 조금 보일 수만 있다.
- 키패드·테두리 버튼은 장식 (기능 없음). 빼려면 `model_blender.py` 의 `DECOR_KEYS = False`.

## 다시 만들기
```
python unreal\GyroSim\Scripts\cockpit\build_cockpit.py                 # 텍스처 (Art/Cockpit/tex) + 형상 → Art/Cockpit_v2 (대기)
python unreal\GyroSim\Scripts\cockpit\build_cockpit.py --out unreal\GyroSim\Art\Cockpit   # 에디터 닫혀 있을 때 바로 실제 폴더로
```
주의: `build_cockpit.py` 는 먼저 `make_textures.py` 로 `Art/Cockpit/tex` (실제 폴더) 를 다시 쓴다 — 에디터가 열려 있으면 `model_blender.py` 만 직접 돌린다:
`blender -b --factory-startup -P unreal\GyroSim\Scripts\cockpit\model_blender.py -- [--no-bake]`.
Blender: `C:/Users/a3162/tools/blender/blender-4.5.15-windows-x64/blender.exe` (항상 `-b` 배경 실행). 마스크 굽기 약 80 초, `--no-bake` 면 약 5 초.
