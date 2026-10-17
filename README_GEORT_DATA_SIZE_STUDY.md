# GeoRT 공개 데이터 수 비교: 네 모델

공식 예제 데이터만 사용하는 모델과 공개 Quest 데이터 1,000·3,498·10,000프레임 모델을
독립적으로 학습한다. 이번 비교에는 직접 녹화한 Quest 데이터를 사용하지 않는다.
최종 모델 경로와 완료 여부는 `results/geort_data_size_20261018/models.json`에 기록된다.

2026-10-18 실행 완료: 네 모델 모두 200 epoch 학습, 체크포인트 재로딩과 각 8프레임의
20관절 추론 검사를 통과했다. 네 체크포인트의 hash는 서로 다르고, 공유 FK·로봇 점군은
동일하게 유지됐다. 검증 기록은 같은 실행 폴더의 `model_verification.json`,
`dataset_verification.json`, `source_integrity.json`이다. 성능 비교는 아직 실행하지 않았다.
각 모델 파일은 `results/geort_data_size_20261018/models/CONDITION/model.pth`,
동반 설정은 같은 폴더의 `config.json`이다.

| 조건 | 입력 프레임 | 내용 |
|---|---:|---|
| `official_3498` | 3,498 | 원본 `human_alex.npy`를 바이트 그대로 사용 |
| `quest_1000` | 1,000 | 공개 Quest 학습 집합의 부분집합 |
| `quest_3498` | 3,498 | 위 1,000프레임을 모두 포함 |
| `quest_10000` | 10,000 | 위 3,498프레임을 모두 포함 |

네 조건은 같은 DG-5F URDF·관절 순서·손끝·한계·neural FK·로봇 점군·seed를 사용한다.
원본 `GeoRTTrainer.train()`을 수정 없이 호출하며 각 IK 모델을 새로 초기화한다.
학습은 원본 기본값인 200 epoch, batch 2,048, AdamW lr 1e-4다.
손실 가중치는 chamfer 80, curvature 0.1, collision 0, pinch 1을 유지한다.
원본에서 collision loss는 비활성 placeholder이므로 충돌 회피를 검증했다고 해석하지 않는다.

## 데이터와 분리

공개 데이터는 `OOJU/wild-mani-kitchen`의 고정 revision
`b5c916d89c771f4a09d5f6d6c59e1dc4f912bb61`이다.
제공자가 Quest 3 손 추적으로 수집했다고 명시한 제3자 데이터이며 Meta 공식 배포물이 아니다.
제공자 라이선스는 Apache-2.0이다. SDK 버전·추적 신뢰도·참가자 정보는 제공되지 않는다.

원본 79,244행 중 완전히 동일한 오른손 월드 좌표 중복 28행을 제외했다.
작업 종류별로 seed `20261018`을 적용하여 에피소드 단위 70/15/15 분리를 수행했다.
작업별 반올림 때문에 전체 비율은 정확히 70/15/15가 아니다.

| 분리 | 에피소드 | 중복 제거 후 프레임 |
|---|---:|---:|
| 학습 | 72 | 55,544 |
| 검증 | 16 | 12,463 |
| 평가 | 14 | 11,209 |

학습 집합에서 에피소드별 프레임 순서를 섞고 에피소드를 번갈아 선택했다.
1k·3,498·10k 모두 같은 72개 학습 에피소드를 포함하며 부분집합은 중첩된다.
검증·평가 에피소드의 좌표는 학습에 전달하지 않는다.
참가자 정보가 없으므로 참가자 독립 평가를 주장할 수 없다.
공식 예제 데이터의 참가자와 공개 데이터 참가자의 중복 여부도 확인되지 않았다.

원본 26관절에서 실제 common21 관절만 선택한다. 데이터의 FLU는 오른손 좌표계로 취급하고,
골격 길이와 wrist 좌표 일치로 meter 해석을 확인했다. GeoRT 원본 canonical helper를 그대로
적용해 손목 원점·원본 손바닥 축으로 변환한다. 누락 관절 생성·크기 보정·데이터 증강은 하지 않는다.
SDK confidence가 없으므로 여기서 유효성은 기하 검사 통과를 뜻하며 추적 정확도를 보증하지 않는다.
프레임 시각은 원본 timestamp가 없어 프레임 인덱스/30초로 명시하며, 학습은 시각을 사용하지 않는다.

각 학습 입력은 `datasets/CONDITION/human.npy`와 `manifest.json`에 저장한다.
Quest의 원본 행·에피소드·프레임 인덱스는 `row_ids.npz`에 저장한다.
검증·평가 입력은 각각 `datasets/validation`, `datasets/test`에 별도 보존한다.

## 공통 FK와 학습 해석

FK는 기존 DG-5F의 로봇 관절 100,000개와 URDF 손끝 위치만으로 학습된 모델을 재사용한다.
과거 실행 폴더에서 복사하지만 **사람 데이터로 학습된 IK 체크포인트는 재사용하지 않는다**.
네 조건의 FK 파일과 로봇 점군 hash가 같은지 확인한다.

원본 GeoRT는 각 손가락 점군을 1 mm voxel로 downsample하고 손가락마다 50,000점을
재샘플링한다. 따라서 1k 모델과 10k 모델의 학습 데이터로더 길이는 같다.
이 실험은 학습량 증가보다 입력 손끝 분포의 범위·밀도 변화에 따른 결과를 비교한다.
추가 프레임 수가 서로 다른 손 자세 수와 같다는 의미도 아니다.

이번에는 조건당 seed 하나로 총 네 모델을 만든다. 반복 학습의 평균·분산은 아직 없다.
원본 콘솔의 epoch별 손실은 첫 minibatch의 출력이며 epoch 평균·검증 오차가 아니다.
성능 우열은 같은 별도 평가 입력으로 측정해야 한다. 이번 작업의 추론 검사는 모델 로딩과
20관절 유한 출력·관절 범위를 확인하는 smoke test이며 성능 평가가 아니다.
기존 직접 녹화 데이터로 만든 보정 프로파일은 이 학습에 적용하지 않는다.

## 재현

데이터 준비는 `.venv-data-audit`, 학습은 기존 `.venv-geort` 환경을 사용한다.
두 환경의 NumPy 버전 요구가 달라 환경을 합치지 않는다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation

# 필요할 때 별도 데이터 환경 생성
uv venv .venv-data-audit --python .venv/bin/python
uv pip install --python .venv-data-audit/bin/python -r requirements/public-quest-audit.txt

# 원본 공개 데이터와 results/public_quest_audit.json이 존재하는 상태에서 실행
# 아래 출력 경로는 새 폴더여야 한다.
.venv-data-audit/bin/python scripts/geort_data_size_study.py prepare \
  --study results/geort_data_size_reproduction
.venv/bin/python scripts/geort_data_size_study.py train \
  --study results/geort_data_size_reproduction
.venv/bin/python scripts/geort_data_size_study.py verify \
  --study results/geort_data_size_reproduction
```

GPU 0과 1에서 각각 한 작업씩 수행하고 조건 두 개씩 순서대로 학습한다.
다른 작업이 GPU를 사용하는 경우 먼저 자원 상황을 확인한다.
외부 Git 코드는 수정하지 않으며 기존 입력·학습 모델·평가 결과를 덮어쓰지 않는다.

## 생성 모델 사용

예를 들어 Quest 10k 모델은 다음처럼 기존 실시간 실행기에 명시한다.

```bash
.venv/bin/python scripts/run_live_retargeting.py --methods geort --port 8026 \
  --checkpoint results/geort_data_size_20261018/models/quest_10000/model.pth \
  --config results/geort_data_size_20261018/models/quest_10000/config.json
```

같은 포트에 서버가 이미 실행 중이면 중복 실행하지 않는다.
`quest_10000`을 `official_3498`, `quest_1000`, `quest_3498`로 바꾸면 해당 모델을 사용한다.
실행기는 선택한 모델만 사용하며 기존 서버의 모델을 자동으로 교체하지 않는다.
