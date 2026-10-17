# Phase 5 결과 — 원본 AnyDex와 공개 데이터 재생

## 구현과 원본 보존

AnyDex 고정 commit `ee68a0234ccdf8a23b98527fd1ee2c6258278cd1`의
`Retargeter` / `AdaptiveOptimizerAnalytical`를 checkout 경로에서 직접 import한다.
모듈 가로채기, monkeypatch, 최적화 수식 재작성, 원본 소스 수정은 하지 않았다.
실행 전 commit·tracked source 무변경을 검사하며 Python source SHA256을 로그에 남긴다.

신규 `benchmark/retargeting/anydex.py`의 `model_config`는 다음만 지정한다.

- 공식 DG-5F 오른손 URDF 절대 경로 및 palm `rl_dg_palm`.
- 실제 손끝 `rl_dg_[1-5]_tip`, offset 0.
- thumb CMC root `rl_dg_1_1`, non-thumb MCP flexion-axis root `rl_dg_[2-5]_2`.
- PIP/중간 link `rl_dg_[1-5]_3`, DIP/말단 link `rl_dg_[1-5]_4`, offset 0.
- 5 fingers와 neutral_qpos=None: 최초 해는 원본 정책인 관절 범위 중간값으로 시작.

알려지지 않은 robot type은 upstream에서 Shadow defaults를 fallback으로 읽는다.
위 robot 관련 필드를 모두 명시해 Shadow link/offset/neutral 값이 유입되지 않게 했다.
원본 설정 확장 API를 사용하므로 `ROBOT_CONFIGS` 원본에 항목을 추가하지 않았다.
Pinocchio 관절 순서를 이름으로 공통 DG-5F 20개 순서로 재배열한다.

이 baseline은 **upstream 코드 기본값**을 사용한다. 다른 로봇용 YAML의 보정값을
DG-5F용으로 가져오거나, 수치를 학습해 개선하지 않았다. 공식 Quest/Wuji YAML과 같은
파라미터라는 뜻은 아니다. `retarget: {}`를 통해 다음 코드 기본값을 사용한다.

| 항목 | 원본 코드 기본값 |
|---|---|
| optimizer | NLopt LD_SLSQP, maxeval 50, ftol_abs 1e-4 |
| huber_delta / huber_delta_dir | 2.0 cm / 0.5 |
| norm_delta | 0.04 |
| w_pos / w_dir / w_full_hand / w_contact | 1 / 10 / 1 / 0 |
| pinch alpha maximum | 0.7 |
| pinch thresholds | 각 non-thumb d1=2 cm, d2=4 cm |
| pinch/lateral/segment scaling | 1.0 |
| project_tip_dir | false |
| 추가 rotation | 없음 |
| LPFilter | 원본 default alpha=0.2, 활성화 |

입력은 기존 `world_points`로 복원해 원본 `apply_mediapipe_transformations`에 전달한다.
이 함수의 wrist 중심화와 SVD frame 계산을 유지한다. 원본 solver의 warm start,
실패 시 fallback, regularization, Huber loss와 adaptive pinch 계산도 그대로다.
NLopt code 5/6은 각각 횟수/시간 예산 도달로 보고하고 음수는 failure/fallback으로 남긴다.
목표값을 튜닝하거나 pinch 성공을 만들기 위한 수정은 하지 않았다.

## 공개 데이터 감사

| 항목 | GeoRT human_alex.npy | AnyDex avp1.pkl |
|---|---|---|
| 파일 | 3,498 × 21 × 3 float64 ndarray | 2,751개 dict의 list, t/left_fingers/right_fingers |
| 크기 | 1,763,120 bytes | 1,689,467 bytes |
| 관절 | wrist 0, thumb 1–4, index 5–8, middle 9–12, ring 13–16, pinky 17–20 | 이미 공식 코드가 21개로 선택한 같은 순서 |
| 오른손 근거 | right-hand 예제 및 canonical geometry에 일관됨; per-frame label 없음 | right_fingers key |
| 추적 방식 | 제공 MANUS FK bone 길이와 일치; 정확한 샘플 수집 경위 미기재 | 공식 avp1 예제와 VisionPro 변환 코드에 근거한 Vision Pro 추정 skeleton |
| 단위/좌표 | m 해석이 MANUS FK와 일치, wrist 중심 canonical RH | m 해석이 공식 translation 출력/손 크기와 일치, wrist 상대 RH |
| 원본 시간 | 없음 | 모든 t=0 |
| 참가자 | 미공개; 파일명 Alex를 검증된 ID로 사용하지 않음 | 미공개 |
| split | 개발 전용; 원래 upstream 학습 예제 | 개발 전용; 공식 replay 예제 |
| 라이선스 | repository CC-BY-NC-4.0, 별도 데이터 라이선스 미발견 | repository MIT, 별도 데이터 라이선스 미발견 |

GeoRT commit은 `fb2075e2a3272be372016580c0b6ebd6120228f0`이다.
단위와 수집 방식은 파일 내 tag로 확인된 사실과 소스·geometry로 추론한 내용을 구분했다.
전체 GeoRT 프레임의 15개 finger segment 길이가 원본 MANUS FK 상수와 맞으며 최대 차이는
약 5.9e-17 m였다. Wrist와 다섯 root도 모든 프레임에서 고정되어 있다.
이는 MANUS FK와의 일관성 근거이며 파일 수집 경위 전체를 증명하는 것은 아니다.

AnyDex 원본 VisionPro 선택 인덱스는
`0,1,2,3,4,6,7,8,9,11,12,13,14,16,17,18,19,21,22,23,24`다.
저장 파일은 이미 21개이므로 재선택하지 않고 identity mapping을 적용한다.
두 입력 모두 점을 추가·보간·padding하지 않는다. 각 프레임 shape, finite 값,
wrist 원점과 meter 규모의 palm/bone 길이를 검사한다.

원래 wrist world pose와 관절 rotation은 없다. `joint_rotations=None`,
`wrist_pose_measured=false`이며 HandFrame의 identity wrist pose는 local 좌표를 공통
인터페이스에 담기 위한 명시적인 좌표 embedding이다. 실제 측정 pose로 평가하지 않는다.
시간은 `timestamp_domain=dataset_assumed_replay`이며 기본 30 FPS는 재생용 가정이다.
원본 frame index, 원본 timestamp 부재/0, 단위 근거, handedness 근거,
repository/commit/hash/license/tracking method를 metadata에 보존한다.
Quest SDK/WebXR 실측 출력과 구분해 `is_quest_sdk_output=false`를 기록한다.

GeoRT 라이선스의 비상업 조건은 원본 LICENSE에 명시되어 있다. 다운로드 사본 옆에도
LICENSE를 보존한다. 파일별 라이선스 허가가 별도로 확인된 것으로 해석하지 않는다.

### 동작 추출 가능성과 중복

고정된 기하학 기준으로 확인한 **후보 프레임** 수다. 제공 gesture label은 없으며,
선정 결과를 학습·평가의 정답 label로 바꾸지 않는다.

| 후보 | GeoRT | AnyDex |
|---|---:|---:|
| Open: non-thumb 모든 PIP/DIP <25°, 모든 abs(MCP)<25° | 886 | 298 |
| Fist: non-thumb 모든 PIP>60°, 모든 MCP>45° | 0 | 323 |
| Pinch: thumb–index distance / wrist–middle MCP <0.35 | 1,215 | 85 |
| 완전히 동일한 pose의 중복 프레임 수 | 264 | 1,641 |

GeoRT에서 이 조건의 Fist는 추출하지 못했다. 임의 pose를 만들거나 임계값을 바꿔
후보가 있다고 주장하지 않는다. AnyDex Fist 첫 후보는 index 625,
Pinch 첫 후보는 206이다. 전체 후보 개수와 첫 index 목록은 데이터 감사 JSON에 있다.

두 파일 사이의 exact pose hash 중복은 0이다. 알려진 source hash·sequence·participant
중복 검사는 train/eval 그룹 간 겹침을 거부한다. 두 예제 모두 참가자 ID가 없으므로
참가자 비중복은 검증할 수 없다. 같은 파일을 프레임 단위로 무작위 분할하지 않으며,
추후 GeoRT 학습에 쓸 파일을 동시에 held-out 평가에 사용하지 않는다.

## 실제 실행 결과

전체 테스트 **112개 통과**. 추가 14개에는 원본 직접 호출과 adapter 출력 일치,
Pinocchio–MuJoCo FK/Jacobian 비교 및 중앙차분, reset 재현성, 공개 입력 변환/재생,
동일 입력 hash, 마지막 프레임 소비, 원본 타이밍 부재, 누락 점/단위 오류 거부,
split 중복 검사와 tracking loss hold가 포함된다.
기존 native SWIG/coal 패키지의 deprecation warning 3건이 있으며 테스트 실패는 없다.
Ruff와 `uv pip check`도 통과했다.

외부 Git 저장소 8개는 고정 commit에서 clean이다. 원래 261개 파일의 보존을 검사하되,
사용자가 요청한 PROJECT_SPEC 17절 추가는 원래 prefix hash가 보존된 허용 변경으로 구분했다.
Phase 5 시작 전 기존 프로젝트 파일 74개는 모두 그대로다.

두 공개 시퀀스 모두 같은 50 Hz 제어, 0.002 s physics timestep, pi rad/s 명령 제한,
250 ms timeout, 동일한 DG-5F 모델과 contact disabled 조건으로 실행했다.
각 source 프레임의 원본 순서를 유지하며 마지막 프레임까지 소비한다.
MANUS/AnyDex의 입력 스트림 SHA256이 일치하는 것을 검증했다.
초기 동역학 상태는 모두 영 자세이며, optimizer 내부의 초기값과 필터는 원본 정책을 유지한다.

측정값은 아래 표에 추가하며, 정확한 값과 실행 경로는
`results/phase5_validation_latest.json` 및 실행별 `validation.json`을 기준으로 한다.

| 입력 | 방법 | 평가 source 프레임 | 평균 처리 ms | P95 ms | 평균 정규화 tip 대응 오차 | 횟수 예산 도달 |
|---|---|---:|---:|---:|---:|---:|
| geort_alex | manus | 3498 | 0.145 | 0.154 | 0.5034 | 0 |
| geort_alex | anydex | 3498 | 8.681 | 14.301 | 0.2057 | 49 |
| anydex_avp1 | manus | 2751 | 0.144 | 0.153 | 0.5829 | 0 |
| anydex_avp1 | anydex | 2751 | 6.861 | 15.136 | 0.1865 | 160 |

기구학 지표는 공통 제한 후 pipeline 목표각의 FK를 비교한다. AnyDex의 기본 출력 필터가
포함된 pipeline 결과다. 사람은 wrist 기준 distal/radial palm frame,
로봇은 URDF palm frame을 사용하고 각각 wrist/palm→middle MCP 길이로 정규화한다.
손 크기/원점 정의와 추정 skeleton 품질에 영향을 받는 개발용 대응 지표이므로,
이 결과를 일반적인 정확도 순위나 독립 GT에 대한 성능으로 주장하지 않는다.
Clipping에는 float32 결과의 관절 경계 반올림도 포함된다.
시간은 adapter와 원본 verbose 전처리·solve·filter·진단 계산을 포함하고
수신, 시뮬레이션, FK 평가 지표, logging, 렌더링은 제외한 로컬 wall time이다.
Pinch 접촉·물체 grasp 성공은 검사하지 않았다.

전체 비교 로그와 90프레임씩의 영상 4개를 실제 생성하고 AnyDex 영상 프레임도 확인했다.
Quest 하드웨어 없이 실행되는 공개 입력→두 retargeter→MuJoCo 경로가 검증됐다.

## 생성 파일과 다음 단계

- `benchmark/retargeting/anydex.py`: 원본 AnyDex와 DG-5F의 연결.
- `benchmark/datasets/public.py`, `configs/public_datasets.json`: 두 공개 입력 adapter와 감사.
- `benchmark/experiments/offline_benchmark.py`: 동일 입력·공통 제어·기구학 지표 실행.
- `requirements/phase5.txt`: 추가 의존성과 ABI 호환 버전.
- `scripts/run_offline_benchmark.py`, `validate_phase5.py`, `verify_phase5_sources.py`.
- `tests/test_phase5_anydex.py`, `README_PHASE5.md`, 이 보고서.
- `data/public/`: 작은 원본 예제 사본 2개 및 LICENSE.

후속 공개 데이터 연결 대상으로 [공식 SHOW3D 코드](https://github.com/facebookresearch/show3d)
및 [데이터 카드](https://huggingface.co/datasets/facebook/show3d-dataset)를 확인했다.
공식 API는 subject/scene/frame을 선택하며 21개 world landmarks를 millimeter로 제공한다.
SHOW3D 촬영에 Quest 3가 쓰여도 이 pose를 Quest SDK 출력과 동일시하지 않는다.
다음 데이터 작업에서는 버전과 라이선스·실제 joint order를 확인한 뒤 한 scene의 작은 pose
구간만 받아 명시적인 adapter를 작성한다. 이번 단계에서 SHOW3D를 다운로드하거나 연결하지 않았다.

Wuji와 GeoRT optimizer/모델은 미구현이며 선택 시 NotImplementedError로 실패한다.
Phase 6·7에서 원본 구현과 필요한 모델 설정/학습을 연결해야 네 방법 비교가 완성된다.
