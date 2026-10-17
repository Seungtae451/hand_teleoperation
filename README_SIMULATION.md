# Quest–Tesollo Hand Retargeting Benchmark

현재 구현 범위는 **Phase 1 저장소 조사와 Phase 2 오른손 DG-5F MuJoCo 시뮬레이터**다.
공식 URDF의 독립 관절 20개를 위치 actuator로 구동하고 다섯 손끝 위치와 Jacobian을 계산한다.
Quest 실시간 수신과 네 Retargeter는 후속 단계이며 현재 데모는 합성 관절 명령을 사용한다.

외부 저장소 소스와 기존 `tesollo_model-main/`, `PROJECT_SPEC.md`는 변경하지 않았다.
앞으로 원본 Git 코드 수정이 필요하면 이유와 변경 범위를 먼저 설명하고 사용자 확인을 받는다.

## 빠른 실행

프로젝트 루트에서 실행한다. 검증 환경은 Ubuntu 22.04, Python 3.10.12,
MuJoCo 3.16.0, NumPy 2.2.6이며 ROS 설치가 필요 없다. `uv`와 `git`을 사용한다.

```bash
# 최초 설치: 조사한 모든 저장소를 고정 commit으로 확보한다.
python3 scripts/fetch_external.py
uv sync --locked --python 3.10

# 별도 모델 생성 및 관절·손끝 정보 확인
.venv/bin/python -m benchmark build
.venv/bin/python -m benchmark inspect

# 계산만 실행: 창이나 렌더링 장치가 필요 없다.
.venv/bin/python -m benchmark demo --duration 4

# 데스크톱 Viewer: 20개 actuator의 ctrl slider도 사용할 수 있다.
MUJOCO_GL=glfw .venv/bin/python -m benchmark demo --duration 20 --viewer

# 한 관절을 0.6 rad로 유지한다. --joint는 여러 번 지정할 수 있다.
MUJOCO_GL=glfw .venv/bin/python -m benchmark demo --duration 5 --viewer \
  --joint rj_dg_2_2=0.6
```

Viewer 실행은 지정한 시간 후 자동 종료된다. 데모 중에는 프로그램이 매 제어 주기마다
ctrl을 갱신하므로 수동 slider 조작은 다음 명령에 의해 덮어써진다. 독립적인 수동 조작은
`.venv/bin/python -m mujoco.viewer --mjcf=assets/tesollo/generated/dg5f_right.xml`로 실행한다.
GUI는 접근 가능한 X 디스플레이가 필요하다. 창이 없는 머신에서는 계산 또는 EGL 경로를 사용한다.

## 테스트와 재현 산출물

```bash
# 원본 저장소 8개와 작업 시작 시 기존 파일 261개의 무변경 확인
.venv/bin/python scripts/verify_sources.py --original

# FK, 20개 관절 제어, 제한/비정상 입력, Jacobian, 재생, 실제 렌더링 테스트
MUJOCO_GL=egl .venv/bin/python -m pytest -q

# 측정 보고서 + 열린 손/굽힌 손 PNG + 4초 영상 + 명령/상태 CSV·JSONL
MUJOCO_GL=egl .venv/bin/python scripts/validate_phase2.py

# 정적 검사
.venv/bin/ruff check benchmark scripts tests
```

EGL에는 시스템 EGL/OpenGL 드라이버가 필요하다. 현재 PC의 NVIDIA EGL에서 실행을 확인했다.
디스플레이가 없으면 GUI 테스트만 skip되며 EGL 렌더링 테스트는 실행한다.
렌더링 장치가 전혀 없을 때 계산 테스트는 `.venv/bin/python -m pytest -q -m 'not render'`로 실행한다.

재현 스크립트는 다음 파일을 `results/`에 생성한다.

- `phase2_validation.json`: 실제 측정치, 환경, 원본 보존 검사
- `phase2_open.png`, `phase2_flexed.png`: MuJoCo 렌더링 결과
- `phase2_demo.mp4`: 640×480, 50 FPS, 4초 영상
- `phase2_demo.jsonl`, `phase2_demo.csv`: 200프레임의 명령과 실제 상태
- `phase2_replay.jsonl`, `phase2_replay.csv`: 동일 명령 재생 결과

별도 녹화와 재생도 가능하다.

```bash
MUJOCO_GL=egl .venv/bin/python -m benchmark demo --duration 4 \
  --log results/custom.jsonl --video results/custom.mp4
.venv/bin/python -m benchmark replay results/custom.jsonl --log results/custom_replay.jsonl
```

재생은 **관절 명령 재생**이다. Quest 녹화/재생은 Phase 3에서 추가한다.
현재 재생 프로토콜은 영 자세에서 reset하고 동일 모델·제어 설정·MuJoCo 버전을 사용한다.
MuJoCo timestep 0.002초와 정확히 나누어지는 제어 FPS를 사용한다. 기본값은 50 FPS다.

## Python API

```python
import numpy as np
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.mujoco_runner import MujocoRunner

robot = RobotModel()
q_target = np.zeros(20)  # canonical order: thumb -> index -> middle -> ring -> pinky
q_target[5] = 0.6       # rj_dg_2_2, radians

# 알고리즘 출력의 기구학 평가: 시뮬레이션 상태를 바꾸지 않는다.
tips_world = robot.forward_kinematics(q_target)                 # (5, 3), meters
tips_palm = robot.forward_kinematics(q_target, frame="palm")
jacobians = robot.fingertip_jacobians(q_target)                  # (5, 3, 20)

# actuator를 이용한 동역학 실행
runner = MujocoRunner(robot)
runner.set_target(q_target)                                    # 기본: 초과값 거부
sample = runner.step(500)                                     # 1 simulated second
print(sample.q_actual, sample.tips_actual_world)

# 제한 초과 명령을 잘라 사용할 때도 원래 출력은 q_target에 남는다.
runner.set_target(q_target, clip=True)
# 실제 상태에는 soft constraint의 미세 초과가 있을 수 있으므로 잘라내지 않고 FK 계산
actual_fk = robot.forward_kinematics(sample.q_actual, enforce_limits=False)
```

`q_target`은 알고리즘의 원 출력, `q_command`는 관절 제한 적용 후 actuator 입력,
`q_actual`은 시뮬레이션 실제 관절각이다. JSONL/CSV에도 이 세 값을 분리한다.
손끝은 공식 URDF tip 링크 **원점**을 의미한다. 접촉 패드 표면 중심은 별도 정의가 필요하다.

## 구조와 확장 지점

```text
benchmark/
  tracking/hand_frame.py         21개 점, 좌표계·단위·xyzw·timestamp 계약
  retargeting/base.py            BaseRetargeter / RetargetingResult
  retargeting/registry.py        manus / anydex / wuji / geort 독립 factory 슬롯
  simulation/urdf.py             원본 파싱 및 독립 FK
  simulation/build_model.py      URDF -> 별도 MJCF 변환
  simulation/robot_model.py      공통 joint order, FK, Jacobian
  simulation/mujoco_runner.py    actuator 제어와 실제 상태
  simulation/visualization.py    Viewer / EGL 렌더러
  experiments/                  합성 데모와 관절 로그
configs/                        명시적인 로봇·제어 설정
external_repositories.lock.json 저장소 URL, commit, license, sparse 범위
external/                       원본 그대로의 고정 commit checkout
assets/tesollo/generated/        재생성 가능한 파생 모델·STL·출처
scripts/                        저장소 확보·보존 검사·수용 검증
tests/                          실행 가능한 검증
recordings/                     후속 Quest 녹화 파일
results/                        실행 산출물
```

새 adapter는 `BaseRetargeter`를 구현하고 `registry.register()`로 등록한다.
현재 네 이름으로 `create()`를 호출하면 미구현 Phase를 명시한 `NotImplementedError`가 발생한다.
원본 라이브러리는 adapter 내부에서만 import하고 출력 관절 순서는 이름으로 재배열한다.

현재 동역학 검증은 **고정 base, 중력 보상, 접촉 비활성화 상태의 자유 운동**이다.
URDF effort는 적용하고 목표각 제한을 검사하지만 velocity 제한을 보장하는 trajectory controller는
아직 없다. 접촉·자기충돌·물체 파지는 검증하지 않았다. 상세 조건은 아래 문서를 참조한다.

- [구현 전 점검한 계획](docs/IMPLEMENTATION_PLAN.md)
- [Phase 1 저장소·의존성 조사](docs/REPOSITORY_AUDIT.md)
- [관절·손끝·좌표계와 모델 변환](docs/ROBOT_MODEL.md)
- [Phase 1·2 결과와 남은 작업](docs/PHASE_REPORT.md)
