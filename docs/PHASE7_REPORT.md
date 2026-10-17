# Phase 7 구현 준비 결과 — 학습 전까지

사용자 요청에 따라 데이터 수집, 실제 학습, 성능 평가는 보류했다.
이 보고서는 원본 GeoRT의 DG-5F 연결 구현과 학습 없이 가능한 기술 검증만 다룬다.
학습된 모델의 정확도나 실제 retargeting 결과를 보고하는 단계가 아니다.

## 원본 API 확인 및 재사용

대상 저장소는 `facebookresearch/GeoRT`, 고정 commit은
`fb2075e2a3272be372016580c0b6ebd6120228f0`, 라이선스는 CC-BY-NC-4.0이다.
원본 소스·설정 디렉터리·기존 로봇 파일을 수정하지 않았다.
기존 Phase 1–6 코드·설정·문서도 변경하지 않았다.

다음 실제 API를 재사용한다.

| 역할 | 원본 API |
|---|---|
| 기구학 모델 | HandKinematicModel.build_from_config / initialize_keypoint / keypoint_from_qpos |
| 학습 진입 | GeoRTTrainer(config).train(human_data_path) |
| 실제 checkpoint 추론 | GeoRTRetargetingModel(model_path, config_path).forward(keypoints) |
| 네트워크 구조 | FKModel / IKModel |
| joint mapping 파싱 | parse_config_keypoint_info / parse_config_joint_limit |
| 오른손 canonical 변환 | manus_mocap_core.py의 hand_to_canonical |

`geort.load_model(tag)`는 원본 패키지 checkpoint 폴더를 substring으로 검색한다.
wrapper에서는 모호한 파일 선택을 피하기 위해 공개 class에 정확한 파일 경로를 전달한다.
MANUS canonical helper는 ROS node를 import하지 않고 원본 함수 AST만 그대로 실행한다.
네트워크·목적함수·optimizer·학습 loop의 계산 코드는 새로 작성하지 않았다.

## 환경

기존 `.venv`는 유지하고 `.venv-geort`를 별도로 만들었다.
SAPIEN 2.x 원본 API와 NumPy ABI를 위한 분리이며 기존 NumPy 2 기반 환경을 낮추지 않았다.

| 구성 | 검증 버전/상태 |
|---|---|
| Python | 3.10.12 |
| PyTorch | 2.7.1+cu128 |
| CUDA runtime | 12.8 |
| SAPIEN | 2.2.2 |
| NumPy | 1.26.4 |
| Open3D | 0.19.0 |
| MuJoCo | 3.16.0 |
| GPU | RTX 5080 두 장 인식, GPU scalar 연산 확인 |

Torch 배포 버전은 [공식 이전 버전 설치 안내](https://pytorch.org/get-started/previous-versions/),
SAPIEN API는 [공식 2.2 문서](https://sapien.ucsd.edu/docs/2.2/tutorial/robotics/basic_robot.html)를
참고하고 실제 import/실행으로 확인했다.
전체 설치 버전 119개는 `requirements/phase7-environment.lock.txt`에 저장했다.
`uv pip check`와 고정 버전 설치 dry-run도 통과했다.
ROS, MANUS SDK, 카메라 장치, torchvision/torchaudio 예제 경로는 실행에 사용하지 않는다.

## DG-5F 설정과 자산

`configs/geort_dg5f_right.json`에 실제 20개 joint order와 다섯 손끝을 지정했다.
각 손가락의 네 관절 chain은 공식 URDF의 부모–자식 연결을 따라 검증했다.

- base frame: `rl_dg_palm`.
- 손끝: `rl_dg_[1-5]_tip`, center_offset=[0,0,0].
- 사람 손끝 index: thumb/index/middle/ring/pinky = 4/8/12/16/20.
- joint order: 기존 benchmark와 같은 `rj_dg_1_1`부터 손가락별 네 개, 총 20개.
- 관절 범위: 공식 URDF 값. export config의 범위가 다르면 거부한다.

Center offset 0은 공식 fingertip link frame 자체를 추적한다는 선택이며,
실제 접촉 표면의 중심을 추정해 값을 추가한 것이 아니다.

workspace의 파생 URDF는 mesh filename만 workspace의 byte 사본으로 변경한다.
joint, axis, origin, limit, inertial, visual/collision geometry를 보존한다.
XML에서 filename을 되돌렸을 때 원본 tree와 동일함을 테스트했다.
SAPIEN이 원본 mesh 옆에 convex cache를 쓰는 동작을 최초 검증에서 발견했다.
생성된 cache 28개는 프로젝트 출력으로 이동하고 이후에는 복사한 mesh만 로딩한다.
최종 외부 저장소는 모두 clean이다. 새 cache는 workspace/meshes 안에 생성된다.
원본 파일을 고치거나 외부 저장소의 ignore 규칙을 바꾸지 않았다.

준비 산출물은 `results/geort_dg5f_workspace`에 있다.
`preparation.json`에 원본·파생 URDF/config/mesh hash와 미실행 상태를 기록했다.
`prepare`는 기존 workspace를 덮어쓰지 않고 `load_workspace`는 준비 파일 변조를 검사한다.

## 입력 규약과 추후 사용자 데이터

공통 HandFrame 오른손 21개 점을 입력받아 기존 `world_points`로 source-world 좌표를 복원하고,
원본 GeoRT의 `hand_to_canonical`을 사용한다.

| 항목 | 규약 |
|---|---|
| shape | N × 21 × 3 |
| 단위 | meter, gain/크기 보정 없음 |
| 원점 | wrist 0 |
| +Z | wrist 0 → middle MCP 9 |
| Y 보조축 | ring MCP 13 → index MCP 5 |
| +X | 정규화한 Y보조축 × Z |
| +Y | Z × X |

이는 기존 benchmark의 보조축 17→5와 다르다. GeoRT 입력에서는 원본 정의를 적용하고,
학습용 export와 추론에서 같은 변환 함수를 공유한다.
반대 손, 추적 무효, 퇴화 bone/palm, meter와 맞지 않는 규모를 거부한다.
누락 점이나 관절 rotation을 만들지 않는다.

추후 `export-input`은 기존 원본 JSONL을 보존하면서 NPY와 별도 manifest를 만든다.
원본 recording hash, 포함한 frame의 시간 domain·metadata, sequence/알려진 participant ID,
선택 split과 명시적으로 제외한 무효 frame 수를 보존한다.
기본 split은 development이며 자동 train/eval 분할을 하지 않는다.
이번 구현 검증의 export 테스트는 temporary synthetic fixture만 사용했다.
사용자의 실제 녹화나 공개 예제를 새 학습 데이터로 export하지 않았다.

## 학습·추론 실행 준비

`train` 명령은 기본적으로 plan_only이며 데이터가 없어도 구조와 미충족 요구사항을 출력한다.
실제 실행 경로에는 `--execute`, 실제 NPY, `train` role manifest가 필요하다.
format·hash·frame count·unit·wrist 중심·입력 convention을 확인하고 원본 trainer를 호출한다.
새 하위 training 폴더를 CWD로 사용하므로 원본의 상대 경로 출력이 외부 저장소에 생기지 않는다.

원본의 학습 구조와 수치를 유지했다.

- 로봇 기구학 데이터 및 neural FK는 원본 경로에서 필요 시 생성·학습.
- neural FK 기본 200 epochs, IK 기본 200 epochs.
- Adam/AdamW, dataset sampling, network 구조, loss 계산은 원본 그대로.
- w_chamfer=80, w_curvature=0.1, w_collision=0, w_pinch=1.
- 기본 재현 seed는 20261018이며 추후 실행 manifest에 남긴다.

원본의 collision classifier 통합은 pending이며 collision loss는 0 placeholder다.
기능을 추가하거나 존재하지 않는 collision API를 구현한 것으로 표시하지 않았다.
이번에 실제 neural FK/IK 학습, 대량 robot 학습 데이터 생성, checkpoint 저장은 하지 않았다.

`GeoRTRetargeter`는 기존 BaseRetargeter를 구현하고 checkpoint가 있을 때 원본 inference class를
호출하도록 연결했다. 학습된 DG-5F checkpoint와 맞는 export config가 없으면 거부한다.
16관절 다른 로봇 모델이나 무작위 가중치로 동작을 대체하지 않는다.
추후 infer CLI는 기존 공통 MuJoCo runner와 제어/로그 정책을 사용한다.
현재 실제 checkpoint 로딩 및 수치 추론, 네 방법 비교는 미검증이다.

## 실제 수행한 검증

- 원본 SAPIEN HandKinematicModel로 DG-5F 20개 관절·다섯 손끝 로딩 성공.
- 영 자세·관절 범위 중간값·범위 내 지정 자세 세 경우의 FK를 MuJoCo와 대조.
- 최대 좌표 성분 차이: **1.0965e-6 m**, 테스트 허용범위 2e-6 m 이내.
- 원본 FK/IK 구조: 손가락별 네 관절, 다섯 network, 총 20개 출력 관절.
- FK parameter 90,255개, IK parameter 90,260개. 구조만 생성하고 forward는 하지 않음.
- original trainer 모듈 import 확인. train 함수는 호출하지 않음.
- CUDA 장치 인식 및 scalar 연산 확인. 학습/추론/속도 측정 없음.
- 입력 변환의 rigid transform 불변성, 거리 보존, 오류 거부, synthetic export와 provenance.
- plan 명령의 미실행, eval-role/잘못된 데이터의 학습 전 거부, checkpoint 누락 오류 확인.

분리 GeoRT 환경의 Phase 7 테스트 **16개 통과**, SAPIEN의 pkg_resources deprecation warning
1건이 있다. 기존 환경 전체 테스트는 **139개 통과, 1개 skip**이다.
기존 환경에서 heavy GeoRT runtime 한 건은 의도적으로 skip하고 분리 환경에서 실행한다.
Ruff와 소스 보존 검사도 통과했다.

외부 Git 저장소 8개와 Phase 7 이전 프로젝트 파일 **96개**가 보존되었다.
기준은 `docs/phase7_existing_files.sha256.json`, 결과는 `results/phase7_source_integrity.json`이다.
`PROJECT_SPEC.md`의 이전 사용자 요청에 따른 17절 추가는 기존 prefix 보존 검사로 구분한다.

주요 실행 기록:

- `results/phase7_runtime_check_isolated_meshes.json`: 최종 FK/구조/CUDA 검사.
- `results/phase7_training_plan.json`: 실행되지 않은 학습 계획.
- `results/geort_dg5f_workspace/preparation.json`: 준비 자산과 입력 규약.

## 추가 파일과 남은 작업

- `configs/geort_dg5f_right.json`.
- `benchmark/geort_support/{source,input,assets,runtime,training,cli}.py`.
- `benchmark/retargeting/geort.py`, `scripts/run_geort.py`.
- `requirements/phase7.txt`, `phase7-torch.txt`, `phase7-environment.lock.txt`.
- `tests/test_phase7_geort.py`, `scripts/verify_phase7_sources.py`.
- `docs/phase7_existing_files.sha256.json`, `README_PHASE7.md`, 이 보고서.

요청 범위인 학습 전 구현 준비와 검증을 마쳤다.
데이터 수집은 사용자가 별도로 진행하며 실제 학습·checkpoint 추론·성능 평가,
학습/평가 데이터의 중복 검증 및 네 방법 전체 비교는 추후 작업으로 남아 있다.
SHOW3D 연결도 이번 단계에 포함하지 않았다.
