# Phase 5 — AnyDexRetarget 및 공개 입력 재생

원본 AnyDex `AdaptiveOptimizerAnalytical`를 DG-5F에 연결했다.
GeoRT `human_alex.npy`와 AnyDex `avp1.pkl`을 공통 `HandFrame`으로 변환해
Quest 장치 없이 MANUS·AnyDex를 같은 입력으로 비교한다.
원본 optimizer·목적함수·기본 파라미터·출력 필터는 변경하지 않았다.
이 단계는 두 방법의 개발용 비교다. Wuji·GeoRT 알고리즘은 Phase 6·7에서 연결한다.

## 설치

기존 `.venv`에서 추가 의존성만 설치한다. 기존 소스, `pyproject.toml`, `uv.lock`은 변경하지 않았다.
아래 명령은 프로젝트 루트에서 실행한다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
uv pip install --python .venv/bin/python -r requirements/phase5.txt
uv pip check --python .venv/bin/python
.venv/bin/python scripts/run_offline_benchmark.py --fetch-only
```

최초 환경은 기존 README의 `uv sync --locked --python 3.10`으로 만든다.
`uv sync`는 추가 패키지를 제거할 수 있으므로 다시 실행했다면 Phase 3과 Phase 5의
추가 requirements도 설치한다. Pinocchio 3.8.0과 호환되는 `cmeel-urdfdom` 4.0.1,
`cmeel-tinyxml2` 10.0.0을 명시적으로 고정했다. 패키지를 최신 버전으로 임의 변경하면
공유 라이브러리 ABI 오류가 발생할 수 있다. 설치 후 import와 `uv pip check`를 확인했다.

샘플은 고정 commit의 Git blob에서 읽고 SHA256을 검사한다.
각각 1,763,120 / 1,689,467 bytes이며 대규모 데이터셋 전체를 다운로드하지 않는다.
외부 sparse checkout을 변경하지 않고 `data/public/`에 사본과 원본 LICENSE를 저장한다.

## 바로 실행

```bash
# PC Viewer: 동일 공개 입력을 MANUS와 AnyDex에 순서대로 재생
MUJOCO_GL=glfw .venv/bin/python scripts/run_offline_benchmark.py \
  --dataset geort_alex --frames 150 --viewer

# 공식 AnyDex 예제로 변경
MUJOCO_GL=glfw .venv/bin/python scripts/run_offline_benchmark.py \
  --dataset anydex_avp1 --frames 150 --viewer

# 창 없이 비교 로그와 각 방법의 영상 생성
MUJOCO_GL=egl .venv/bin/python scripts/run_offline_benchmark.py \
  --dataset anydex_avp1 --frames 150 --video

# AnyDex Fist 후보가 포함된 구간 확인 (정답 label은 아님)
MUJOCO_GL=glfw .venv/bin/python scripts/run_offline_benchmark.py \
  --dataset anydex_avp1 --start-frame 625 --frames 90 --viewer

# 기존 Quest 녹화도 같은 두 방법으로 재생 가능
.venv/bin/python scripts/run_offline_benchmark.py \
  --input recordings/quest-20261017T135937-204414Z.jsonl --frames 150
```

`--methods anydex` 또는 `--methods manus`로 한 방법만 선택할 수 있다.
Viewer는 각 방법마다 새로 초기화된다. 공정한 전체 구간 비교는 창을 중간에 닫지 않고
실행하거나 headless 실행한다. 미구현 `wuji`/`geort` 선택 시 명확히 실패하며 대체 구현을 사용하지 않는다.
`--output`은 존재하지 않는 새 폴더만 허용한다.

기본 재생은 source frame index / **가정한 30 FPS**다. GeoRT에는 시간 정보가 없고
AnyDex 샘플의 `t`는 모두 0이다. `--assumed-fps`로 재생 속도를 바꿀 수 있으나
이를 실제 수집 FPS로 해석하지 않는다. 변경 시 시간 기반 동역학 결과도 달라진다.

## 출력과 해석

매 실행에서 새 `results/phase5-*` 폴더를 만든다.

- `input.jsonl`: 선택된 공통 HandFrame, 원본 frame index 및 데이터 출처/라이선스 metadata.
- `manus.jsonl`, `anydex.jsonl`: 원본 출력·공통 제한 후 목표·속도 제한 후 명령·실제 상태.
- `*_summary.json`: 처리 시간, 정규화 손끝 지표, clipping, solver 상태, 관절 변화량.
- `comparison.json`: 두 방법의 비교, 입력 hash, 데이터 감사와 분할 한계.
- `*.mp4`: `--video`를 지정한 경우 각 방법 영상.

각 방법의 `common_input_stream_sha256`이 같아야 한다. 50 Hz 제어 시각에서 마지막 source
프레임을 선택하고 같은 timeout·속도 제한·모델을 사용한다. 원본 sequence 자체는 보존한다.
목표각 지표는 새로운 입력이 소비됐을 때만 계산하고 반복 control tick으로 중복 가중하지 않는다.

AnyDex `optimizer_q_unfiltered`는 원본 solver 결과, `q_vendor_raw`는 원본 기본
LPFilter(alpha=0.2) 후 결과다. 이후 공통 URDF 제한을 적용한 값이 `retarget_q_target`이다.
필터는 알고리즘에서 제공하는 기본 동작으로 보존하며 MANUS에 임의로 같은 필터를 추가하지 않는다.
NLopt code 5는 수렴 성공과 구분해 `evaluation_budget_reached`로 보고한다.

정규화 손끝 지표는 사람 wrist 기준 palm 축과 DG-5F URDF palm 축을 정렬하고,
각 손의 wrist/palm→중지 MCP 길이로 나눈 기하학적 대응값이다.
카메라/글러브 추정 pose와 독립적인 실제 손 정답 사이의 오차가 아니며,
접촉 성공이나 물체 grasp 성공률도 아니다. 설정과 한계는 각 로그 header에 남는다.

## 데이터 감사 및 검증

```bash
MUJOCO_GL=egl .venv/bin/python -m pytest -q
.venv/bin/ruff check benchmark scripts tests
.venv/bin/python scripts/verify_phase5_sources.py
MUJOCO_GL=egl .venv/bin/python scripts/validate_phase5.py
```

전체 시퀀스 비교와 각 데이터셋의 두 방법 영상 4개를 생성하고
`results/phase5_validation_latest.json` 및 실행 폴더의 `validation.json`에 측정값을 저장한다.

기존 `verify_sources.py --original`은 초기 `PROJECT_SPEC.md` hash를 검사하므로 사용자가
요청한 17절 추가도 변경으로 표시한다. 새 `verify_phase5_sources.py`는 원래 내용의 hash가
유지된 추가인지 확인하며, 외부 저장소 8개와 기존 자산 및 Phase 5 이전 파일도 검사한다.
기존 검증 코드와 hash 기준 파일은 수정하지 않았다.

공개 샘플 둘 다 참가자 ID와 공식 split 정보가 없어 **development 전용**이다.
GeoRT 샘플은 원래 학습 예제이기도 하므로 후속 GeoRT 학습에 사용하고 같은 데이터를
held-out 평가로 사용하면 안 된다. 파일·시퀀스·알려진 참가자 중복 검사 기능을 제공하지만,
미공개 참가자 정보 때문에 subject-disjoint를 검증했다고 주장하지 않는다.

상세한 데이터 구조, 동작 후보 개수와 알려진 한계는
[PHASE5_REPORT.md](docs/PHASE5_REPORT.md)를 참고한다.
