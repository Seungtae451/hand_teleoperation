# Phase 6 — Wuji 원본 구현 연결 및 세 방법 비교

Wuji의 고정 commit `531f6ed4250b475d2e9231f54e988fc9b1c5b4ea`에서
`Retargeter` / `AdaptiveOptimizerAnalytical`를 직접 사용한다.
DG-5F URDF와 실제 link 이름을 원본 설정 API로 지정했으며 원본 소스를 수정하지 않았다.
기존 Phase 1–5 코드도 유지하고 별도 adapter와 진입점만 추가했다.

이제 Quest 없이 **MANUS·AnyDex·Wuji**를 동일한 공개 입력·DG-5F 모델·공통 제어 설정으로 실행할 수 있다.
GeoRT 학습/추론 모델과 SHOW3D 데이터 연결은 후속 작업이다.

## 바로 실행

현재 `.venv`에 추가 의존성 설치를 마쳤다. 다른 환경에서 재현할 때는 다음을 실행한다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
uv pip install --python .venv/bin/python -r requirements/phase6.txt
uv pip check --python .venv/bin/python
```

최초 프로젝트 설치와 고정 외부 저장소 확보는 기존 README, HTTPS/WSS 의존성은
README_PHASE3.md를 따른다. Phase 6 requirements는 Phase 5의 ABI 호환 numerical stack과
SciPy 1.15.3을 고정한다. 하드웨어 송신 API를 사용하지 않아 Wuji SDK는 설치하지 않는다.
core 모듈을 checkout에서 직접 import하며 공식 package 전체 설치를 했다고 주장하지 않는다.
`uv sync`를 다시 실행했다면 추가 requirements도 다시 설치한다.

```bash
# 세 방법을 같은 공개 입력으로 순서대로 Viewer에서 확인
MUJOCO_GL=glfw .venv/bin/python scripts/run_phase6.py \
  --dataset anydex_avp1 --frames 150 --viewer

# Wuji만 확인
MUJOCO_GL=glfw .venv/bin/python scripts/run_phase6.py \
  --dataset geort_alex --methods wuji --frames 150 --viewer

# Fist 후보 구간 확인: 데이터의 정답 gesture label은 아님
MUJOCO_GL=glfw .venv/bin/python scripts/run_phase6.py \
  --dataset anydex_avp1 --start-frame 625 --frames 90 --viewer

# GUI 없이 세 방법 비교 로그·영상 생성
MUJOCO_GL=egl .venv/bin/python scripts/run_phase6.py \
  --dataset geort_alex --frames 150 --video

# 기존 Quest 녹화도 동일한 경로로 재생
.venv/bin/python scripts/run_phase6.py \
  --input recordings/quest-20261017T135937-204414Z.jsonl --frames 150
```

각 실행은 새 `results/phase6-*` 폴더를 만든다. `--output`은 존재하지 않는 새 폴더만 허용한다.
기존 `run_offline_benchmark.py` 명령은 Phase 5 동작을 유지한다.
새 `run_phase6.py`는 registry에 Wuji를 일시 등록하고 기존 공통 runner를 그대로 재사용한다.
각 방법 Viewer가 차례로 열리므로 같은 구간을 끝까지 재생한다. 중간에 닫아 입력이 달라지면
비교 성공으로 저장하지 않는다. 재현 가능한 전체 비교에는 headless 실행이 편하다.

## 원본 동작과 해석

Wuji는 별도의 알고리즘을 새로 만든 것이 아니라 원본 adaptive 구현을 재현한 것이다.
AnyDex와 공유하는 Huber/TipDirVec/FullHandVec/adaptive pinch/SLSQP 구조가 있으며,
현재 모두 1인 scale과 선택 기능이 꺼진 기본값에서는 기본 loss·gradient가 일치한다.
서로 완전히 독립적인 알고리즘으로 취급하지 않는다.

Wuji의 다음 기능은 원본 코드에서 기본적으로 비활성화되어 있다.

- Hyperextension: `w_hyper=0`, `soft_min=0`.
- DIP–PIP coupling: `w_couple=0`, `couple_ratio=0.7`은 비활성 항의 기본 상수.
- Thumb PIP 생략: `thumb_skip_pip=false`.

이 baseline은 위 기본값을 유지한다. DG-5F의 PIP/DIP는 독립 관절이며 URDF가 음수 각도도
허용하므로, Wuji Glove 예제의 positive-only soft penalty와 사람 손 coupling ratio를
DG-5F의 물리 제약으로 간주하지 않는다. 실제 PIP/DIP 관절 연결, 원본 선택 penalty의
cost·gradient는 별도 진단 테스트로 검증했다. 성능을 높이려고 weight를 변경하지 않았다.

원본 기본 LPFilter(alpha=0.2), midpoint 초기값과 warm start도 유지한다.
solver 출력과 필터 출력, 공통 URDF 제한 후 목표, 속도 제한 후 명령, 실제 상태를 구분한다.
NLopt 횟수 예산 도달(code 5)을 수렴 성공과 구분한다.

## 산출물과 검증

각 결과 폴더에는 다음을 저장한다.

- `input.jsonl`: 모든 방법이 공유한 HandFrame 입력과 출처 metadata.
- `manus.jsonl`, `anydex.jsonl`, `wuji.jsonl`: 단계별 출력·실제 상태·기구학 지표.
- `*_summary.json`, `comparison.json`: 입력 hash, 처리 시간, 지표, solver 상태.
- `*.mp4`: `--video` 실행 시 각 방법의 영상.

`common_input_stream_sha256`은 세 방법에서 동일해야 한다.
두 예제는 원본 시간 정보가 없거나 0이므로 기본 30 FPS를 **가정한 재생 시간**을 사용한다.
제어는 공통 50 Hz, physics timestep 0.002 s, 명령 속도 pi rad/s, timeout 0.25 s다.
정규화 지표와 추정 pose의 한계는 Phase 5와 동일하다. 접촉은 비활성화되어 있다.

```bash
MUJOCO_GL=egl .venv/bin/python -m pytest -q
.venv/bin/ruff check benchmark scripts tests
.venv/bin/python scripts/verify_phase6_sources.py
MUJOCO_GL=egl .venv/bin/python scripts/validate_phase6.py
```

검증 스크립트는 GeoRT 3,498프레임, AnyDex/Wuji 공용 AVP 예제 2,751프레임 전체를
세 방법으로 비교하고 짧은 영상 6개를 생성한다. 결과 위치는
`results/phase6_validation_latest.json`에, 각 실행의 측정값은 해당 폴더의 `validation.json`에 남긴다.
기존 파일 검사 기준도 `docs/phase6_existing_files.sha256.json`에 보존했다.

Wuji 저장소의 `example/data/avp1.pkl`은 Git LFS 포인터이며, 가리키는 SHA256이
확보한 AnyDex 예제와 동일하다. 두 예제를 별도 평가 시퀀스나 참가자로 중복 집계하지 않는다.
두 공개 데이터는 참가자 ID와 공식 split이 확인되지 않은 development 전용이다.

구현 차이·제약 감사·실제 측정 결과는 [PHASE6_REPORT.md](docs/PHASE6_REPORT.md)에 정리한다.
