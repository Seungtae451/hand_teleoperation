# Phase 1: 저장소 및 실행 환경 조사

조사일: 2026-10-17 (Asia/Seoul). README와 실제 소스를 함께 읽었다.
아래 commit은 조사 당시 확보한 버전이다. 전체 SHA·URL·sparse 범위는
`external_repositories.lock.json`을 기준으로 한다. 모든 저장소에 공개 접근 및 clone이 가능했다.

## 개발 환경

| 항목 | 확인 결과 |
|---|---|
| OS | Ubuntu 22.04.5 LTS, Linux 6.8.0-138-generic, x86_64 |
| 시스템 Python | 3.10.12; `python` 별칭과 시스템 pip 없음 |
| 환경 도구 | uv 0.12.22; `.venv`에 editable 프로젝트 설치 |
| ROS | `/opt/ros` 없음; Phase 2에는 불필요 |
| GPU | NVIDIA GeForce RTX 5080 16 GB × 2 |
| 드라이버 | 580.95.05; nvidia-smi CUDA 호환 표시 13.0 |
| 그래픽 | DISPLAY=:0, libGL/libEGL/NVIDIA EGL 존재; GUI 및 EGL 실제 실행 확인 |
| Phase 2 패키지 | MuJoCo 3.16.0, NumPy 2.2.6, Pillow/ImageIO, pytest, Ruff |

nvidia-smi의 CUDA 표시는 설치된 CUDA toolkit 또는 GeoRT 학습 환경 검증을 뜻하지 않는다.
Quest 장치의 수신 실험과 GeoRT 학습은 이번 단계에서 실행하지 않았다.

## 확보한 저장소

| 저장소 | 고정 SHA 앞 12자리 | 라이선스 | 확인한 주요 경로 | 실행/호환성 판단 |
|---|---|---|---|---|
| [hand-tracking-streamer](https://github.com/wengmister/hand-tracking-streamer) | `5ff7c1cfea0e` | Apache-2.0 | Unity `Assets/Scripts/HandLandmarkStreamer.cs`, `CONNECTIONS.md`, `scripts/` | Unity 앱. Python 프로젝트 메타데이터는 ≥3.13; 시뮬레이터 환경에 설치하지 않음 |
| [hand-tracking-sdk](https://github.com/wengmister/hand-tracking-sdk) | `6ca05d1d5b00` | Apache-2.0 | `src/hand_tracking_sdk/{client,frame,parser,convert}.py` | 스트리머 README에서 발견한 별도 공식 Python SDK; ≥3.10, lark/pyyaml |
| [dg5f_ros2](https://github.com/tesollodelto/dg5f_ros2) | `0cb45ae9474c` | BSD-3-Clause | `dg5f_description/`, `dg5f_driver/script/manus_retarget/` | ROS 2 기반. MANUS mapping은 후속 adapter에서 재사용 후보 |
| [tesollo_model](https://github.com/tesollodelto/tesollo_model) | `f648627be40f` | BSD-3-Clause | `dg5f/dg5f_right.urdf`, XML, meshes | Phase 2 실제 사용 및 실행 완료 |
| [tesollo_ros2](https://github.com/tesollodelto/tesollo_ros2) | `1307f7d537b4` | BSD-3-Clause | `.gitmodules`, `doc/`, `dg_common/` | 여러 제품용 submodule umbrella. ROS 패키지는 실행하지 않음 |
| [AnyDexRetarget](https://github.com/qqsq12321/AnyDexRetarget) | `ee68a0234ccd` | MIT | `optimizer/{analytical_optimizer,base_optimizer,key_vector_optimizer,robot_configs}.py` | ≥3.10. numpy/nlopt/pyyaml; 실제 FK에 `pin`도 필요. 설치·optimizer 실행은 후속 Phase |
| [wuji-retargeting](https://github.com/wuji-technology/wuji-retargeting) | `531f6ed4250b` | MIT | `opt/{adaptive_analytical,base,vector}.py`, `robot.py`, YAML | ≥3.10, Pinocchio/NLopt/SciPy/SDK 의존성. 설치·optimizer 실행은 후속 Phase |
| [GeoRT](https://github.com/facebookresearch/GeoRT) | `fb2075e2a327` | CC-BY-NC-4.0 | `geort/{trainer,model,export}.py`, `env/hand.py`, `config/` | README 권장 Python 3.8; SAPIEN·Torch CUDA 별도 검증 필요. 학습 미실시 |

라이선스는 각 저장소의 LICENSE 실제 내용을 확인했다. GeoRT는 비상업 이용 조건을 명시하므로
회사 PoC에서의 이용 조건을 후속 단계 전에 확인해야 한다. 이 보고서는 라이선스 허가의 판단이 아니다.

다운로드는 소스 분석에 필요한 경로를 sparse checkout했다. Git에는 나머지 트리 정보가 있지만
대형 assets/checkpoint/data 및 submodule 내용은 모두 확보한 것으로 간주하지 않는다.
특히 GeoRT의 기본 학습 데이터와 checkpoint, AnyDex 기본 로봇 assets는 현재 범위에 없다.
Wuji 기본 description/시뮬레이터 submodule과 Tesollo ROS 하위 submodule도 미초기화 상태다.
따라서 “저장소 접근·소스 조사 완료”와 “외부 알고리즘 실행 완료”를 구분한다.

## Quest 스트리머의 실제 계약

근거: 고정 버전의 [HandLandmarkStreamer.cs](https://github.com/wengmister/hand-tracking-streamer/blob/5ff7c1cfea0ead1bb8a0e233bc7770d94d31feb5/hand_tracking_streamer/Assets/Scripts/HandLandmarkStreamer.cs),
[SDK frame.py](https://github.com/wengmister/hand-tracking-sdk/blob/6ca05d1d5b00dfd89535aef74f698d6765bf1229/src/hand_tracking_sdk/frame.py).

- 설치 경로: Meta Quest Store, SideQuest 또는 저장소 APK의 ADB sideload.
  소스 빌드는 README에서 Unity 6000.0.65f1을 사용한다.
- 통신: UTF-8 CSV line, UDP 또는 TCP. wrist line은 위치 3개와 xyzw quaternion 4개,
  landmarks line은 위치 63개 = `(21,3)`이다. 관절별 회전은 전송하지 않는다.
- 실제 선택 인덱스: `[1,2,3,4,5,7,8,9,10,12,13,14,15,17,18,19,20,22,23,24,25]`.
  출력 순서는 wrist + 손가락마다 4개 점이다. 단순히 원 skeleton 첫 21개를 사용하면 안 된다.
- 좌표: wrist는 Unity world, landmark는 `GetJointPosesFromWrist()`에 따른 wrist 상대 위치다.
  README의 world 표현만 보고 모든 점을 world 좌표로 해석하지 않는다. Unity 기본 단위는 m이며
  실제 장치 수신 후 손 길이로 스케일을 확인할 예정이다.
- validity: `IsTrackedDataValid`가 false이면 전송하지 않는다. false flag를 받는 구조가 아니므로
  수신 timeout과 wrist/landmark 시간 차이를 Phase 3에서 관리해야 한다.
- timestamp: 디버그 헤더를 켠 경우 source frame ID와 Stopwatch 기반 ns가 추가된다.
  SDK에는 source/receive timestamp와 sequence가 있다. source와 PC 시계를 동기화된 것으로 취급하지 않는다.
- 주기: 코드의 목표 interval은 0.01초지만 실제 주기는 hand update·렌더·네트워크에 좌우된다.
  CONNECTIONS 문서는 TCP에서 약 70 Hz를 안내한다. 이 PC/Quest에서 실측한 수치는 아니다.

Phase 3은 실제 존재하는 `HTSClient(HTSClientConfig(...))`, `iter_events()`,
`HandFrameAssembler`, `landmarks.points`, `wrist`, `recv_ts_ns`를 adapter 경계로 사용할 수 있다.
SDK의 좌표 변환 함수도 실제 소스를 확인했으며, 변환된 위치와 회전의 basis를 함께 관리해야 한다.

## MANUS mapping 재사용 범위와 확인된 주의점

근거: [공식 manus_retarget.py](https://github.com/tesollodelto/dg5f_ros2/blob/0cb45ae9474caa92410dfa820346da8ffbae8405/dg5f_driver/script/manus_retarget/manus_retarget.py).
입력은 `ManusGlove.ergonomics`의 degree 값 20개, 출력은 이름이 있는 20개 radian 명령이다.
순수 계산부는 `ManusBimanualRetarget._compute_mqd_from_q()`이며 ROS Node 안에 들어 있다.
방향 배열·gain·thumb offset·pinky 조건이 실제 구현되어 있다. 이 값들을 Quest 입력과 동일시하지 않는다.

현재 소스는 `clamped_vals`를 계산하지만 publish에는 `out_vals`를 사용한다.
또한 이 파일의 하드코딩한 일부 joint limit는 이번 `tesollo_model` URDF와 다르다.
Phase 4에서는 순수 계산부를 adapter에서 재사용하는 방식을 검증하고 **공통 URDF 제한을 최종 적용**한다.
ROS import 우회/동작 분리 방법은 그 단계에서 정한다. 원본 수정을 자동 수행하지 않는다.

## AnyDex와 Wuji의 관계 및 Tesollo 등록 경로

두 소스 모두 `(21,3)` keypoint 입력, Pinocchio FK/Jacobian, NLopt SLSQP 및 warm start를 사용한다.
위치·방향·full-hand vector·adaptive pinch·이전 q regularization 구조가 유사하므로
독립적인 두 연구 알고리즘이라고 단정하지 않는다. 내부 위치 loss는 cm 단위로 환산하는 부분이 있다.

| 항목 | AnyDex | Wuji |
|---|---|---|
| 생성 API | `Retargeter.from_config()` / `from_yaml()` | `Retargeter.from_config()` / `from_yaml()` |
| 로봇 등록 | `robot.urdf_path`, origin/tip/link1/link3/link4 명시 override | `optimizer.urdf_path`, `optimizer.link_naming` template override |
| 공통 optimizer | `AdaptiveOptimizerAnalytical` | `AdaptiveOptimizerAnalytical` |
| 추가 기능 | `w_contact`, `pinch_scaling`, 여러 로봇·mimic 처리 | `w_hyper`, `w_couple`, `couple_ratio`, `thumb_skip_pip` |
| joint 출력 | 로봇의 Pinocchio 순서; 이름으로 canonical 재배열 필요 | 동일 |
| reset | filter와 optimizer 상태 초기화 경로 있음 | 동일 |

실제 조사 소스:
[AnyDex base](https://github.com/qqsq12321/AnyDexRetarget/blob/ee68a0234ccdf8a23b98527fd1ee2c6258278cd1/anydexretarget/optimizer/base_optimizer.py),
[AnyDex analytical](https://github.com/qqsq12321/AnyDexRetarget/blob/ee68a0234ccdf8a23b98527fd1ee2c6258278cd1/anydexretarget/optimizer/analytical_optimizer.py),
[Wuji base](https://github.com/wuji-technology/wuji-retargeting/blob/531f6ed4250b475d2e9231f54e988fc9b1c5b4ea/wuji_retargeting/opt/base.py),
[Wuji adaptive](https://github.com/wuji-technology/wuji-retargeting/blob/531f6ed4250b475d2e9231f54e988fc9b1c5b4ea/wuji_retargeting/opt/adaptive_analytical.py).

Tesollo 등록은 원본에 robot type을 추가하기 전에 설정 override를 우선한다.
AnyDex에서는 기본 Shadow 설정이 fallback되므로 모든 link role과 offset/num_fingers를 명시한다.
Wuji template는 `prefix=""`, `palm="rl_dg_palm"`, `fingers=["1",...,"5"]`,
`tip="rl_dg_{finger}_tip"`, `pip="rl_dg_{finger}_3"`, `dip="rl_dg_{finger}_4"`,
`link1="rl_dg_{finger}_1"`로 실제 링크에 대응할 수 있다. 관절 방향·thumb 구조와 coupling 의미는
Phase 5·6에서 검증해야 하며 해당 ratio를 그대로 승인한 것이 아니다.

## GeoRT의 실제 지원 범위와 추가 작업

근거: [trainer.py](https://github.com/facebookresearch/GeoRT/blob/fb2075e2a3272be372016580c0b6ebd6120228f0/geort/trainer.py),
[model.py](https://github.com/facebookresearch/GeoRT/blob/fb2075e2a3272be372016580c0b6ebd6120228f0/geort/model.py),
[env/hand.py](https://github.com/facebookresearch/GeoRT/blob/fb2075e2a3272be372016580c0b6ebd6120228f0/geort/env/hand.py).

- 공식 학습 CLI는 `python geort/trainer.py -hand NAME -human_data NAME -ckpt_tag TAG`이며
  배포 API는 `geort.load_model(TAG)`와 반환 모델의 `forward()`다.
- 예제는 Allegro 4개 손가락이지만 네트워크 모듈은 `keypoint_joints` 목록으로 손가락 수를 구성한다.
  Tesollo에는 5개의 fingertip와 각 4개 joint, human ID 4/8/12/16/20 설정 및 신규 학습이 필요하다.
- 학습 로봇 FK는 SAPIEN을 사용하며 `sapien.Engine`, `sapien.VulkanRenderer` 등 API와
  `.cuda()` 호출을 확인했다. requirements는 대부분 unpinned이고 setup.py 의존성이 비어 있다.
  현재 GPU에서 실행 가능한 SAPIEN/Torch 조합을 별도 환경에서 검증해야 한다.
- config/data/checkpoint 경로가 패키지 루트에 결합되어 있다. 후속 단계에서는 프로젝트 소유의
  workspace 또는 wrapper에서 config dict를 전달하는 방법을 우선 검증한다.
- `collision_loss`는 소스에서 0 tensor로 설정되어 있다. collision-aware 학습이 완성되어 있다고
  주장할 수 없으며 구현을 추가하려면 별도 범위와 원본 변경 필요 여부를 검토해야 한다.

## Phase 1 결론

MuJoCo 모델은 공식 URDF로 직접 실행 가능하다. 모든 필수 저장소의 접근·버전·라이선스·실제
확장 경로를 확인했고, 원본 수정 없이 Phase 2를 구현했다. 외부 optimizer/Quest 연결/GeoRT 학습의
실행 호환성은 해당 Phase에서 검증해야 하는 남은 작업이다.
