# 플레이테스트 봇 (오프라인)

학생 봇이 강의 0~10 을 처음부터 끝까지 날아 봅니다 (브리핑 → 시범 → 연습 → 단독 점검 → 결과).
JSBSim 만 쓰고 네트워크·Unreal 은 필요 없어요. 실제보다 훨씬 빨리 돌아요 (봇 3개 × 강의 11개 ≈ 2~3 분).

```bash
set PYTHONIOENCODING=utf-8                          # (bash: export PYTHONIOENCODING=utf-8)
python sim/playtest/run.py                          # 봇 3개 × 전체 강의, 쉬운 모드 끔
python sim/playtest/run.py --bots good --lessons 9  # 하나만
python sim/playtest/run.py --assist both            # 쉬운 모드 끔 → 켬 두 번
python sim/playtest/run.py --assist on --sim-patch  # 제안한 simcore 쉬운 모드 수정을 흉내 내서
python sim/playtest/run.py --trace ...              # 로그에 0.5 초마다 비행 상태 기록
python sim/playtest/run.py ... | python sim/playtest/sumfmt.py   # 한 줄씩 보기 좋게
python sim/playtest/sumfmt.py sim/playtest/logs/summary.json     # 저장된 요약 보기
python sim/playtest/show.py sim/playtest/logs/good_L9.json 60    # 교관이 한 말
python sim/playtest/trace.py sim/playtest/logs/good_L9.json solo 3   # --trace 로그의 비행 상태
python sim/playtest/bot_tune.py sloppy              # 봇이 간단한 자세를 안정되게 잡는지 (교관 없이)
```

## 봇 (사람 모형)
자동 조종(`training/autopilot.py`)이 "하려는 조작"을 정하고, 사람처럼 흐트러뜨립니다:
반응 지연, 스틱 움직이는 속도 한계, 손 떨림(잡음), 주의가 흐트러지는 느린 흔들림, 조작 세기(gain).

| 봇 | 특징 |
|---|---|
| good | 지연 0.15 초, 떨림 작음 — 차분한 초보 |
| sloppy | 지연 0.35 초, 떨림 큼, 기수를 세게 고쳐 넘침 — 서툰 초보 |
| wrong | 단계마다 처음 몇 초 반대로 조작, 틀린 걸 보면(경사 15°/기수 5° 움직임) 또는 교관이 고쳐 주면 바로 고침. 추락한 단계는 다음에 덜 틀림 |
| clumsy | (기본 실행에는 없음) 지연 0.5 초, 아주 많이 떨림 — 점검이 너무 쉽지 않은지 보는 용도. 대부분 떨어져야 정상 |

연습에서 시간 초과 힌트 뒤 30 초가 지나도 못 하면 봇은 N(건너뛰기)을 누릅니다. 단독 점검에 떨어지면 2 번까지 다시 해요.
쉬운 모드: `--assist off|on|auto|both`. 강의 10 은 `assist=False` (60° 경사·한 바퀴 롤) 라서 하네스가 쉬운 모드를 끕니다
(engine.py 가 아직 이 표시를 안 읽어서 — `--engine-as-is` 로 지금 엔진 그대로도 볼 수 있어요).

## 결과 파일
- `logs/<봇>_L<n>[_on][_simpatch].json` — 강의 하나: 교관이 한 말(`said`), 단계 흐름(`phases`), 점검 결과(`results`: 과제별 점수·최대 벗어남, 접지 기록 `vars.td`)
- `logs/summary.json` (쉬운 모드 끔), `summary_assist_on.json`, `summary_assist_on_simpatch.json` (제안한 simcore 수정),
  `summary_assist_on_asis.json` (엔진 그대로, 강의 10 도 쉬운 모드 켬), `summary_seed2/3.json` (다른 난수, 쉬운 모드 끔) — 전체 표. 만든 시각·봇 설정·seed 포함

요약 한 줄의 칸:

| 칸 | 뜻 |
|---|---|
| passed / first_try | 통과했나 / 첫 단독 점검에서 통과했나 |
| scores, best, tries | 단독 점검 점수들(시도 순서), 최고 점수, 시도 횟수 (통과 70 점, 모든 과제 완료해야 통과) |
| crashes, crash_why | "다시 해 봐요" 횟수와 이유 (너무 낮음, G 초과, 활주로 이탈 …) |
| skips | 연습에서 봇이 N 으로 건너뛴 단계 수 |
| coach | 연습 중 교관이 고쳐 준 말 횟수 ("… — …" 형식, 단계 안내문 제외) |
| wrong_end | wrong 봇: 반대 조작이 어떻게 끝났나 — self(스스로 알아챔) / coach(교관 말 듣고) / time(시간 지나서) |
| praise | "좋아요" 횟수 |
| touchdown | 강의 9 접지 순간: vs 강하율 fpm, e 중심선에서 m, n 문턱 뒤 m, theta 기수 각도, kts 속도 |
| fails | 마지막 시도에서 못 끝낸 과제 |
| sim_min / wall_s | 비행 시간(분) / 실제 걸린 시간(초) |
