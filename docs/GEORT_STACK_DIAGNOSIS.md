# 손 모양 불일치 원인 분리 — 2026-10-18

**현재 증거로는 MuJoCo에 관절값을 잘못 올리는 문제가 주원인은 아니다. 직접 데이터를 대량으로
더 수집하기 전에 GeoRT가 DG-5F에 대해 만드는 관절 자세와 로봇 설정을 검증해야 한다.**
학습 절차가 실행되지 않았다는 뜻은 아니다. 원본 loss를 학습한 결과가 원하는 인간 손 자세를
충분히 재현하지 못하고 있다는 뜻이다. 단일 seed 결과만으로 근본 원인 하나를 확정하지 않는다.

이번 검사는 최근 실행 세션 `results/live-retargeting-o6axl2lk`의 실제 기록을 사용했다.
새 parity 모델 3개와 공식 **데이터로 우리 DG-5F 설정에서 학습한** 모델의 체크포인트 해시가
세션 설정과 일치한다. 여기서 공식 데이터 모델은 저자가 배포한 검증 완료 DG-5F 가중치가 아니다.
검사 범위는 네 GeoRT 모델이며, AnyDex·Wuji·MANUS-style의 동작 원인을 함께 검증한 것은 아니다.

## 단계별 측정

최근 세션에서 유효 오른손 5,790프레임을 읽고, 그중 균등 간격 512프레임을 추론했다.
새 학습·원본 수정·test split 점수 계산은 하지 않았다.

| 확인한 경계 | 결과 | 의미 |
|---|---|---|
| GeoRT joint_order ↔ MuJoCo 이름 | 20개 순서와 한계 일치 | 관절 배열이 바뀐 증거 없음 |
| SAPIEN 정확 FK ↔ MuJoCo 정확 FK | 손끝 최대 0.001585 mm | 1,045개 자세에서 시뮬레이터 기구학 일치 |
| 링크 원점 SAPIEN ↔ MuJoCo | 최대 0.001359 mm | 중간 링크도 단일 관절 동작에서 일치 |
| 신경망 FK ↔ 실제 FK | 무작위 관절 1,024개 평균 2.15 mm, 최대 9.83 mm | 학습용 FK 근사 오차는 있으나 수십 mm 차이 전체의 설명은 어려움 |
| 새 10k 모델 출력에서 신경망 FK ↔ 실제 FK | 평균 2.53 mm, 최대 7.18 mm | 모델이 선택한 자세에서도 근사 FK 오차는 상대적으로 작음 |
| 새 10k 세션 명령 ↔ 실제 손끝 | 평균 0.678 mm, P95 2.89 mm | MuJoCo는 적용된 명령을 잘 추종 |
| 새 10k 세션 모델 목표 ↔ 실제 손끝 | 평균 13.06 mm, P95 76.09 mm | 매 5번째 TRACKING tick; 속도 제한에 의한 과도 지연도 포함 |
| 일정 목표 4초 유지 | 모델별 8개 자세, 최대 관절 잔차 약 9e-16 rad | 현재 무접촉 설정에서 지속적인 자세 추종 실패는 확인되지 않음 |

모델 목표와 적용 명령의 최대 관절 차이를 매 tick 구하면 새 10k에서 평균 0.579 rad다.
반면 적용 명령과 실제 관절의 최대 차이는 평균 0.0143 rad다.
빠른 움직임에서는 공통 π rad/s 제한의 지연이 있으나, 잘못된 목표 자세는 기다려도 그대로 남는다.
이번 검사에서 제한을 없애거나 제어 게인을 바꾸지 않았다.

고정 목표 검사는 모델 출력의 추종 여부이며 인간 손의 정확한 재현을 보증하지 않는다.
시뮬레이터 간 검사는 기구학과 링크 원점을 검증한다. STL 표면·접촉 패드·실제 하드웨어 보정까지
인증하는 검사는 아니다. 현재 MuJoCo는 공식 STL collision mesh로 렌더링하며 접촉은 비활성이다.

## 모델이 이미 다른 자세를 만든다

동일 인간 입력과 **제어기를 통과하기 전 목표 자세**를 겹쳐 그렸다.

![인간 입력과 모델 목표의 측면 비교](../results/geort-stack-audit-f4pfvpoq/posture_examples.png)

회색 점선은 인간, 색 선은 로봇이며 X–Z 측면이다. 원점은 각각 wrist와 palm이다.
각 열은 모든 모델에서 같은 실제 기록 프레임을 쓴다. 후보는 동작 정답 라벨이 아닌 기하 선택이다.
로봇 선은 실제 URDF 링크 원점들을 연결하므로 인간의 21관절과 일대일 관절 대응 그림은 아니다.

펼친 손 후보 32개의 인간 비엄지 PIP 평균 굽힘은 약 1.99°다.
그 입력에서 새 10k 모델의 검지 2·3·4번 관절 평균은 약 `[25.5, -28.5, -38.5]°`,
중지는 `[19.2, 54.7, 87.9]°`다. 사람의 펼친 손과 다른 목표가 이미 만들어지고 있다.
사람의 PIP를 로봇 관절과 수치상 같게 만들라는 뜻이 아니라, 모델이 펼친 자세를 유지하지 않는다는 관찰이다.

새 10k 모델은 이 512프레임에서 비엄지 3·4번 관절값 중 약 42.2%를 -0.05 rad 미만으로 출력한다.
공식 URDF는 이 관절에 ±90°를 허용한다. 따라서 관절 한계 검사에는 통과하면서도 인간의 자연스러운
굴곡과 다른 역방향 굽힘·관절 상쇄를 선택할 수 있다. 음수 자체가 항상 잘못된 동작이라는 판정은 아니다.

## 직접 수집하면 해결되는가

그렇게 단정할 근거는 없다. 새 10k 모델에서:

- 실제 입력의 최근접 학습 손끝 거리는 평균 4.14 mm, 5 mm 초과는 손끝 표본의 약 32.3%다.
  일부 입력 분포 차이와 커버리지 부족은 남는다.
- 자기 학습 데이터 512개에서도 인간–모델 손끝 대응 거리는 평균 40.13 mm다.
  최근 실제 입력에서는 48.63 mm다. 학습 입력에서도 큰 차이가 있어 일반화 문제만은 아니다.
- 기존 robot-only 100,000개 관절 샘플에서 손가락마다 가장 가까운 표본을 골라 조합하면,
  같은 실제 입력에 평균 8.38 mm까지 접근한다. 실제 FK로 확인했다.
  따라서 관측된 48.63 mm가 전부 로봇의 도달 불가능성 때문인 것은 아니다.

마지막 검사는 **도달 가능성 진단용 검색**이며 새 retargeting 알고리즘이나 평가 baseline이 아니다.
손가락별 관절이 독립이라는 설정을 사용하며, 충돌·접촉·자연스러운 중간 관절 자세는 보장하지 않는다.
이 진단으로 기존 모델을 교체하지 않았다.
모든 인간–로봇 거리는 wrist/palm을 각 원점으로 하는 원시 좌표 거리로, 독립 정답 pose 오차가 아니다.
이전 보고서의 52.71 mm와 이번 48.63 mm는 입력 세션이 다르므로 성능 변화로 해석하지 않는다.

## 코드에서 확인한 원리와 남은 가설

원본 `external/GeoRT/geort/model.py`의 IKModel은 손가락마다 **3차원 손끝 하나 → 관절 4개**를
입력·출력한다. 21개 관절을 보존해도 실제 네트워크에는 다섯 손끝만 전달한다.
같은 손끝 위치를 만드는 여러 중간 관절 자세를 인간의 관절 자세에 맞춰 구분할 정보가 부족하다.

원본 `trainer.py`의 목적함수는 주변 입력 이동 방향, 손끝 point cloud의 Chamfer 거리,
curvature, pinch 항이다. 인간–로봇 전체 관절의 자세 정답을 맞추는 supervised loss가 아니다.
`dataset.py`는 손가락별 point cloud를 각각 voxel downsample·독립 재표본화한다.
학습 batch의 다섯 손끝이 원래 기록된 동일 프레임의 조합일 필요도 없다.
이 동작은 원본 구현이며 이번 작업에서 바꾸지 않았다.

따라서 데이터 수를 늘렸다고 펼친 손·주먹·모든 중간 관절의 의미가 자동으로 보장되지는 않는다.
DG-5F의 넓은 양방향 관절 범위와 전체 범위 무작위 robot cloud가 현재 결과에 얼마나 기여했는지,
원본이 지원하는 다른 로봇에서도 같은 재현 환경에서 문제가 발생하는지,
학습 seed·수렴 상태의 영향이 얼마나 큰지는 아직 분리하지 않았다.
전체 관절 pose loss나 임의 joint coupling을 추가하면 사용자의 목표인 원본 baseline 재현과 달라지므로
그런 변경은 하지 않았다.

## 권장 순서

1. **원본 지원 로봇을 대조군으로 재현한다.** 공식 human_alex + 원본 Allegro 설정으로 같은 코드·환경의
   동작을 확인한다. DG-5F 설정에 국한된 문제인지 일반적인 재현 문제인지 분리한다.
2. **DG-5F의 로봇별 설정을 공식 문서·제조사 예제와 대조한다.** 기준 축, 손끝점, 관절 범위와
   실제 사용하는 굽힘 방향을 확인한다. 시뮬레이터끼리 같다는 사실과 알고리즘에 적합한 로봇 설정이라는
   주장은 다르다. 범위를 임의로 줄여 좋은 결과를 만들지 않고, 근거와 비교 조건을 먼저 고정한다.
3. 그 검사가 끝난 뒤 같은 WebXR 경로에서 손가락별 운동 범위·펼친 손·각 thumb pinch를 담은
   작은 검증 시퀀스를 사용한다. 기존 개인 녹화도 진단에 활용할 수 있으므로 대규모 재수집부터 할 필요는 없다.
4. 입력 분포 문제가 남는 것으로 확인되면 직접 수집을 별도 학습 조건으로 추가한다.
   공개 데이터 수에 따른 실험은 그대로 남기고, 수집 경로와 평가 조건을 분리한다.

이번에는 분석 코드와 보고서만 추가했다. 모델·제어기·기존 기록·공식 URDF·외부 Git 코드는 수정하지 않았다.

## 재현 및 근거 파일

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
.venv-geort/bin/python scripts/audit_geort_stack.py \
  --session results/live-retargeting-o6axl2lk
# 위 명령이 출력하는 새 audit 폴더 경로를 아래 --audit에 사용한다.
.venv-geort/bin/python scripts/probe_geort_reachability.py \
  --audit results/geort-stack-audit-f4pfvpoq
.venv-geort/bin/python scripts/plot_geort_stack.py \
  --audit results/geort-stack-audit-f4pfvpoq
```

기준 산출물: `results/geort-stack-audit-f4pfvpoq/`의 `audit.json`, `reachability.json`,
`*_targets.npz`, `posture_examples.png`, `source_integrity.json`.
새 코드 Ruff 통과. FK 일치 assertion과 실제 모델·MuJoCo 추종 검사를 실행했다.
외부 저장소 8개 clean, 기존 Phase 7 이전 파일 96개 변경 없음.

## 후속: 공식 Allegro 대조 실험 완료

`results/geort_allegro_control_20261018/`에 원본 Allegro 대조군을 실제 학습했다.
GeoRT pinned commit의 sparse checkout에 없던 assets와 제공 FK 가중치는 `git archive`로
결과 폴더에 byte-identical 추출했다. 원본 checkout과 sparse 설정은 변경하지 않았다.

- 원본 `allegro_right.json`에서 실행 경로인 `urdf_path`만 복사본 경로로 변경했다.
- 원본 Allegro URDF·손끝 offset·관절 순서·관절 범위·loss·optimizer는 그대로다.
- 공식 제공 `fk_model_allegro_right.pth`와 원본 방식으로 생성한 robot-only 100,000개 샘플을 공유했다.
- 공식 `human_alex.npy` 3,498프레임, 개인 Quest 학습 12,998프레임으로 각각 IK 200 epoch 완료.
- seed는 두 조건 모두 20261018. 학습 시간은 각각 약 98초·101초였다.
- 기존 DG-5F의 공식 데이터 모델과 개인 데이터 모델을 같은 인간 입력에서 대조했다.
  기존 모델과 녹화, 원본 Git 코드를 변경하지 않았다.

### 같은 Quest 평가 입력에서의 결과

네 모델 모두 같은 평가 녹화를 사용했다. 비교 가능한 검지·중지·약지의 PIP와 MCP 기하 기준으로
펼친 손 869개·주먹 433개 후보를 선택하고 각 후보군에서 최대 256개를 균등 추출했다.
기존 4손가락 전체 주먹 검사와 달리 새끼를 제외한 공통 3손가락 기준이라 후보 수가 다르다.

개인 Quest 데이터로 학습한 두 모델의 **세 번째 관절 목표 평균**:

| 로봇 | 검지: 펼친 손 → 주먹 | 중지: 펼친 손 → 주먹 | 약지: 펼친 손 → 주먹 |
|---|---:|---:|---:|
| Allegro | −4.6° → +97.5° | −8.4° → +97.5° | −8.2° → +96.6° |
| DG-5F | −53.2° → −46.1° | +58.6° → −70.9° | −37.8° → −85.5° |

인간 PIP 굽힘과 로봇 굽힘 관절 3개의 합계 간 Spearman 상관을 같은 평가 프레임 512개에서 계산했다.
이 값은 방향 반응 진단이며 인간과 로봇 관절 각도를 일대일 정답으로 취급하지 않는다.

| 조건 | 검지 | 중지 | 약지 |
|---|---:|---:|---:|
| Allegro / 공식 데이터 학습 | +0.953 | +0.894 | +0.967 |
| DG-5F / 공식 데이터 학습 | +0.895 | +0.409 | +0.441 |
| Allegro / 개인 Quest 학습 | +0.974 | +0.955 | +0.973 |
| DG-5F / 개인 Quest 학습 | +0.873 | **−0.677** | +0.373 |

Allegro는 두 입력 조건에서 펼친 손→주먹에 따라 자연스러운 굽힘 방향으로 움직였다.
현재 DG-5F 개인 모델의 중지 역방향 반응은 이 대조군에서 재현되지 않았다.
다만 Allegro도 펼친 손에서 굽힘 합계가 38~50° 정도 남는다. 완벽한 손 자세 복제를 확인한 것은 아니다.

실제 같은 평가 프레임의 정적 모델 목표 그림:

![Allegro와 DG-5F의 같은 입력 자세 비교](../results/geort_allegro_control_20261018/pose_comparison.png)

각 행은 두 로봇에서 같은 실제 평가 프레임을 사용한다. 카메라 중심은 로봇 형상에 맞게 다르다.
제어기를 통과하기 전 목표를 qpos에 넣어 정적 형상을 비교한 것이며 동적 추종·충돌 검사는 아니다.
원시 손끝 거리는 두 로봇의 원점과 형상 차이가 크므로 로봇 간 정확도 순위로 사용하지 않는다.

### 기구학과 범위 확인

- Allegro도 SAPIEN과 MuJoCo의 256개 무작위 자세에서 손끝 FK 차이 최대 **0.0021 mm**로 일치했다.
- 공식 제공 Allegro 신경망 FK의 실제 FK 대비 평균 오차는 **1.65 mm**, 최대 4.56 mm다.
- Allegro 비엄지 세 번째 관절은 약 −9.97°~+97.92°, 네 번째는 −13.01°~+92.70°다.
  DG-5F의 해당 관절은 −90°~+90°라서 크게 다른 역방향 자세를 선택할 공간이 있다.
- Allegro의 원본 inertial 값은 MuJoCo의 관성 부등식 검사를 통과하지 않아, **비교용 파생 import에만**
  `balanceinertia=true`를 적용했다. 학습용 원본 URDF·관절 기구학은 바꾸지 않았다.
  이 파생 모델로 Allegro 동역학까지 검증했다고 주장하지 않는다.

### 결론과 아직 분리하지 못한 부분

**Quest 데이터가 잘못 기록되어서 어느 로봇에서도 주먹을 재현하지 못하는 상황은 아니다.**
같은 데이터와 원본 구현으로 Allegro에서는 굽힘 방향이 일관되게 학습된다.
또한 현재 역방향 동작은 SAPIEN→MuJoCo 변환 오류로 설명되지 않는다.
문제 범위는 DG-5F에서의 학습 매핑과 그 로봇의 관절 구성·도달 공간으로 좁혀졌다.

그렇다고 공식 DG-5F URDF가 잘못됐거나 넓은 관절 범위 하나만이 원인이라고 확정할 수는 없다.
공식 데이터로 학습한 DG-5F 모델은 같은 주먹 입력에서 중간 관절을 양의 방향으로 출력한다.
현재 개인 데이터 모델은 다른 해를 선택했으므로 데이터 분포와 학습 초기화·수렴의 영향도 남는다.
Allegro는 원본 제공 FK를 사용했고 DG-5F는 직접 학습한 FK를 사용한다. 같은 seed라도 FK를 새로
학습했는지에 따라 IK 초기화 전 RNG 소비가 달라지므로 두 로봇의 학습 경로가 완전히 통제된 것은 아니다.

GeoRT 기여자는 [공식 이슈 #14](https://github.com/facebookresearch/GeoRT/issues/14)에서
방향 loss가 인간 도달 공간의 경계에서 유효하지 않은 주변 점을 요구해, 경계 자세를 내부의 굽힌
자세로 옮길 수 있다고 설명했다. 해당 mask 수정은 그 댓글 시점에 구현하지 않았다고 밝혔다.
[이슈 #16](https://github.com/facebookresearch/GeoRT/issues/16)에서는 LEAP의 과도한 기본 관절
범위가 손끝 도달 공간 불일치를 일으킬 수 있다고 지적했다. 이는 이번 DG-5F 결과와 관련 있는
공식 근거지만, 다른 로봇에 대한 설명을 DG-5F 원인 증명으로 취급하지 않는다.

다음 원인 분리 실험은 DG-5F의 로봇별 학습 관절 범위를 근거에 따라 고정한 **별도 조건**과
기존 전체 범위 조건을, 동일 FK·초기화·데이터에서 대조하는 것이다. 범위를 바꾸면 실험 조건이
바뀌므로 기존 원본 baseline 결과와 구분해야 한다. 이번 작업에서는 범위나 원본 loss를 바꾸지 않았다.

### 재현

```bash
# 새 폴더를 사용한다. prepare/train은 기존 결과를 덮어쓰지 않는다.
.venv-geort/bin/python scripts/geort_allegro_control.py prepare \
  --output results/geort_allegro_control_reproduction
.venv-geort/bin/python scripts/geort_allegro_control.py train \
  --output results/geort_allegro_control_reproduction
.venv-geort/bin/python scripts/compare_allegro_control.py \
  --output results/geort_allegro_control_reproduction
MUJOCO_GL=egl .venv-geort/bin/python scripts/render_allegro_control.py \
  --output results/geort_allegro_control_reproduction
```

결과는 `comparison.json`, `comparison_*.npz`, `pose_comparison.png`,
`models/*/manifest.json`, 각 epoch console 로그에 보존했다.
두 조건의 0–199 epoch 로그·체크포인트 hash·복사 원본 asset hash·실제 FK 대조 검사를 통과했다.
새 코드 Ruff 통과, 외부 저장소 8개 clean, 기존 Phase 7 이전 파일 96개 변경 없음.

## 후속: DG-5F 학습 범위 제한 실험 완료

사용자 요청에 따라 `results/geort_range_study_20261018/`에서 별도 범위 실험을 수행했다.
**학습용 파생 URDF에서 검지·중지·약지·새끼의 3·4번 관절 8개 하한만 −90°→0°로 변경했다.**
상한 90°, 엄지 및 나머지 관절, 공식 URDF, 실제 MuJoCo의 전체 관절 범위는 보존했다.
제조사 공식 보정값이나 기존 baseline으로 표시하지 않는다.

### 통제한 조건과 구현

- 전체 범위 `full`과 제한 범위 `restricted`를 각각 200 epoch 학습했다.
- 개인 Quest 학습 데이터 12,998프레임·seed 20261018·동일 FK 가중치를 사용했다.
- 두 모델의 초기 IK 모든 가중치와 BatchNorm buffer가 tensor 단위로 동일한지 검사했다.
- robot-only 100,000개 표본은 같은 latent uniform 값을 각 범위로 변환했다.
  범위가 바뀌면 도달 point cloud도 바뀌며, 이것은 범위 실험의 일부다.
- 원본 GeoRT trainer/loss는 수정하지 않고 프로젝트의 subclass에서 FK 입력 정규화 경계만 연결했다.

**기존 FK를 다른 정규화 범위에서 그대로 호출하면 안 된다.** 제한 모델의 정규화 값이 나타내는
실제 radian 값을 원래 전체 범위의 정규화 값으로 고정 affine 변환한 뒤 같은 FK에 넣었다.
이 adapter는 관절각의 표현만 바꾸며, 학습된 FK 함수·loss·게인은 바꾸지 않는다.
같은 실제 각도에 대한 정규화 일치 검사와 파생 제한 SAPIEN ↔ 공식 MuJoCo FK 검사를 통과했다.
후자의 최대 차이는 100개 자세에서 약 0.001583 mm다.

초기 가중치가 같더라도 출력 정규화 범위가 달라지므로 초기 **물리 관절각**이 같다는 뜻은 아니다.
동일 정규화 표현을 다른 물리 범위로 해석하는 것까지가 이번 처리 조건이다.

### 결과: 역방향 출력은 차단되지만 동작 대응은 해결되지 않음

같은 Quest 평가 2,000프레임에서 공통 검지·중지·약지 기준 펼친 손 869개·주먹 433개 후보를 사용했다.
후보는 기하 기준이며 정답 동작 라벨이 아니다. 이미 반복 확인한 평가 녹화이므로 blind test가 아니다.

세 번째 관절의 평균 목표 각도:

| 조건 | 검지 펼침 → 주먹 | 중지 펼침 → 주먹 | 약지 펼침 → 주먹 | 새끼 펼침 → 주먹 |
|---|---:|---:|---:|---:|
| 새 전체 범위 대조군 | −47.5° → +80.0° | −35.0° → +81.9° | −64.4° → +78.0° | −11.0° → +62.1° |
| 제한 범위 모델 | +66.8° → +41.2° | +79.9° → +80.7° | +4.7° → +86.6° | +10.1° → +78.7° |

제한 모델의 해당 8관절에서 음수 출력은 0개다. 이는 출력 범위로 보장한 결과이며,
자연스러운 동작을 학습했다는 증거로 취급하지 않는다. 제한 모델은 펼친 손 입력에도 검지·중지가
많이 굽는다. 인간 PIP와 로봇 굽힘 3관절 합계의 Spearman 상관은 다음과 같다.

| 조건 | 검지 | 중지 | 약지 |
|---|---:|---:|---:|
| 새 전체 범위 대조군 | +0.949 | +0.920 | +0.951 |
| 제한 범위 모델 | **−0.940** | **−0.853** | +0.955 |

즉, **0~90°로 제한하는 것만으로는 펼침·주먹 대응이 해결되지 않았다.**
제한 모델의 역방향 굽힘 관절값은 없어졌지만 일부 동작 반응은 오히려 반대다.

한편 이번 새 전체 범위 모델은 이전 개인 모델과 다르게 공통 세 손가락에서 양의 반응을 보인다.
이전 개인 모델과 이번 전체 범위 모델 사이에는 IK 초기화와 robot 표본 생성 경로 등의 차이가 있어
그 차이를 초기화 하나의 효과로 확정할 수는 없다. 다만 “넓은 범위면 반드시 실패한다”는 설명은
맞지 않으며, 원본 GeoRT의 학습 매핑·학습 경로에 대한 민감성을 계속 조사해야 한다.
새 전체 범위 모델도 펼친 손에서는 역방향 관절값을 내며, 주먹에서 새끼의 네 번째 관절 평균은
약 −66.3°다. 새 대조군까지 완전히 해결된 모델로 해석하지 않는다.

정적 모델 목표 비교:

![같은 입력에서 전체 범위와 제한 범위 비교](../results/geort_range_study_20261018/pose_comparison.png)

각 행은 같은 실제 평가 프레임이며 물리 모델과 카메라가 같다. 모델 목표를 정적으로 표시했다.
thumb pinch 15 mm 미만 후보에서 로봇 손끝 간 평균 거리(mm)는 아래와 같다.

| 조건 | 엄지–검지 | 엄지–중지 | 엄지–약지 | 엄지–새끼 |
|---|---:|---:|---:|---:|
| 새 전체 범위 대조군 | 31.8 | 32.6 | 31.3 | 26.7 |
| 제한 범위 모델 | 15.8 | 25.6 | 10.6 | 20.5 |

후보 수는 각 17·13·49·16프레임이다. 접촉/충돌을 켜거나 성공 여부를 검증한 수치는 아니다.
이전 개인 모델과의 pinch 성능 우열도 이 표로 주장하지 않는다.

같은 무접촉 MuJoCo·50 Hz·π rad/s 공통 제어기로 평가 녹화를 재생했다.
양 조건 모두 TRACKING 2,223 tick과 tracking-loss hold 검사를 통과했다.
제한 모델의 적용 명령–실제 상태 최대 관절 차이는 tick 평균 약 0.0169 rad다.
모델 목표·공통 공식 한계 처리·명령·실제 상태는 각각 보존했다.

### 실행 및 재현

제한 모델 실시간 서버를 새 포트 8034에서 실행했다. 기존 8026 서버와 모델은 변경하지 않았다.
Quest: `https://192.168.100.136:8034/`.
창 제목의 `RESTRICTED: NONTHUMB 3/4 = 0..90 DEG`로 실험 모델을 구분한다.
MuJoCo의 두 viewer를 같은 프로세스에서 동시에 여는 경로는 충돌이 있어 제거했고,
실시간 실행기는 한 조건씩 연다. 비교 그림과 offline 수치는 같은 입력을 사용한다.

```bash
# 기존 8034 서버가 실행 중이면 중복 실행하지 않는다.
MUJOCO_GL=glfw .venv-geort/bin/python scripts/run_geort_range_live.py \
  --study results/geort_range_study_20261018 --condition restricted --port 8034

# 전체 범위 새 대조군을 따로 확인할 때 사용한다.
MUJOCO_GL=glfw .venv-geort/bin/python scripts/run_geort_range_live.py \
  --study results/geort_range_study_20261018 --condition full --port 8035

# 재학습은 새 결과 폴더에서 실행한다.
.venv-geort/bin/python scripts/geort_range_study.py prepare --output results/geort_range_reproduction
.venv-geort/bin/python scripts/geort_range_study.py train --output results/geort_range_reproduction
.venv-geort/bin/python scripts/verify_geort_ranges.py --output results/geort_range_reproduction
.venv-geort/bin/python scripts/compare_geort_ranges.py --output results/geort_range_reproduction
MUJOCO_GL=egl .venv-geort/bin/python scripts/render_geort_ranges.py --output results/geort_range_reproduction
```

`.venv/bin/python -m pytest -q tests/test_geort_range_experiment.py`: 2개 통과.
새 코드 Ruff 통과. 원본 저장소 8개 clean, 기존 Phase 7 이전 파일 96개 변경 없음.
주요 근거는 `study.json`, `range_verification.json`, `initialization_verification.json`,
`comparison.json`, `eval_outputs.npz`, `*_eval_control.jsonl`, 각 조건의 `manifest.json`이다.

### 실제 Quest 확인 후: 제한 모델 사용 중단

사용자가 손을 펴도 굽혀 있는 현상을 확인했다. 최근 펼친 손 후보 100프레임과 대응하는
105개 TRACKING tick을 대조했다. 인간 검지·중지 PIP 평균은 4.18°·1.89°였지만, 모델의
로봇 3번 관절 목표 평균은 73.17°·83.07°였다. 적용 명령–실제 최대 관절 차이는 평균
0.0115 rad로, 시뮬레이터보다 모델 목표의 문제임을 다시 확인했다.

제한 모델 서버 PID 376467 / 포트 8034를 종료했다. 기존 8026 서버·모델·기록은 보존했다.
제한 모델 manifest에는 학습 완료 상태와 별도로 `behavioral_validation: failed_open_hand_mapping`을
기록했다. 이 모델을 개선된 기본 모델로 사용하지 않는다. 이전 실행 명령은 실패 현상 재현을
위한 진단용으로만 남긴다. 근거: `results/geort_range_study_20261018/live_open_failure.json`.

## 후속: 원본 매핑·학습 모드·손끝 해의 중복 조사

추가 학습이나 live 보정 없이 기존 개인 모델, 새 full 대조군, restricted 모델을 검사했다.
결과: `results/geort-mapping-investigation-gixfo42w/investigation.json`.
모든 모델의 체크포인트 hash는 검사 전후 동일하다.

### 1. 학습/추론 모드 차이만으로 실패를 설명하기 어려움

원본 sampler 형태의 2,048개 입력에서 원본 eval 모델과 복사본 train-mode 모델을 비교했다.
손끝 위치 차이 평균은 개인 원본 2.49 mm, full 1.72 mm, restricted 1.50 mm였다.
최대 관절 차이의 표본 평균은 각각 5.84°·3.64°·2.90°로, 모드 차이가 전혀 없는 것은 아니다.

실제 펼침·주먹 후보를 원본 sampler 문맥에 넣어 중지 3번 관절을 비교해도 잘못된 대응이 남았다.

| 모델 | eval 펼침/주먹 | train-mode 복사본 펼침/주먹 |
|---|---:|---:|
| 개인 원본 | +58.4° / −70.5° | +58.5° / −65.7° |
| 새 full | −34.9° / +81.8° | −36.3° / +79.7° |
| restricted | +79.7° / +80.4° | +78.8° / +77.8° |

train-mode를 배포에 사용하거나 BatchNorm 통계를 재보정하지 않았다. 이 검사는 가중치가 같은
독립 복사본의 진단이며, 실제 학습 batch 전체 loss나 추론 개선법으로 제시하지 않는다.

### 2. FK의 위치뿐 아니라 미분 방향도 대체로 일치

실제 출력 관절에서 신경망 FK Jacobian과 MuJoCo 정확 FK Jacobian을 비교했다.
유효한 own-finger 관절 열의 방향 cosine 평균은 개인 원본 0.9936, full 0.9934,
restricted 0.9867이었다. 상대 벡터 오차 중앙값은 약 11~13%로 근사 오차가 남지만,
현재 큰 역방향 자세를 FK 부호 오류 하나로 설명할 증거는 약하다.

평가 입력 256개에 원본과 같은 크기 범위의 무작위 국소 위치 변화(1~11 mm)를 주어,
인간 손끝 변화와 실제 MuJoCo 손끝 변화 방향을 대조했다.
평균 cosine은 개인 원본 **0.912**, full **0.936**, restricted **0.936**이었다.
즉, **작은 손끝 이동 방향은 잘 보존하면서도 전체 손의 관절 자세는 잘못될 수 있다.**
이는 원본 direction objective가 원하는 관절 자세와 같은 기준이 아니라는 실측 근거다.
기하 probe는 원본 녹화나 학습 데이터에 추가하지 않았다.

### 3. 잘못된 해는 학습 초기에 이미 나타남

저장된 epoch 0·1·5·10·20·50·100·150·199를 읽어 같은 입력을 추론했다.
개인 원본의 중지 목표는 epoch 1부터 펼침 약 +70.9° / 주먹 약 −64.0°였고,
epoch 199에도 +58.3° / −71.5°로 남았다.
restricted의 검지 굽힘 반응은 epoch 5부터 큰 음의 상관을 보이며 끝까지 유지됐다.
새 full 대조군 중지는 초기에는 반대였지만 epoch 20~50 구간에 양의 반응으로 바뀌었다.

이는 마지막 export나 MuJoCo 연결에서 새로 생긴 고장이 아니라 학습 중 선택된 매핑이다.
긴 학습이 반드시 실패를 해결한다거나, 초기화만이 유일한 원인이라고 단정하지 않는다.
이 진단으로 checkpoint를 다시 선택하거나 평가 입력에 맞춰 모델을 조정하지 않았다.

### 4. 넓은 관절 범위와 관절 조합의 비유일성

로봇만 사용하는 정적 기구학 진단에서 다음 두 중지 관절 조합을 찾았다.
다른 관절은 동일하고, 표는 중지 2·3·4번 관절이다.

| 자세 | 2번 | 3번 | 4번 |
|---|---:|---:|---:|
| 양의 굽힘 예 | +28.65° | +40.11° | +22.92° |
| 대체 관절 조합 | +80.04° | **−53.68°** | +50.29° |

MuJoCo 정확 FK의 손끝 위치 차이는 약 **2.3e-9 mm**로 수치 오차 수준이다.
손끝이 같아도 중간 관절은 전혀 다른 모양을 만들 수 있고, 넓은 역방향 범위가 이 선택지를 허용한다.
원본의 모든 loss는 IK 출력 관절 자체의 인간 자세 대응이 아니라 FK로 얻은 손끝에 작용한다.
다만 단일 자세의 손끝이 같다는 사실이 전체 연속 매핑의 direction/curvature loss까지
자동으로 같다는 뜻은 아니다.

대체 자세를 찾은 least-squares는 **도달성 진단용**으로만 사용했고 retargeter나 baseline에
넣지 않았다. 사람 관절 데이터를 생성하지도 않았다.
근거는 같은 폴더의 `robot_ik_ambiguity.json`, `robot_ik_ambiguity.npz`다.

### 5. 실제 기록 프레임과 원본 학습 sampler의 차이

원본 `MultiPointDataset.from_points`는 다섯 손가락 point cloud를 각각 voxel downsample 후
독립 재표본화한다. 12,998개의 실제 동시 손 자세가 학습 시 그대로 유지되는 방식이 아니다.
인수 `n=20000`과 별개로 실제 기본 resample 출력은 50,000개다.

엄지–검지 15 mm 미만 기하 후보 비율은 원본 실제 프레임에서 690/12,998 = 약 5.31%,
재표본화된 조합에서는 737/50,000 = 약 1.47%였다. 엄지–새끼는 약 1.86%→0.26%였다.
재표본화된 조합은 실제 기록된 동시 pose가 아니므로 이를 실제 pinch label로 해석하지 않는다.
이 관찰만으로 현재 실패의 주원인을 sampler 하나로 확정할 수는 없지만,
기록 프레임 수와 원본 학습에서 사용하는 pose 분포가 다르다는 점은 명확하다.

### 사용자 가설: 사람처럼 쓰는 작업 범위

사람의 자연스러운 동작에 대응하는 **리타게팅 작업 범위**를 로봇의 기계적 최대 범위와
구분하는 것은 근거가 있는 방향이다. 실제로 넓은 범위 안에 같은 손끝을 만드는 역방향 해가 존재한다.
그러나 앞선 0~90° 실험은 비엄지 8개 하한만 바꾼 것으로, 엄지·뿌리 관절·손가락 관절들의
조합까지 사람처럼 정의한 실험은 아니다.

사람 관절 각도 범위를 로봇의 encoder 각도에 그대로 복사하는 것도 검증이 필요하다.
관절 축·기준 자세·링크 구조와 엄지 관절 의미가 대응하는지 먼저 확인해야 한다.
수집된 동작의 관측 범위 역시 사람의 해부학적 최대 ROM을 측정한 것으로 표시하면 안 된다.
관절 간 새로운 coupling이나 자세 loss를 넣는다면 단순 로봇 설정을 넘어 원본 알고리즘 조건이
달라지므로 기존 baseline과 분리해야 한다. 이번 조사에서 그런 변경은 하지 않았다.

이번 결과는 “범위만 바꾸면 해결”과 “데이터만 더 모으면 해결” 어느 쪽도 보장하지 않는다.
문제는 원본 손끝 중심 목적함수가 허용하는 여러 관절 해 중 현재 모델이 부적절한 것을 선택하고,
일부에서는 전역적인 펼침/주먹 의미도 보존하지 못한다는 것이다.
사람형 작업 범위 프로파일은 이 선택지를 줄이는 다음 설정 실험이 될 수 있으나,
손끝 매핑 자체의 적절성은 반드시 별도 확인해야 한다.

재현:

```bash
.venv-geort/bin/python scripts/investigate_geort_mapping.py
```

새 결과 폴더를 만들며 optimizer·훈련·기존 모델 쓰기를 하지 않는다.
원본 checkpoint hash 보존과 새 코드 Ruff 검사를 통과했다.

## 후속: 직접 수집한 Quest 데이터의 관절 최대각

사용자의 `quest_train_session_002.jsonl`만 사용해 유효 오른손 **12,998프레임**에서 계산했다.
평가 녹화는 범위 결정에 사용하지 않았다. 입력 hash는 기존 train manifest와 대조했다.
원본 WebXR 25관절에 포함된 각 손가락 metacarpal 위치를 사용했다.
MCP는 중수골 방향에 대한 손바닥 기준 축으로 투영한 signed flexion 추정값이고,
PIP/DIP 및 엄지 MCP/IP는 인접 뼈 벡터 사이의 unsigned 굽힘 각도다.
임상 ROM이나 SDK가 제공한 직접 관절각·Tesollo encoder 각도로 표시하지 않는다.

| 손가락 | MCP 최대 | PIP 최대 | DIP 최대 |
|---|---:|---:|---:|
| 검지 | 85.85° | 108.21° | 71.29° |
| 중지 | 93.26° | 105.59° | 68.46° |
| 약지 | 92.92° | 107.89° | 74.63° |
| 새끼 | 96.91° | 105.63° | 76.42° |

엄지의 관측 최대 굽힘은 MCP **63.86°**, IP **52.87°**다.
엄지 CMC의 두 회전축을 이 숫자로 대체하지 않는다. 기존 20개 Quest ergonomics proxy도
별도로 전부 계산했지만, 엄지 opposition/elevation 등은 encoder 관절각으로 취급하지 않는다.
기존 proxy MCP는 palm 방향 기준이며 위 MCP는 metacarpal 기준이어서 숫자가 다를 수 있다.

각 각도의 원시 min/max·0.5/99.5 percentile·최대값 시점의 sequence/수신 시각·최대 근처 프레임 수를
함께 저장했다. 사용자 요청대로 원시 최대값을 percentile로 몰래 대체하지 않았다.
일부 최대값이 여러 프레임에서 반복되는 현상도 원본 추정 골격의 특성으로 그대로 기록한다.
관측 min은 해부학적 최소값·로봇의 중립값으로 자동 사용하지 않는다.

### 로봇 상한 후보

검지·중지·약지의 대응 굽힘 3단계에 대해 `min(관측 최대, 공식 DG-5F 상한)`을 계산했다.
이는 각도 기준·축 대응을 추가 검증하기 위한 **후보**이며 실제 URDF나 모델에 적용하지 않았다.

| 손가락 | 2번 상한 후보 | 3번 상한 후보 | 4번 상한 후보 |
|---|---:|---:|---:|
| 검지 | 85.85° | 90° | 71.29° |
| 중지 | 93.26° | 90° | 68.46° |
| 약지 | 92.92° | 90° | 74.63° |

중요하게도 PIP 최대 관측값은 105~108°로 로봇의 양의 상한 90°보다 크다.
따라서 최대값만 참조하면 PIP 상한은 줄어들지 않는다.
그리고 **상한을 줄여도 기존 하한 −90°는 남으므로 뒤로 꺾이는 문제를 막지 못한다.**
사용 범위에는 상한뿐 아니라 굽힘/신전 부호, 하한, 중립 자세가 필요하다.
PIP/DIP의 이번 unsigned 각도만으로 음의 방향 하한까지 측정했다고 주장할 수 없다.

엄지·새끼와 첫 관절은 관절 역할/축에 대한 일대일 대응이 미검증이라 자동 매핑하지 않았다.
특히 DG-5F 새끼의 1·2번 축은 검지·중지·약지와 달라 숫자 순서만 맞춰 넣지 않는다.
로봇의 최대 가동 범위를 사람의 관측 최대보다 넓히거나 출력 gain/offset을 추가하지 않았다.

### 산출물 및 재현

폴더: `results/quest_observed_ranges_session002_verified/`

- `observed_ranges.json`: 14개 native 기반 굽힘 추정 및 20개 기존 proxy의 통계·정의·출처.
- `observed_angles.npz`: 유효 프레임별 각도·sequence·수신 시각.
- `candidate_robot_upper_limits.json`: 공식 범위와 교집합을 취한 9개 상한 후보.
  하한은 공식값을 유지하며 `candidate_not_applied`로 표시했다.

```bash
.venv/bin/python scripts/measure_quest_joint_ranges.py \
  --input recordings/quest_train_session_002.jsonl \
  --manifest data/geort/quest_train_session_002/manifest.json \
  --output results/quest_observed_ranges_reproduction
.venv/bin/python -m pytest -q tests/test_quest_observed_ranges.py
```

알려진 각도의 MCP 측정·강체 회전 불변성·unsigned 굽힘의 부호 한계·퇴화 벡터 거부 검사를 통과했다.
원본 녹화·공식 URDF·모델·원본 Git 코드를 변경하지 않았고 재학습하지 않았다.

직전 Allegro 참조 프로파일은 `configs/geort/allegro_reference_v1.json`과
`results/geort_allegro_reference_v1/`에 별도로 준비돼 있다. 해당 프로파일도 학습은 시작하지 않았고,
이번 관측 최대값 후보와 섞거나 기존 실시간 모델에 적용하지 않았다.

## Quest 관측각과 DG-5F 관절 대응 확인 (2026-10-18)

공식 오른손 URDF, 생성된 MuJoCo 모델, 고정된 제조사 MANUS 매핑 함수를 읽기 전용으로
대조했다. **20개 관절에 사람의 각도를 같은 순서로 복사하는 대응은 성립하지 않는다.**
이 검사는 로봇 기구학과 소스의 대응 검증이며, 사람이 취한 자세와 로봇 encoder의
동시 측정에 의한 보정이나 실제 로봇 검증은 아니다.

| 대상 | 확인된 대응 | 적용 판단 |
|---|---|---|
| 검지·중지·약지 3번 | PIP에 해당하는 굽힘, 로컬 Y축 | 기하학적 굽힘 크기 참조 가능 |
| 검지·중지·약지 4번 | DIP에 해당하는 굽힘, 로컬 Y축 | 기하학적 굽힘 크기 참조 가능 |
| 검지·중지·약지 2번 | MCP 굽힘 역할, 로컬 Y축 | 사람 중수골 기준과 로봇 중립 기준 정합 미검증 |
| 검지·중지·약지 1번 | 벌림 축, 로컬 X축 | 굽힘 최대값을 넣지 않음 |
| 새끼 1·2번 | 로컬 Z·X축, 제조사 매핑에서 spread 기반 출력 | 일반 손가락의 1·2번 역할로 복사하지 않음 |
| 새끼 3·4번 | 제조사 매핑에서 각각 사람 MCP·PIP 입력 | 사람 PIP·DIP 순서로 복사하지 않음 |
| 엄지 | X·Z·X·X축, 제조사 매핑에 오프셋과 결합 존재 | Quest 추정각과 직접 일대일 보정 미확립 |

### MuJoCo 수치 검사

0 자세 및 공식 범위 내 고정 seed 무작위 128개 자세에서 다섯 손가락의 3·4번 관절을
검사했다. 인접 뼈 벡터와 실제 회전축으로 구한 signed angle은 관절값과 일치했다.
검지·중지·약지 2번도 부모 링크의 로컬 Z 기준 회전각과 관절값이 일치했다.
총 129개 자세의 최대 signed 오차는 **5.69×10⁻¹⁴° 미만**, unsigned 굽힘과
관절값 절댓값의 최대 차이는 **4.91×10⁻¹²° 미만**이었다.

검지·중지·약지 3번을 0°에서 +10°로 돌리면 손끝은 palm +X 방향으로 각각
11.166 mm 이동했다. 양의 방향이 손바닥 쪽 굽힘임을 확인했다.
그러나 이번 Quest PIP/DIP 측정은 unsigned이므로 +30°와 −30°를 구분하지 못한다.
따라서 해당 데이터로 음의 하한까지 측정했다고 할 수 없다.

MCP의 로봇 0°는 부모 링크의 기하학적 기준이다. Quest 측정은 실제 추정 중수골을 기준으로
투영한 각도다. 축의 역할이 같아도 두 기준이 일치하는지는 별도 확인이 필요하다.
이 검사 결과를 사람 MCP 각도와 encoder 사이의 오프셋 보정값으로 사용하지 않는다.

### 제조사 매핑이 보여주는 차이

출처: `external/dg5f_ros2/dg5f_driver/script/manus_retarget/manus_retarget.py`,
고정 commit `0cb45ae9474caa92410dfa820346da8ffbae8405`.
기존 `OfficialManusMapping`을 통해 원본 함수 AST를 그대로 실행했다.
오른손 출력에는 다음 변환이 존재한다(각도는 이해를 위해 degree로 표기).

- 검지 PIP 출력: `max(0, 1.3 × (MANUS IndexPIPStretch − 40°))`.
- 중지 PIP 출력: `max(0, 1.3 × (MANUS MiddlePIPStretch − 30°))`.
- 새끼 3번 출력은 `PinkyMCPStretch`, 4번 출력은 `PinkyPIPStretch`다.
  `PinkyDIPStretch` 입력을 바꿔도 이 함수의 출력은 변하지 않는다.
- 엄지 4번은 두 입력의 평균에 gain을 적용한다. 단일 관절각 복사가 아니다.
- 여러 굽힘 출력에는 음수 제거가 포함된다. 이는 제조사 MANUS 매핑의 동작이며
  GeoRT 전체에 공통으로 적용된 제약은 아니다.

실행 예에서 MANUS 검지 PIP 60° 입력은 로봇 3번 26°, 중지 PIP 60°는 39°가 된다.
**MANUS ergonomics와 Quest 위치 기반 추정각은 서로 다른 입력이다.** 이 오프셋/gain을
Quest 각도에 복사하거나 반대로 제거해 보정하는 작업은 하지 않았다.
또한 이 매핑 차이가 GeoRT의 입력 오류를 증명하는 것은 아니다. GeoRT는 손끝 위치를 입력받는다.

### 기존 상한 후보에 대한 판정

`quest_observed_ranges_session002_verified/candidate_robot_upper_limits.json`은 계속
미적용 후보로 보존한다. PIP/DIP 6개는 굽힘 **크기** 참조에 기구학적 근거가 있다.
MCP 3개는 사람-로봇 중립 기준 정합 전까지 수치 적용을 보류해야 한다.
새끼·엄지의 대응을 번호로 확장해서는 안 된다.
상한만 줄여도 음의 관절값은 허용되며, 이전 0~90° 제한 실험에서도 손을 폈을 때 굽혀지는
실패가 있었다. 범위 제한만으로 GeoRT의 잘못된 자세 대응이 해결된다고 결론낼 수 없다.

재현 명령(출력 파일은 새 경로 지정):

```bash
.venv/bin/python scripts/verify_quest_tesollo_correspondence.py \
  --output results/quest_tesollo_correspondence_reproduction/audit.json
.venv/bin/python -m pytest -q tests/test_quest_observed_ranges.py tests/test_geort_reference_ranges.py
.venv/bin/python scripts/verify_phase7_sources.py
```

결과: `results/quest_tesollo_correspondence/audit.json`. FK 수치 검사 및 제조사 함수의
출력 예제 assertion 통과, 관련 테스트 5개 통과, 고정 upstream 8개 저장소 clean 확인.
원본 Git 코드·URDF·기존 모델·관절 범위를 변경하지 않았고 재학습하지 않았다.

## Quest 관측 상한 적용 학습 실험 (2026-10-18)

이후 사용자가 범위 적용과 학습을 요청하여 별도 실험
`results/geort_quest_observed_six_20261018/`를 생성했다.
공식 URDF 원본과 기존 모델은 유지하고, 학습용 URDF 사본과 export 설정에만 적용한다.

| 관절 | 적용 학습 범위 |
|---|---:|
| 검지 PIP / DIP | 0~90° / 0~71.2902° |
| 중지 PIP / DIP | 0~90° / 0~68.4642° |
| 약지 PIP / DIP | 0~90° / 0~74.6311° |

상한은 검증된 대응 6개에 대해 `min(녹화의 원시 최대각, 공식 상한)`이다.
**하한 0°는 역굽힘을 제외하기 위한 명시적인 실험 제약이며, 녹화에서 측정한 하한이 아니다.**
MCP·벌림·엄지·새끼의 14개 관절은 공식 범위를 유지한다.
특히 새끼와 엄지까지 역굽힘이 방지된 모델이라고 표시하지 않는다.

학습 입력은 `quest_train_session_002`의 오른손 유효 12,998프레임이며
공개 데이터와 평가 녹화는 학습에 넣지 않는다. 원본 GeoRT loss, gain, offset,
학습률, 200 epoch 및 데이터 재표본화 방식을 유지한다.
full/restricted 두 조건은 같은 seed 20261018, 초기 IK 텐서, 100,000개 로봇 샘플의
기저 uniform 값과 같은 full-range neural FK를 사용한다.
제한 범위의 normalized joint를 원본 FK 정규화로 변환하는 기존 affine 어댑터를 재사용한다.
따라서 제한 범위 export에 기존 FK 가중치를 무보정으로 넣는 오류를 피한다.
범위 변경에 따른 로봇 workspace와 정규화 차이는 실험 조건의 일부다.
이 결과는 원본 공식 baseline이나 제조사 보정 결과로 취급하지 않는다.

학습 전 검사에서 URDF 사본은 지정한 6개 관절 limit 속성만 변경됐고,
100개 자세의 SAPIEN/MuJoCo FK 최대 차이는 0.00158 mm였다.
범위·관측각 관련 기존 테스트 7개와 upstream 무변경 검사를 통과했다.

재현(prepare는 새 폴더를 지정하고, 학습은 완료 모델을 덮어쓰지 않음):

```bash
.venv-geort/bin/python scripts/geort_quest_observed_study.py prepare \
  --output results/geort_quest_observed_six_reproduction
.venv-geort/bin/python scripts/geort_quest_observed_study.py train \
  --output results/geort_quest_observed_six_reproduction
.venv-geort/bin/python scripts/geort_quest_observed_study.py check \
  --output results/geort_quest_observed_six_reproduction
MUJOCO_GL=egl .venv-geort/bin/python scripts/render_geort_ranges.py \
  --output results/geort_quest_observed_six_reproduction
```

`profile.json`은 실제 범위와 근거, `study.json`은 학습 입력/FK hash,
`preparation_verification.json`은 기구학 검사,
`initialization_verification.json`은 두 모델 초기화 일치 결과를 담는다.
각 조건의 `manifest.json`, `model.pth`, `export_config.json`, epoch별 checkpoint와
console 로그를 보존한다. `check`는 이미 진단에 사용한 평가 녹화의 2,000프레임으로
유한 출력·학습 범위 준수 및 open/fist 후보의 원시 목표를 확인한다.
이는 blind test나 실제 접촉 성공 평가가 아니다.

### 완료 결과

두 조건 모두 **200 epoch 완료**, 제한 모델 학습 시간 약 **293초**.
초기 IK state_dict의 모든 텐서와 full-range FK hash가 일치했다.
제한 모델 체크포인트 SHA256:
`fc3cf2238cb64ab15fd65a2014536ce6414854bab2d775f28bbc289562ced024`.

평가 2,000프레임에서 모든 출력이 유한하고 각 모델의 선언 범위를 준수했다.
그러나 **자세 대응은 실패**했다. 기존 기하 조건으로 고른 open 후보 869프레임,
fist 후보 433프레임의 제한 모델 PIP 평균은 다음과 같다.

| 손가락 | Open 입력 PIP 출력 | Fist 입력 PIP 출력 |
|---|---:|---:|
| 검지 | 70.36° | 48.90° |
| 중지 | 86.56° | 81.19° |
| 약지 | 7.29° | 84.71° |

사람 PIP와 로봇 MCP+PIP+DIP 합의 Spearman 상관은 검지 −0.933, 중지 −0.848,
약지 +0.919였다. full 조건은 각각 +0.949, +0.920, +0.951였지만,
full도 손을 폈을 때 음의 PIP/DIP가 나타나므로 올바른 자세의 기준 모델은 아니다.
상관은 자세 정답 정확도와 다르다.

따라서 이번 실험은 지정한 관절의 역굽힘을 구조적으로 제외했지만,
손을 펴면 로봇이 굽혀지는 문제는 해결하지 못했다.
추가 데이터만으로 해결된다거나 MuJoCo가 범위를 잘못 적용했다고 볼 근거는 없다.
공식 GeoRT의 손끝 기반 자세 대응이 이 범위에서 잘못 학습된 결과가 남아 있다.
이번 단일 seed 결과로 모든 범위 설정이나 모든 학습 초기화가 실패한다고 일반화하지 않는다.

결과 파일:

- `restricted/model.pth` + `restricted/export_config.json`: 제한 범위 모델과 필수 범위 설정.
- `full/model.pth` + `full/export_config.json`: 동시 학습한 기존 범위 대조 모델.
- `comparison.json`, `eval_outputs.npz`: 원시 모델 목표와 open/fist 진단 결과.
- `pose_comparison.png`: 동일 입력 프레임의 범위 제한 전후 MuJoCo 정적 렌더.
- `source_integrity.json`: 학습 후 고정 upstream 8개 저장소 clean 확인.

실시간 서버의 기존 모델은 교체하지 않았다. 이 제한 모델은 동작 개선이 확인되지 않은
진단용 실험 모델이며, 기존 0~90° 실험용 hardcoded live adapter로 불러오면 안 된다.
반드시 모델과 짝이 맞는 `export_config.json`의 범위로 역정규화해야 한다.
