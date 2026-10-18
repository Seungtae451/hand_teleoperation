# DG-5F 시뮬레이터 API

공식 URDF의 오른손 20관절과 다섯 손끝을 사용한다. 설치·실행은 [RUNNING.md](RUNNING.md), 좌표·링크 정의는 [ROBOT_MODEL.md](ROBOT_MODEL.md)를 참조한다.

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

이 저수준 API와 별도로 비교 runner는 원본 출력·공통 clip 목표·속도 제한 명령을 분리한다. `q_command`는 actuator 입력,
`q_actual`은 시뮬레이션 실제 관절각이다. JSONL/CSV에도 이 세 값을 분리한다.
손끝은 공식 URDF tip 링크 **원점**을 의미한다. 접촉 패드 표면 중심은 별도 정의가 필요하다.

