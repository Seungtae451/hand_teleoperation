# Project: Meta Quest 3 기반 Tesollo DG-5F Hand Retargeting Benchmark

## 1. 프로젝트 개요

### 프로젝트 목표

Meta Quest 3의 카메라 기반 Hand Tracking을 사용하여 사람 손의 움직임을 실시간으로 추적하고, 여러 Retargeting 알고리즘을 통해 Tesollo DG-5F 로봇핸드에 적용하는 시스템을 구현한다.

실제 Tesollo 하드웨어는 보유하고 있지 않으므로 **모든 로봇 제어 및 성능 평가는 MuJoCo 시뮬레이션 환경에서 수행한다.**

최종적으로 4가지 Retargeting 방식을 동일한 입력과 동일한 로봇 모델에서 비교하여 다음을 분석한다.

- 사람 손의 움직임을 얼마나 정확하게 재현하는가?
- 손가락 간 관계와 Pinch 동작을 얼마나 잘 보존하는가?
- 실시간 Teleoperation에 적합한 연산속도를 제공하는가?
- 관절 움직임이 얼마나 부드럽고 안정적인가?
- 알고리즘별 구현 난이도와 실제 적용 가능성은 어떠한가?

이 프로젝트는 회사 내부 기술 벤치마킹 및 PoC 발표를 목적으로 한다.

**핵심 연구 주제:**

"산업계에서 활용되는 기존 Hand Retargeting 기술과 최신 Learning-based Retargeting 기술의 성능 및 적용 가능성 비교"

---

## 2. 개발 환경 및 제약사항

### Hardware

- Input Device: Meta Quest 3
- Robot Target: Tesollo DG-5F (5 Fingers, 20-DoF)
- Physical Robot: 없음
- Development Machine: Ubuntu Linux 기반 PC
- GPU: 사용 가능한 경우 GeoRT 학습에 활용

### Software

- Primary Language: Python
- Simulator: MuJoCo
- Robot Model: Tesollo 공식 URDF/xacro 기반
- Input: Meta Quest 3 Hand Tracking
- Visualization: MuJoCo Viewer 및 Python Plot
- Data Logging: NumPy, JSON, CSV 등

### 필수 제약사항

1. 실제 로봇 제어를 구현할 필요는 없다.
2. MuJoCo에서 동일한 Tesollo DG-5F 모델을 사용해야 한다.
3. 모든 알고리즘은 동일한 Quest 3 입력 데이터를 사용해야 한다.
4. 최종 관절 명령은 공통된 20-DoF joint order로 통일해야 한다.
5. 로봇 관절 제한을 반드시 적용해야 한다.
6. 각 알고리즘의 출력과 실제 시뮬레이션 관절 상태를 구분하여 기록한다.
7. 원본 GitHub 코드는 가능하면 수정하지 않고 adapter를 구현한다.
8. 불가피하게 수정할 경우 변경사항과 이유를 기록한다.
9. 존재하지 않는 API, URDF link, joint name을 임의로 가정하지 않는다.
10. 외부 GitHub의 문서와 실제 코드를 직접 확인한 후 구현한다.

---

## 3. 필요한 GitHub 저장소

아래 저장소들을 조사하고 다운로드한다. 저장소 주소, 현재 접근 가능 여부, 라이선스, 요구 환경 및 실제 파일 구조를 먼저 검증한다.

### 3.1 Meta Quest 3 Hand Tracking

Repository:
https://github.com/wengmister/hand-tracking-streamer

목적:
- Meta Quest 3에서 추적되는 손 관절 데이터를 PC에서 수신
- 3D joint positions
- Joint rotations/orientations
- Wrist pose
- Timestamp 및 Tracking validity(제공 가능한 경우)

확인할 사항:
- Quest 3 앱 설치 방법
- 실제 제공하는 landmark 개수 및 데이터 구조
- Python SDK 및 통신 방식
- Coordinate System
- 데이터 단위
- Streaming frequency
- Hand tracking validity 처리

위 데이터가 실제 SDK에서 제공되는지 각각 확인한다.

### 3.2 Tesollo DG-5F

Repositories:
https://github.com/tesollodelto/dg5f_ros2

https://github.com/tesollodelto/tesollo_model

https://github.com/tesollodelto/tesollo_ros2

목적:
- DG-5F URDF/xacro 확보
- 20개 관절 정보 확인
- Joint limits 확인
- Link geometry 및 fingertip frames 확인
- MuJoCo 모델 구축
- MANUS Retargeting 코드 확보

특히 다음을 확인한다.
- Robot base/palm link
- 각 손가락의 joint 이름과 순서
- Fingertip link
- Joint axis
- Joint limits
- Mesh 파일
- Mimic/coupled joints 존재 여부

URDF에 명시된 정보와 실제 제어 가능한 자유도를 구분한다.

### 3.3 AnyDexRetarget

Repository:
https://github.com/qqsq12321/AnyDexRetarget

목적:
- Optimization-based Retargeting
- Adaptive Analytical Optimizer
- Hand Keypoint 기반 최적화
- MuJoCo 시뮬레이션 연동

분석 대상:
- `analytical_optimizer.py`
- `base_optimizer.py`
- `key_vector_optimizer.py`
- 설정 파일 및 example

Tesollo DG-5F를 새로운 로봇으로 등록하는 방법을 조사하고 구현한다.

### 3.4 Wuji Retargeting

Repository:
https://github.com/wuji-technology/wuji-retargeting

목적:
- Wuji Hand 제조사의 최적화 기반 Retargeting 구현 참고
- Adaptive Analytical Optimizer
- Hyperextension Constraint
- DIP–PIP Coupling Constraint
- Full Hand Vector Loss

분석 대상:
- `wuji_retargeting/opt/adaptive_analytical.py`
- `wuji_retargeting/opt/base.py`
- `wuji_retargeting/opt/vector.py`
- 관련 설정 파일

AnyDexRetarget과 공통된 최적화 구조가 있으므로 두 프로젝트를 완전히 독립적인 알고리즘으로 취급하지 않는다.

공통 목적함수와 프로젝트별 추가 기능을 구분하여 구현 및 평가한다.

### 3.5 GeoRT

Repository:
https://github.com/facebookresearch/GeoRT

Project:
https://zhaohengyin.github.io/geort/

목적:
- Neural Network 기반 Geometric Retargeting
- 새로운 로봇 모델 등록
- Tesollo DG-5F용 모델 학습
- 실시간 추론
- 기존 최적화 방식과 비교

GeoRT는 기본 예제에서 4-Finger Hand를 사용하는 경우가 있으므로 Tesollo의 5-Finger 구성에 맞게 설정 및 학습이 필요하다.

공식 API, 학습 절차 및 Python 의존성을 반드시 확인한다.

---

## 4. 구현할 Retargeting 알고리즘

### Method A — MANUS-style Joint Mapping

기준:
Tesollo에서 제공하는 MANUS 글러브 기반 Retargeting 방식

입력:
Meta Quest 3의 Hand Joint Positions 및 Rotations

처리:
1. Quest의 관절 회전 또는 관절 위치에서 손가락 굽힘각 계산
2. MANUS Ergonomics와 대응되는 입력 표현 구성
3. Tesollo의 기존 Joint Mapping 방식 적용
4. Calibration Gain 적용
5. Joint Limits 적용

출력:
Tesollo DG-5F 20개 Joint Target

주의:
- 실제 MANUS 글러브 데이터가 아니므로 Quest-to-MANUS 변환이 필요하다.
- MANUS와 Quest의 joint convention이 다를 수 있다.
- 실제 joint mapping과 calibration 수치는 공식 코드를 기준으로 확인한다.

### Method B — AnyDexRetarget

방식:
Optimization-based Hand Retargeting

입력:
Meta Quest 3의 Hand Keypoints

처리:
1. Quest Keypoints를 optimizer 좌표계로 변환
2. Human Hand와 Robot Hand의 기하학적 관계 구성
3. Adaptive Analytical Optimization 실행
4. Robot FK 및 Jacobian 활용
5. 최적 관절 목표각 계산

관심 항목:
- Fingertip Position
- Fingertip Direction
- Full Hand Vector
- Adaptive Pinch
- Explicit Contact Loss
- Previous Joint Regularization

출력:
Tesollo 20-DoF Joint Target

### Method C — Wuji Adaptive Analytical Retargeting

방식:
Geometry-aware Optimization

입력:
Meta Quest 3의 Hand Keypoints

처리:
1. Human Hand Skeleton 전처리
2. Wuji Adaptive Analytical Optimizer 적용
3. Tesollo의 URDF 및 Joint Configuration 사용
4. Joint Constraints 적용
5. 최적화 결과를 Tesollo Joint Target으로 변환

관심 항목:
- Full Hand Vector Loss
- Fingertip Position/Direction Loss
- Adaptive Pinch
- Hyperextension Penalty
- DIP–PIP Coupling
- Thumb-specific Loss Handling

주의:
Wuji의 coupling ratio와 관절 제약은 Tesollo에 그대로 적용하지 말고, 로봇의 관절 방향과 구조에 맞는지 검증한다.

### Method D — GeoRT

방식:
Learning-based Geometric Retargeting

입력:
Meta Quest 3에서 얻은 Human Hand Keypoints

처리:
1. Tesollo DG-5F URDF 등록
2. 5개 손가락 fingertip mapping 설정
3. 필요한 Neural FK / Collision 관련 모델 구축
4. GeoRT 학습
5. 학습된 모델을 사용하여 Retargeting 수행

출력:
Tesollo 20-DoF Joint Target

관심 항목:
- Motion Preservation
- Workspace/C-space Coverage
- Pinch Correspondence
- Collision Avoidance
- Inference Speed

주의:
- 사전 학습된 다른 로봇 모델을 Tesollo에 그대로 적용하지 않는다.
- Tesollo용 모델을 학습해야 한다.
- 학습에 사용한 Quest 데이터와 평가 데이터는 분리한다.
- 학습 및 추론에 걸린 시간도 별도로 기록한다.

---

## 5. 전체 시스템 아키텍처

```text
                Meta Quest 3
                     |
                     v
             Hand Tracking SDK
                     |
                     v
              PC Data Receiver
                     |
                     v
           Common Hand Data Format
                     |
              +------+------+
              |             |
              v             v
         Data Recorder   Live Stream
              |             |
              +------+------+
                     |
                     v
             Retargeting Input
                     |
        +------------+------------+
        |            |            |
        v            v            v
   MANUS-style   AnyDexRetarget   Wuji
        |            |            |
        +------------+------------+
                     |
                   GeoRT
           (independent branch)
                     |
                     v
           Common Joint Format
               q = (20,)
                     |
                     v
              Tesollo DG-5F
               MuJoCo Model
                     |
                     v
              Data Collection
                     |
                     v
             Performance Analysis
```

실제 코드에서는 GeoRT를 포함해 4개 Retargeter를 동일한 인터페이스를 가진 병렬적인 모듈로 구현한다.

하나의 알고리즘 출력을 다른 알고리즘에 순차적으로 입력하지 않는다.

---

## 6. 공통 데이터 형식 정의

서로 다른 라이브러리의 데이터를 직접 주고받는 대신, 공통 데이터 구조를 만든다.

예시:

```python
@dataclass
class HandFrame:
    timestamp: float
    handedness: str
    joint_positions: np.ndarray
    joint_rotations: np.ndarray
    wrist_position: np.ndarray
    wrist_rotation: np.ndarray
    tracking_valid: bool
```

실제 데이터 크기는 Quest SDK의 구조를 확인하여 정의한다.

공통적으로 다음 사항을 관리한다.

- Units: meters / radians
- Handedness: left / right
- Coordinate frame: source / wrist / palm
- Quaternion convention
- Joint indexing
- Timestamp
- Tracking validity

특히 MediaPipe 21-keypoint 구조를 사용하는 라이브러리와 Quest SDK의 원래 skeleton이 다를 수 있으므로 명시적인 mapping 함수를 구현한다.

모든 알고리즘은 다음과 같은 공통 인터페이스를 사용하도록 한다.

```python
class BaseRetargeter:
    def reset(self):
        raise NotImplementedError

    def retarget(self, hand_frame):
        """
        Returns:
            q_target: np.ndarray, shape (20,)
        """
        raise NotImplementedError
```

Retargeter에서 사용한 state, solver status, 연산시간 등도 별도 metadata로 기록할 수 있도록 한다.

---

## 7. MuJoCo Simulation 요구사항

Tesollo DG-5F의 동일한 모델을 네 방법이 공유한다.

구현 기능:

1. DG-5F URDF를 기반으로 MuJoCo 모델 생성
2. 20개 관절의 개별 목표각 지정
3. 모든 Joint Limit 검증
4. Robot Forward Kinematics
5. Fingertip 3D Position 계산
6. Joint State Logging
7. MuJoCo Viewer
8. 시뮬레이션 녹화
9. 동일 입력 데이터 재생
10. 알고리즘 전환 기능

시뮬레이션 평가를 두 종류로 분리한다.

**Kinematic Evaluation**

각 알고리즘이 생성한 q_target을 FK에 입력하여 리타게팅 알고리즘 자체의 성능을 분석한다.

**Dynamic Evaluation**

MuJoCo의 actuator와 controller로 실제 시뮬레이션 손을 움직여 tracking 및 grasp performance를 분석한다.

두 평가에서 사용하는 관절각과 손끝 위치를 구분해서 저장한다.

---

## 8. 평가 지표

### 8.1 Fingertip Position Error

사람 손과 로봇 손의 normalized fingertip position 차이를 계산한다.

\[
E_{\text{tip}} =
\frac{1}{5T}
\sum_{t=1}^{T}
\sum_{i=1}^{5}
\|\hat p_{h,i,t}-\hat p_{r,i,t}\|_2
\]

사람과 로봇의 손 크기가 다르므로 palm frame 정렬 및 정규화 방식을 명확하게 정의한다.

Quest 추정 위치를 기준으로 계산하는 지표는 독립적인 사람 손 Ground Truth가 아니라는 점을 기록한다.

### 8.2 Fingertip Distance Error

엄지와 각 손가락 사이의 거리 보존 정도를 평가한다.

대상:
- Thumb–Index
- Thumb–Middle
- Thumb–Ring
- Thumb–Pinky

가능하면 각 손의 기준 길이로 거리를 정규화한다.

### 8.3 Motion Direction Consistency

사람 손끝의 이동 방향과 로봇 손끝의 이동 방향이 얼마나 일치하는지 평가한다.

Cosine Similarity를 사용한다.

미세한 움직임으로 방향이 정의되지 않는 프레임은 적절한 임계값을 적용하여 제외한다.

### 8.4 Computation Time

Retargeting 실행시간을 측정한다.

기록:
- Mean
- Median
- P95
- Maximum
- Throughput (FPS)

입력 전처리 시간과 optimizer 자체의 실행시간을 구분한다.

GeoRT는 Training Time과 Inference Time을 따로 기록한다.

### 8.5 Motion Smoothness

출력되는 joint target의 변화를 평가한다.

- Joint Velocity
- Joint Acceleration
- Joint Jerk
- Static Pose Jitter

Jerk만 최소화하면 느린 움직임이 유리해질 수 있으므로 motion fidelity 및 latency와 함께 평가한다.

### 8.6 Simulation Safety

- Joint Limit Violations
- Robot Self-collision
- Invalid Joint Target
- Optimization Failure
- Tracking Loss Recovery

### 8.7 Functional Retargeting

시뮬레이션에서 다음을 평가한다.

- Pinch Success
- Fingertip Contact
- Finger Independence
- Workspace Coverage
- Object Grasp Success (후속 단계)

---

## 9. 실험 동작

Meta Quest 3를 통해 다음 손동작을 기록한다.

### Static Poses

1. Open Hand
2. Closed Fist
3. Thumb–Index Pinch
4. Thumb–Middle Pinch
5. Thumb–Pinky Pinch
6. Independent Finger Flexion

### Dynamic Motions

1. Repeated Open/Close
2. Repeated Pinch
3. Sequential Finger Flexion
4. Slow Finger Motion
5. Fast Finger Motion
6. Finger Spreading

### Tracking Robustness

1. 손가락의 부분적인 가림
2. 손의 빠른 움직임
3. Tracking이 잠깐 끊기는 상황
4. 손가락이 서로 겹치는 상황

동일한 Hand Tracking 녹화 데이터에 네 알고리즘을 적용한다.

반복 실험에서는 각 알고리즘의 이전 상태를 초기화하고 동일한 초기 조건을 사용한다.

---

## 10. 결과 시각화

회사 기술 발표를 위해 다음 결과를 출력해야 한다.

### Graphs

1. 알고리즘별 Fingertip Position Error
2. Thumb–Index Distance vs Time
3. Thumb–Pinky Distance vs Time
4. Computation Time Distribution
5. Joint Jitter Comparison
6. Motion Direction Consistency
7. Joint Limit / Collision Statistics
8. Pinch Success Rate

### Videos

가장 중요한 결과물은 동일한 Quest Hand Tracking 입력에 대해 네 방법의 움직임을 비교하는 영상이다.

화면 구성 예시:

```text
+----------------+----------------+
| MANUS-style    | AnyDexRetarget |
|                |                |
|  Tesollo Hand  |  Tesollo Hand  |
+----------------+----------------+
| Wuji Adaptive  | GeoRT          |
|                |                |
|  Tesollo Hand  |  Tesollo Hand  |
+----------------+----------------+
```

같은 타임스탬프에 대응하는 손동작이 네 화면에 나타나야 한다.

가능하다면 Quest의 Human Hand Skeleton도 함께 시각화한다.

---

## 11. Wuji와 AnyDexRetarget의 차이 분석

두 프로젝트의 Adaptive Analytical Optimizer는 핵심 목적함수가 매우 유사하다.

따라서 두 프로젝트를 단순히 서로 다른 알고리즘으로 취급하지 말고, 코드 및 설정 수준의 차이를 분석한다.

특히 다음을 확인한다.

**Common Optimization Terms**
- Fingertip Position Loss
- Fingertip Direction Loss
- Full Hand Vector Loss
- Adaptive Pinch Weight
- Previous Joint Regularization

**AnyDexRetarget-specific**
- Explicit Contact Loss
- Pinch Scaling
- 기타 추가된 기능

**Wuji-specific**
- Hyperextension Penalty
- DIP–PIP Coupling
- Thumb-specific Loss Handling

가능하면 별도의 ablation experiment를 수행한다.

| Condition | Description |
|---|---|
| Base Adaptive | 공통 목적함수 |
| AnyDex Extension | Contact-related extensions |
| Wuji Extension | Joint constraint extensions |
| Combined | 두 확장 기능 결합 |

이 ablation은 기본 네 방법의 비교를 완료한 뒤 추가 실험으로 수행한다.

---

## 12. 권장 프로젝트 구조

```text
quest_tesollo_benchmark/
│
├── external/
│   ├── hand-tracking-streamer/
│   ├── dg5f_ros2/
│   ├── tesollo_model/
│   ├── AnyDexRetarget/
│   ├── wuji-retargeting/
│   └── GeoRT/
│
├── benchmark/
│   ├── tracking/
│   │   ├── quest_receiver.py
│   │   ├── coordinate_transform.py
│   │   ├── hand_frame.py
│   │   └── recorder.py
│   │
│   ├── retargeting/
│   │   ├── base.py
│   │   ├── manus.py
│   │   ├── anydex.py
│   │   ├── wuji.py
│   │   └── geort.py
│   │
│   ├── simulation/
│   │   ├── robot_model.py
│   │   ├── mujoco_runner.py
│   │   └── visualization.py
│   │
│   ├── evaluation/
│   │   ├── fingertip_error.py
│   │   ├── motion_consistency.py
│   │   ├── timing.py
│   │   ├── smoothness.py
│   │   ├── collision.py
│   │   └── pinch.py
│   │
│   ├── experiments/
│   │   ├── offline_benchmark.py
│   │   ├── simulation_benchmark.py
│   │   └── compare_methods.py
│   │
│   └── utils/
│
├── assets/
│   └── tesollo/
│
├── configs/
│   ├── manus.yaml
│   ├── anydex.yaml
│   ├── wuji.yaml
│   ├── geort.yaml
│   └── experiment.yaml
│
├── recordings/
├── results/
├── tests/
├── scripts/
├── README.md
└── requirements/
```

필요에 따라 구조를 개선할 수 있지만 공통 데이터 인터페이스와 알고리즘별 모듈 분리는 유지한다.

---

## 13. 구현 순서

### Phase 1 — Repository Investigation

1. GitHub 저장소 확보
2. 실제 코드와 요구 환경 확인
3. URDF 및 joint naming 조사
4. 각 프로젝트의 입력/출력 형식 정리
5. 실행 가능 여부 및 호환성 보고

완료 조건:
- 모든 필수 저장소의 상태를 파악한다.
- 사용할 코드 파일과 버전을 명시한다.
- 기술적 문제와 필요한 추가 작업을 문서화한다.

### Phase 2 — Tesollo MuJoCo Model

1. DG-5F 모델 확보
2. URDF/xacro 처리
3. MuJoCo 모델 생성
4. Joint actuation 구현
5. Fingertip FK 확인
6. Viewer 구현

완료 조건:
- MuJoCo에서 Tesollo Hand가 정상적으로 렌더링된다.
- 20개 관절을 지정한 목표각으로 움직일 수 있다.
- 각 손끝의 3D 위치를 계산할 수 있다.

### Phase 3 — Quest 3 Hand Tracking

1. Quest SDK 연결
2. 데이터 수신
3. 좌표계 변환
4. 데이터 저장
5. 저장 데이터 재생

완료 조건:
- Quest에서 손을 움직이면 PC에서 추적 데이터가 갱신된다.
- 동일한 입력 데이터를 재생할 수 있다.
- Quest 없이도 녹화 파일로 오프라인 테스트가 가능하다.

Quest 장치가 연결되지 않은 개발 환경에서는 우선 합성 입력과 공식 예제 데이터를 사용해 파이프라인을 테스트한다.

### Phase 4 — MANUS-style Retargeting

1. Tesollo MANUS 코드 분석
2. Quest-to-MANUS 변환
3. Joint Mapping
4. Calibration
5. Simulation 연결

완료 조건:
- Quest Hand Motion이 Tesollo Hand의 20개 관절 목표값으로 변환된다.
- Open/Close와 Pinch 동작이 시뮬레이션에서 확인된다.

### Phase 5 — AnyDexRetarget

1. 라이브러리 설정
2. Tesollo Robot Model 등록
3. Human Keypoint Mapping
4. Adaptive Optimizer 실행
5. MuJoCo 연동

완료 조건:
- 동일한 Quest 데이터에서 목표 관절각을 생성한다.
- 계산시간과 손끝 오차를 측정할 수 있다.

### Phase 6 — Wuji Retargeting

1. Wuji Optimizer 분석
2. Tesollo 모델 설정
3. 관절 제약 및 coupling 검증
4. MuJoCo 연동
5. AnyDexRetarget과 비교

완료 조건:
- Wuji 방식으로 Tesollo 손을 구동할 수 있다.
- 두 최적화 방식의 공통점과 차이점을 문서화한다.

### Phase 7 — GeoRT

1. 공식 GeoRT 실행 환경 구성
2. Tesollo 모델 등록
3. 5-Finger Mapping 설정
4. Neural FK 관련 준비
5. GeoRT Training
6. Trained Model Inference
7. MuJoCo 연동

완료 조건:
- 학습된 Tesollo용 GeoRT 모델이 20개 관절 목표각을 생성한다.
- 동일한 Quest 데이터를 사용하여 다른 알고리즘과 비교할 수 있다.

### Phase 8 — Benchmark

1. 공통 평가 데이터셋 구축
2. 네 알고리즘 자동 실행
3. 평가 지표 계산
4. 결과 CSV/JSON 저장
5. 그래프 생성
6. 네 화면 비교 영상 생성
7. 결과 보고서 작성

---

## 14. 구현 시 반드시 지켜야 할 사항

- GitHub README만 보고 추측하지 말고 실제 소스코드를 확인한다.
- 존재하지 않는 함수나 옵션을 임의로 만들어 사용하지 않는다.
- 공식 구현을 최대한 재사용한다.
- 알고리즘을 대체하는 임의의 단순화된 구현을 원래 알고리즘인 것처럼 표시하지 않는다.
- 미구현 기능은 명확하게 표시한다.
- 모든 joint order와 좌표계를 명시적으로 관리한다.
- Retargeting 결과에 대한 단위 테스트를 작성한다.
- 동일한 입력으로 재현 가능한 벤치마크를 구성한다.
- 학습 데이터와 테스트 데이터를 분리한다.
- 최적화 알고리즘의 warm-start 조건을 통일한다.
- 모든 실험의 파라미터와 랜덤 시드를 기록한다.
- 외부 라이브러리 버전 또는 commit SHA를 기록한다.
- 실험 결과를 임의로 생성하지 않는다.
- 로봇 하드웨어가 없기 때문에 실제 로봇 제어 성능을 검증했다고 주장하지 않는다.

---

## 15. 최종 산출물

최종적으로 아래 파일과 기능을 제공한다.

**Software**
- Quest Hand Tracking Receiver
- Common Hand Data Interface
- Tesollo DG-5F MuJoCo Model
- MANUS-style Retargeter
- AnyDexRetarget Adapter
- Wuji Retargeter Adapter
- GeoRT Retargeter Adapter
- Data Recording / Replay Tool
- Benchmark Runner
- Result Visualization Tool

**Documentation**
- Installation Guide
- Repository/Dependency List
- Robot Model Configuration
- Coordinate System Documentation
- Algorithm Comparison
- Benchmark Protocol
- Evaluation Result Report
- Known Limitations

**Demo**
- Human Hand Tracking Visualization
- Four Retargeting Methods Comparison
- Same Input / Same Robot Side-by-side Simulation
- Performance Comparison Graphs

---

## 16. Codex 작업 지침

이 프로젝트를 단계적으로 구현해줘.

우선 현재 작업 디렉터리와 개발 환경을 조사하고, 기존 파일이 있다면 덮어쓰지 말고 구조를 파악해.

외부 GitHub의 실제 코드를 확인하여 구현 가능성을 검증하고, 필요한 저장소를 확보해.

처음부터 전체 시스템을 임시 코드로 구성하지 말고, 각 단계별로 실제 동작하는 결과물을 만들어.

특히 **가장 먼저 완성할 목표는 Tesollo DG-5F의 20-DoF MuJoCo 시뮬레이션**이야.

그다음 Quest 데이터 인터페이스와 Recording/Replay 시스템을 구현하고, MANUS-style → AnyDexRetarget → Wuji → GeoRT 순서로 확장해.

환경상 Quest 3가 연결되어 있지 않더라도 오프라인 데이터와 테스트 입력으로 구현을 계속 진행해.

개발 중 문제가 발생하면 가능한 해결 방안을 조사하고 구현하되, 핵심 알고리즘을 다른 것으로 임의 대체하지는 마.

각 Phase가 끝날 때 다음을 보고해줘.

1. 구현한 기능
2. 생성하거나 수정한 파일
3. 실제 실행 및 테스트 결과
4. 남아 있는 문제
5. 다음 단계

최종 목표는 네 가지 Retargeting 방법을 **동일한 Quest 3 입력 데이터와 동일한 Tesollo DG-5F MuJoCo 모델에서 공정하게 비교할 수 있는 재현 가능한 벤치마크 시스템**을 완성하는 것이야.


---

## 17. Additional Task — Public Human Hand Dataset Integration

Meta Quest 3 장치가 연결되지 않은 상태에서도 Retargeting Benchmark를 개발할 수 있도록 공개 Human Hand Dataset을 활용한다.

### 데이터셋 우선순위

1. GeoRT 저장소의 `human_alex.npy`
2. AnyDexRetarget / Wuji의 공식 예제 입력
3. Meta SHOW3D Dataset
4. InterHand2.6M 또는 DexYCB (필요시)

### 구현 요구사항

- 각 데이터셋의 실제 파일 구조와 관절 인덱스를 확인한다.
- 모든 데이터를 공통 `HandFrame` 포맷으로 변환한다.
- 오른손 데이터를 우선 지원한다.
- 좌표계, 스케일, 단위 및 handedness를 검증한다.
- 21개 keypoint로 변환할 수 없는 데이터는 임의로 값을 생성하지 않는다.
- 데이터 출처, 라이선스, 원래 추적 방식을 metadata에 기록한다.
- 각 데이터에서 Open Hand, Fist, Pinch 동작을 추출할 수 있는지 확인한다.
- 동일한 프레임을 네 Retargeting 알고리즘에 입력할 수 있도록 구현한다.
- 데이터셋 간 관절 정의가 다르면 명시적인 adapter를 만든다.
- Quest 3 SDK의 실제 출력과 공개 데이터셋의 추정 pose를 구분해서 기록한다.
- 학습/평가 데이터 분리 및 참가자·시퀀스 중복 여부를 확인한다.
- 다운로드 용량이 큰 데이터셋은 전체를 받기 전에 소규모 시퀀스를 선택하여 테스트한다.

### 구현 순서

우선 GeoRT와 AnyDexRetarget의 예제 데이터로 공통 재생 파이프라인을 완성하고, 이후 SHOW3D 데이터를 연결한다.

### 완료 조건

최종적으로 Quest 3가 연결되지 않아도 MuJoCo에서 네 Retargeting 방법의 Offline Benchmark가 실행되어야 한다.

기존 Retargeting 구현을 재현하고 평가한다는 원칙을 유지한다. 데이터셋 adapter는 원본 알고리즘과 분리하며, 평가 성능을 높이기 위해 원본 알고리즘을 임의로 수정하지 않는다.
