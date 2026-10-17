# Phase 1·2 실행 결과

검증일: 2026-10-17 (Asia/Seoul). 실제 로봇 하드웨어 검증은 수행하지 않았다.

## Phase 1 — Repository Investigation

### 구현한 기능과 조사 결과

- 필수 GitHub 저장소 7개와 스트리머가 안내하는 별도 Python SDK 1개를 확보했다.
- 실제 코드·설정·라이선스·환경 선언을 확인하고 전체 commit SHA를 고정했다.
- 공식 DG-5F URDF의 link/joint/axis/limit/tip/mimic 여부와 기존 로컬 URDF 일치를 확인했다.
- Quest의 실제 전송값, MANUS 코드의 clipping 문제, AnyDex/Wuji 확장 경로,
  GeoRT의 학습 의존성 및 미구현 collision loss를 문서화했다.
- 원본 변경 없이 adapter와 별도 파생 모델을 사용하는 구현 계획을 점검한 뒤 진행했다.

### 생성한 파일

`external_repositories.lock.json`, `scripts/fetch_external.py`, `scripts/verify_sources.py`,
`docs/REPOSITORY_AUDIT.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/original_files.sha256.json`.
다운로드한 checkout은 `external/`에 있으며 sparse 범위와 submodule 상태를 lock 파일에 기록했다.

### 실제 실행 결과

`scripts/fetch_external.py`의 고정 commit 검증과 `scripts/verify_sources.py --original`을 실행했다.
외부 8개 저장소 모두 pinned revision과 일치하고 working tree가 clean이었다.
기존 파일 **261개**의 SHA-256도 모두 작업 시작 전 값과 일치했다.

### 남은 문제와 다음 단계

외부 retargeter와 Quest SDK의 런타임 설치/입력 검증, GeoRT 전용 CUDA/SAPIEN 환경 구성은
각 Phase에 남겨두었다. repository metadata 조사와 실제 학습/추론 가능 확인을 혼동하지 않는다.
Phase 3부터 Quest SDK를 adapter로 연결한다. 원본 코드 수정 필요 시 사용자에게 먼저 확인한다.

## Phase 2 — Tesollo MuJoCo Model

### 구현한 기능

- 공식 오른손 URDF → 별도 MJCF bundle 생성, 원본·파생 파일 해시 및 라이선스 보존
- fixed palm/tip frame 보존, 20개 독립 position actuator와 URDF effort/angle 제한
- 20개 목표각 검증/선택적 clipping, actuator 동역학 실행과 reset
- 독립 MjData 기반 5개 tip world/palm FK 및 `(5,3,20)` world translational Jacobian
- q_target/q_command/q_actual, 명령 FK/실제 tip을 구분한 CSV/JSONL 기록과 동일 명령 재생
- GUI Viewer, EGL 렌더링, MP4 녹화
- 후속 Quest 공통 HandFrame과 네 retargeter의 공통 인터페이스/registry

### 생성한 파일

| 경로 | 역할 |
|---|---|
| `pyproject.toml`, `uv.lock`, `.gitignore` | 설치·의존성 고정·생성물 관리 |
| `configs/tesollo_right.json` | 실제 joint/link order와 시뮬레이션 설정 |
| `benchmark/simulation/` | URDF 파싱/FK, 변환, 공통 모델, 동역학 runner, Viewer/renderer |
| `benchmark/tracking/hand_frame.py` | 실제 21-point 계약과 full skeleton 선택 mapping |
| `benchmark/retargeting/` | 공통 reset/retarget/result 및 네 독립 adapter 등록 지점 |
| `benchmark/experiments/`, `benchmark/cli.py` | 합성 관절 데모, logger, 재생 CLI |
| `tests/` | 모델·관절·FK/Jacobian·제어·입력·재생·렌더링·GUI 검증 |
| `scripts/validate_phase2.py` | 수용 조건 실측 및 PNG/MP4/JSON/CSV 생성 |
| `README.md`, `docs/ROBOT_MODEL.md`, `requirements/README.md` | 재현 방법·좌표계·환경 분리 |
| `assets/tesollo/generated/` | 재생성 가능한 MJCF, normalized URDF, STL, 출처, LICENSE |
| `results/phase2_*`, `results/pytest.xml` | 실제 실행 산출물 |

기존 파일 수정은 없으며 모두 새 프로젝트 파일 또는 별도 생성물이다.

### 실제 테스트 결과

환경: Python 3.10.12 / MuJoCo 3.16.0 / NumPy 2.2.6 / EGL / NVIDIA RTX 5080.

| 검증 | 실제 결과 |
|---|---|
| pytest 전체 | **66 passed**, 2.25초, skip 없음 |
| Ruff check 및 format check | 통과 |
| 자유도·actuator | nq=20, nv=20, nu=20 |
| URDF joint limits/axis/frame | 원본과 일치; fixed link 포함 |
| 독립 URDF FK, 무작위 100 자세 | 최대 좌표 성분 오차 `8.326672684688674e-17 m` |
| 20개 개별 관절 2초 정착 시험 | 목표 대비 최대 절대 오차 `8.326672684688674e-17 rad` |
| Jacobian 20개 열 | finite difference와 일치, 다른 손가락에 영향 없음 |
| 경계·입력 검사 | 양 끝 limit 허용, 초과값 거부/명시 clipping, NaN/Inf/shape 거부 |
| 4초 합성 명령 재생 | 200프레임 q_actual 차이 `0.0 rad` |
| 생성 bundle 이동 | 다른 디렉터리에서 MJCF와 normalized URDF 모두 로드 통과 |
| 렌더링 | 실제 hand pixels 및 손가락 움직임 검증; PNG 육안 확인 |
| GUI Viewer | 창 열기·시뮬레이션·자동 닫기 후 프로세스 exit code 0 |
| 녹화 | 640×480, 50 FPS, 200프레임 MP4 생성 후 decode 확인 |

위 정착 시험은 **중력 보상, 접촉 비활성화, ±0.15 rad 수준의 개별 step 명령** 조건이다.
매우 작은 정착 오차는 이상화된 시뮬레이션의 수치 결과이며 하드웨어나 retargeting 정확도가 아니다.
제어기 gain, timestep 및 조건은 provenance와 `results/phase2_validation.json`에 기록했다.
같은 CPU/버전/조건에서의 재생을 확인한 것으로 서로 다른 환경에서 bitwise 동일함을 보장하지 않는다.

### 재현

```bash
python3 scripts/fetch_external.py
uv sync --locked --python 3.10
MUJOCO_GL=egl .venv/bin/python -m pytest -q --junitxml=results/pytest.xml
MUJOCO_GL=egl .venv/bin/python scripts/validate_phase2.py
MUJOCO_GL=glfw .venv/bin/python -m benchmark demo --duration 20 --viewer
```

### 남은 문제

- 현재 모델은 오른손 한 종류다. 왼손·short/tactile 모델은 별도 검증이 필요하다.
- STL 기반 시각 형상이다. DAE material/texture를 재현하지 않는다.
- fingertip 값은 URDF tip frame 원점이다. 패드 표면 중심 및 contact offset은 미정의다.
- contact 기본 비활성, 중력 보상 사용. 자기충돌·물체 파지/접촉 안정성 검증은 미완료다.
- URDF velocity 제한을 보장하는 trajectory controller는 아직 없다.
- Quest 실시간 수신과 사람 손 녹화/replay, 네 retargeter는 미구현이다.
  registry에서 미구현 알고리즘을 요청하면 명시적으로 실패한다.

### 다음 단계

Phase 3에서 SDK 수신, timestamp pairing, timeout 기반 tracking loss, wrist/palm 좌표 변환,
입력 recorder/replay를 구현한다. 이후 Phase 4 MANUS adapter부터 동일한 canonical joint order,
동일한 모델, 동일한 입력 데이터에서 연결한다. AnyDex와 Wuji의 공통 loss/추가항은 별도로 기록하고,
GeoRT는 Tesollo 5-finger 설정과 전용 학습을 완료한 뒤 비교한다.
