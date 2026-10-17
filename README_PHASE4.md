# Phase 4 — 기존 MANUS 매핑 재현 및 평가

프로젝트 목적은 기존 retargeting 코드의 재현과 평가다. 성능 개선용 알고리즘이나
프로젝트별 gain/offset 보정은 추가하지 않는다. 이 원칙은 `AGENTS.md`에도 기록했다.
기존 Phase 1–3 파일과 외부 Git 소스를 수정하지 않고 별도 adapter와 실행기를 추가했다.

Tesollo의 고정 commit에서 `_compute_mqd_from_q` 계산 본문을 그대로 실행한다.
원본의 calibration gain, offset, 조건 분기를 유지한다. Quest 위치를 20개 각도로 바꾸는
입력 adapter는 별도 모듈이며, 실제 MANUS 글러브 입력과 동등하다고 주장하지 않는다.

## 바로 실행

기존 `.venv`를 사용한다. Phase 3의 HTTPS/WSS 의존성과 TLS 설정이 필요하다.
Phase 3 설치와 인증서 신뢰 방법은 [README_PHASE3.md](README_PHASE3.md)를 따른다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
MUJOCO_GL=glfw .venv/bin/python scripts/run_manus.py live --viewer --port 8024
```

PC에 MuJoCo Viewer가 열린다. Quest 브라우저에서 터미널에 출력되는 주소
(현재 PC 설정에서는 `https://192.168.100.136:8024/`)를 열고 **손 추적 시작**을 누른다.
기존 Quest XR 세션은 종료하고 새 페이지에서 시작한다. 오른손을 사용한다.
추적 손실 또는 250 ms 이상 오래된 입력에서는 마지막 적용 명령을 유지한다.
추가적인 펼친 손 보정 절차는 없다. 원본 offset 때문에 펼친 손이 로봇 영 자세와 같지 않다.
종료는 PC에서 Ctrl+C 또는 Viewer 닫기로 한다. 서버를 백그라운드로 남겨두지 않는다.
포트가 사용 중이면 `--port 8025`처럼 다른 포트를 사용하고 출력된 주소로 접속한다.

매 실행마다 새 `results/phase4-*` 폴더에 다음 파일을 저장한다.

- `quest_input.jsonl`: live에서 받은 입력 및 추적 상태 이벤트.
- `simulation.jsonl`: 원본 출력, URDF 제한 후 목표, 속도 제한 후 명령, 실제 관절/손끝 상태.
- `simulation.csv`: 목표·명령·실제 관절 상태.
- `manus.mp4`: `--video` 옵션을 지정한 경우 시뮬레이션 영상.

GUI 없이 실행하거나 녹화를 재생할 수도 있다.

```bash
# 합성 입력 Open → Close → Open → Pinch → Open
.venv/bin/python scripts/run_manus.py demo --duration 5

# 저장한 실제 입력을 그대로 사용한다. 기존 녹화 파일을 변경하지 않는다.
MUJOCO_GL=glfw .venv/bin/python scripts/run_manus.py replay \
  recordings/quest-20261017T135937-204414Z.jsonl --duration 10 --viewer

# 오프스크린 영상 + 로그 생성
MUJOCO_GL=egl .venv/bin/python scripts/run_manus.py replay \
  recordings/quest-20261017T135937-204414Z.jsonl --duration 5 --video
```

`--start`는 녹화 첫 오른손 프레임부터의 초 단위 상대 시간이다.
재생은 50 Hz 제어 시각에 도달한 마지막 입력을 사용하며 유효기간 검사도 적용한다.
`--output`으로 출력 폴더를 지정하면 새 폴더만 허용한다.

## 검증 및 현재 결과

```bash
MUJOCO_GL=egl .venv/bin/python -m pytest -q
.venv/bin/ruff check benchmark scripts tests
.venv/bin/python scripts/verify_sources.py --original
MUJOCO_GL=egl .venv/bin/python scripts/validate_phase4.py \
  --recording recordings/quest-20261017T135937-204414Z.jsonl
```

검증 시 전체 **98개 테스트 통과**. 원본 함수와 좌우 손의 무작위/분기 입력 203건에서
출력이 정확히 일치했다. HTTPS/WSS 합성 입력→시뮬레이터→추적 손실 hold 통합 테스트,
동일 녹화 재생의 결정성 테스트와 EGL 렌더링도 통과했다.
외부 저장소 8개와 기존 자산 261개, Phase 4 시작 전 프로젝트 파일 57개가 변경되지 않았다.

사용자 녹화의 오른손 유효 입력 3,236개를 처리했으며 20개 목표 관절 모두 변화했다.
이번 실행의 전처리·매핑·제한 처리 시간은 평균 약 0.126 ms, P95 약 0.134 ms였다.
이는 수신·렌더링·시뮬레이션 시간이 포함되지 않은 로컬 측정이다.

합성 pinch 입력의 엄지–검지 끝 프레임 거리는 사람 fixture 약 20.5 mm,
로봇 약 68.4 mm였다. 사람 fixture는 측정된 정답 데이터가 아니며 두 손 크기도 다르다.
이 값은 정규화 오차나 pinch 성공률이 아니다. 접촉은 비활성화되어 있어 접촉 성공을
검증하지 않았다. 원본 코드를 유지한 결과로 남기며 성능을 높이기 위한 조정을 하지 않았다.
실제 Quest→MuJoCo 실시간 동작은 사용자의 추가 확인이 필요하다.

전체 측정값과 생성 영상/PNG 폴더는 `results/phase4_validation_latest.json`에 기록한다.
이 파일은 검증할 때 최신 실행으로 갱신되며 각 실행의 `validation.json`도 별도 보존한다.

구조·입력 각도 정의·평가 범위는 [PHASE4_REPRODUCTION.md](docs/PHASE4_REPRODUCTION.md)를 참고한다.
이후 AnyDexRetarget, Wuji, GeoRT도 원본 알고리즘과 입력/모델 adapter를 구분하고
동일한 입력·모델·제어 설정으로 평가한다.
