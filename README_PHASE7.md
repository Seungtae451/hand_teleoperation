# Phase 7 — GeoRT 구현 준비 (수집·학습·평가 보류)

현재 범위는 **원본 GeoRT와 DG-5F의 연결 구현 및 학습 전 검증**이다.
데이터 수집은 사용자가 따로 진행한다. 이번 단계에서 실제 학습, 성능 평가,
학습되지 않은 모델의 추론이나 임시 checkpoint 생성은 실행하지 않았다.

원본 Git 소스를 유지하고 별도 설정·adapter·실행기를 추가했다.

- DG-5F: 20개 관절, 다섯 손끝, 실제 URDF chain과 관절 범위.
- 입력: 공통 `HandFrame` → 원본 GeoRT 오른손 canonical 21개 점, meter 단위.
- 실행 준비: 데이터 export, 학습 계획/실행 진입점, 실제 checkpoint를 요구하는 추론 adapter.
- 검증: 원본 SAPIEN 모델 로딩, MuJoCo와 FK 대조, 네트워크 구조 및 입력 오류 처리.

## 지금 실행할 명령

현재 PC에 `.venv-geort`와 `results/geort_dg5f_workspace`를 준비했다.
아래 두 명령은 학습이나 성능 평가를 시작하지 않는다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation

# 원본 SAPIEN FK·20개 관절·다섯 손끝·CUDA 환경 검사
MUJOCO_GL=egl .venv-geort/bin/python scripts/run_geort.py check \
  --workspace results/geort_dg5f_workspace

# 데이터가 없어도 출력할 수 있는 학습 계획. 실행은 하지 않는다.
.venv-geort/bin/python scripts/run_geort.py train \
  --workspace results/geort_dg5f_workspace
```

`check`는 세 관절 자세의 기하학 검증과 구조 검사를 수행한다.
신경망은 구조만 생성하고 forward·학습·checkpoint 저장을 하지 않는다.
CUDA 확인에 사용하는 scalar 연산도 모델 추론이나 성능 벤치마크가 아니다.
`train`의 기본 출력은 `mode: plan_only`, `training_executed: false`다.

## 분리 환경과 재현

원본의 SAPIEN 2.x API와 NumPy ABI를 유지하기 위해 기존 `.venv`와 환경을 분리했다.
검증 조합은 Python 3.10, PyTorch 2.7.1+cu128, SAPIEN 2.2.2,
NumPy 1.26.4, Open3D 0.19.0, MuJoCo 3.16.0이다.
RTX 5080 두 장 인식과 CUDA scalar 실행을 확인했다.
기존 `.venv`의 NumPy 2 환경과 Phase 1–6 dependencies는 변경하지 않았다.

새 환경에서는 다음 순서로 준비한다. Torch 배포 URL은
[공식 버전별 설치 안내](https://pytorch.org/get-started/previous-versions/)를 기준으로 했다.

```bash
uv venv .venv-geort --python 3.10
uv pip install --python .venv-geort/bin/python -r requirements/phase7-torch.txt
uv pip install --python .venv-geort/bin/python -r requirements/phase7.txt
uv pip check --python .venv-geort/bin/python

# 새 workspace만 허용한다. 이미 준비했다면 다시 실행할 필요가 없다.
.venv-geort/bin/python scripts/run_geort.py prepare \
  --workspace results/geort_dg5f_workspace
```

전체 설치 버전은 `requirements/phase7-environment.lock.txt`에 기록했다.
같은 버전을 재현하려면 아래 명령을 사용할 수 있다.

```bash
uv pip install --python .venv-geort/bin/python \
  --extra-index-url https://download.pytorch.org/whl/cu128 \
  --index-strategy unsafe-best-match -r requirements/phase7-environment.lock.txt
```

기존 프로젝트 패키지를 새 환경에 editable install할 필요는 없다.
`run_geort.py`는 프로젝트 루트를 명시하여 소스를 읽는다.
GeoRT의 camera·ROS·MANUS SDK 경로는 실행하지 않으며 torchvision/torchaudio 등
현재 core 경로가 사용하지 않는 전체 예제 의존성을 설치했다고 주장하지 않는다.
원본 trainer 모듈 import까지 검증했다.

## 로봇 설정과 workspace

`configs/geort_dg5f_right.json`은 공식 GeoRT 설정 형식을 따른다.
`prepare`는 다음을 새 workspace에 생성한다.

- `config.json`: 실제 joint order, tip/chain, human IDs `[4,8,12,16,20]`, 관절 범위.
- `dg5f_right_resolved.urdf`: mesh 경로만 로컬 사본으로 변경한 파생 URDF.
- `meshes/`: 공식 mesh의 byte 단위 사본. SAPIEN convex cache도 이 폴더에 생성된다.
- `preparation.json`: 원본 commit/hash, 파생 파일·mesh hash와 입력 규약, 미실행 상태.

원본 URDF의 joint·inertial·visual·collision geometry를 유지한다.
SAPIEN은 mesh 옆에 cache를 쓰므로 원본 파일을 직접 참조하지 않고 사본을 사용한다.
외부 저장소와 기존 모델 파일은 변경하지 않는다. 기존 workspace를 덮어쓰지 않는다.

## 추후 사용자 데이터 연결

수집 기능을 새로 실행하거나 사용자 녹화를 이번 단계에서 학습 데이터로 export하지 않았다.
나중에 수집한 데이터가 공통 HandFrame JSONL이라면 다음 경로를 사용한다.

```bash
# 추후 수집 후 사용. input 경로는 실제 녹화 파일로 바꾼다.
.venv-geort/bin/python scripts/run_geort.py export-input \
  --input recordings/YOUR_SESSION.jsonl \
  --output data/geort/YOUR_TRAIN_SESSION --split train --drop-invalid
```

입력은 오른손 21개 점을 모두 포함해야 한다. 누락 점을 만들거나 자동 단위 보정을 하지 않는다.
원본 `hand_to_canonical`을 그대로 사용한다. wrist0가 원점, Z는 0→9,
Y 보조축은 13→5이며, 이것은 기존 benchmark palm의 17→5 정의와 다르다.
학습 데이터와 추론 입력에 같은 GeoRT 변환을 적용한다.

원본 recording을 유지하고 `human.npy`와 `manifest.json`을 별도로 생성한다.
manifest에 원본 hash, split, 포함 frame의 시간·출처 metadata, 제외한 무효 frame 수를 남긴다.
`--drop-invalid`가 없으면 무효 입력에서 오류로 중단한다. 참가자 정보가 없으면
subject-disjoint를 검증했다고 표시하지 않는다. 이 단계는 자동 split이나 성능 보정이 아니다.

실제 학습은 **추후 별도로 결정한 뒤** 아래와 같이 명시적으로 실행할 수 있도록 구현했다.
지금 이 명령을 실행한 것은 아니다.

```bash
.venv-geort/bin/python scripts/run_geort.py train \
  --workspace results/geort_dg5f_workspace \
  --human-data data/geort/YOUR_TRAIN_SESSION/human.npy \
  --manifest data/geort/YOUR_TRAIN_SESSION/manifest.json --execute
```

실행 시 새 `training-*` 하위 폴더를 작업 디렉터리로 사용하여 원본의 상대 data/checkpoint
출력이 외부 저장소에 생기지 않게 한다. 기본 FK 200 epochs와 IK 200 epochs,
원본 loss·optimizer·sampling을 유지한다. 필요한 neural FK가 없으면 원본이 먼저 학습한다.
실제 학습 메모리 사용량·소요 시간·수렴·결과 checkpoint는 아직 검증하지 않았다.

## 추후 checkpoint 추론

원본 `GeoRTRetargetingModel(model_path, config_path)`를 직접 호출한다.
모호한 tag 검색이나 다른 로봇용 checkpoint, 임의 초기화 출력으로 대체하지 않는다.
DG-5F의 20개 관절·다섯 손끝·관절 범위가 맞는 export config가 필요하다.

```bash
# 실제 학습 완료 후 사용. 파일 경로를 실제 산출물로 바꾼다.
MUJOCO_GL=glfw .venv-geort/bin/python scripts/run_geort.py infer \
  --input recordings/YOUR_SESSION.jsonl \
  --checkpoint PATH_TO_TRAINED_DG5F/last.pth \
  --config PATH_TO_TRAINED_DG5F/config.json --frames 150 --viewer
```

공통 MuJoCo runner의 목표·명령·실제 상태 구분과 제어 정책을 재사용한다.
checkpoint가 없으면 명확히 실패한다. 현재 실제 GeoRT 추론과 네 방법 비교는 미검증이다.

## 테스트와 상태 보고서

```bash
# 기존 환경의 전체 회귀 테스트 (GeoRT heavy runtime 한 건은 의도적으로 skip)
MUJOCO_GL=egl .venv/bin/python -m pytest -q

# 원본 SAPIEN·CUDA 환경을 포함한 Phase 7 테스트
GEORT_RUNTIME_TEST=1 MUJOCO_GL=egl \
  .venv-geort/bin/python -m pytest tests/test_phase7_geort.py -q

.venv/bin/ruff check benchmark scripts tests
.venv/bin/python scripts/verify_phase7_sources.py
```

runtime 검사 기록은 `results/phase7_runtime_check_isolated_meshes.json`,
원본 보존 확인은 `results/phase7_source_integrity.json`, 학습 계획은
`results/phase7_training_plan.json`에 저장했다.
상세 범위와 미검증 항목은 [PHASE7_REPORT.md](docs/PHASE7_REPORT.md)를 따른다.
