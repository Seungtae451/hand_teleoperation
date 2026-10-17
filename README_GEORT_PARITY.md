# 공개 Quest 좌표 parity 실험

양손 검증 화면에서 사용자가 관찰한 X 굽힘 방향 불일치를 반영하여, 공개 OOJU 입력에만
별도 canonical parity adapter를 적용한다. 기존 공개 데이터 모델은 보존한다.
수집/exporter 코드가 공개 배포본에 없어 **제공자가 확인한 좌표 변환으로 인증된 것은 아니다**.

## 적용 범위

- `benchmark/datasets/quest_parity.py`: 기존 GeoRT canonical 변환 후 `(X,Y,Z) → (-X,Y,Z)`.
- 양손에 같은 규칙을 적용할 수 있지만 학습은 기존과 같이 오른손만 사용한다.
- 손 라벨, 단위, 관절 인덱스, 뼈 길이, 관절 간 거리, 스케일은 바꾸지 않는다.
- world pose나 wrist quaternion을 변환한 것처럼 기록하지 않는다.
- 실시간 WebXR 입력과 공식 `human_alex.npy`는 반전하지 않는다.
- 학습량 1,000 / 3,498 / 10,000, 기존 row ID·split·seed·200 epoch·원본 loss·공통 제어기를 유지한다.
- 공식 데이터 모델은 기존 체크포인트를 그대로 재사용한다. 총 비교 모델은 네 개다.
- 본인 Quest 기록은 학습에 사용하지 않는다. 기존 실시간 snapshot은 진단에만 사용한다.

이전 배포본과 재배포본의 작은 pose shard 1,923프레임을 대조했다.
양손 모두 정확히 `(x,y,z) → (z,x,y)`이고 determinant는 +1이다.
현재 pinned 배포본의 같은 관절 데이터도 재배포본과 일치한다.
이 사실은 chirality가 유지되었음을 보여주지만, 그 이전 좌표의 정의나 제공자 버그를 단독으로
입증하지 않는다. 사용자 관찰과 기존 기하 진단을 근거로 명시적인 empirical adapter 실험으로 둔다.

출처: [OOJU dataset](https://huggingface.co/datasets/OOJU/wild-mani-kitchen),
[좌표 재배포 이력](https://huggingface.co/datasets/OOJU/wild-mani-kitchen/commit/6c562cea69817ab54e4b80fd2353459d343eba87).
원본 추적은 제공자 표기상 Quest 3 / Unity이며 SDK 버전은 미제공, 라이선스는 Apache-2.0이다.
참가자 식별 정보가 없어 참가자 단위 분리 여부는 여전히 검증할 수 없다.

## 재현

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
.venv/bin/python -m pytest -q tests/test_quest_parity.py tests/test_hand_validation.py
.venv-data-audit/bin/python scripts/check_quest_export_history.py

# 별도 경로에 생성한다. 기존 경로에 다시 prepare하면 덮어쓰지 않고 실패한다.
.venv/bin/python scripts/geort_parity_study.py prepare --study results/geort_data_size_parity_reproduction
.venv/bin/python scripts/geort_parity_study.py train --study results/geort_data_size_parity_reproduction
.venv/bin/python scripts/geort_parity_study.py verify --study results/geort_data_size_parity_reproduction
```

실제 생성 경로는 `results/geort_data_size_parity_20261018/`이다.
`study.json`은 adapter 근거와 한계, `dataset_verification.json`은 입력·분할 보존 검사,
각 `models/*/run_manifest.json`은 입력 해시와 200 epoch 완료·체크포인트 해시를 기록한다.
`models.json`의 공식 모델 경로는 보존된 이전 실험 체크포인트를 가리킨다.

학습 후 재현할 진단과 통합 검사:

```bash
.venv-geort/bin/python scripts/compare_geort_parity.py --study results/geort_data_size_parity_20261018
.venv/bin/python scripts/validate_live_retargeting.py --port 8030 --geort-study results/geort_data_size_parity_20261018/models.json
```

첫 검사는 변환된 동일 validation 512프레임과 변환하지 않은 동일 과거 WebXR 512프레임을
이전·새 모델에 넣는다. test split은 점수 계산에 사용하지 않는다.
손목 기준 인간 손끝과 로봇 palm 기준 손끝의 거리는 독립 정답 오차가 아니므로,
이 수치만으로 알고리즘 우열이나 실제 손 모양의 품질을 확정하지 않는다.
통합 검사는 기록된 native packet을 재생해 MuJoCo의 20관절 제어와 추적 상실 시 hold를 검사한다.
실제 새 Quest 동작 시험과 구분한다.

## 새 모델로 실시간 확인

기존 비교 서버가 실행 중이면 그 서버의 터미널에서 Ctrl+C로 종료한 뒤 실행한다.

```bash
.venv/bin/python scripts/run_geort_models_live.py \
  --geort-study results/geort_data_size_parity_20261018/models.json \
  --port 8026
```

Quest 접속 주소는 실행 콘솔의 HTTPS 주소를 사용한다.
`--geort-study`를 생략하면 기존 launcher는 이전 모델을 선택하므로 반드시 지정한다.
X 방향 문제를 수정한 입력 실험이며, 모든 굽힘·pinch·제어 지연이 해결되었다는 의미는 아니다.

## 양손 입력 그림만 다시 비교

원본 검증 samples는 보존하고, 양손에 adapter를 적용한 별도 복사본도 만들었다.
각 후보 이름에 `[parity adapter]`가 표시된다. 기존 진단용 반사 checkbox는 꺼 두어야 한다.
같은 기하 canonical 축 정의를 사용하므로 양손의 해부학적 굽힘 X 부호가 같을 필요는 없다.

```bash
# 최초 생성 시에만 실행한다. 이미 생성된 파일은 덮어쓰지 않는다.
.venv/bin/python scripts/prepare_parity_validation.py

# 기존 검증 서버와 다른 포트로 실행할 수 있다.
.venv/bin/python scripts/run_hand_validation.py --port 8031 --monitor-port 8032 \
  --samples results/geort_data_size_parity_20261018/hand_validation_samples.json
```

PC는 `http://127.0.0.1:8032/inspect`, Quest는 콘솔의 HTTPS 주소로 연결한다.
라이브 입력은 그대로이며, 새 samples에 담긴 공개 손 그림에만 고정 adapter가 적용되어 있다.

완료 결과와 잔여 문제: [docs/GEORT_PARITY_RESULT.md](docs/GEORT_PARITY_RESULT.md).
세 모델 모두 200 epoch 완료, 네 모델의 recorded-packet MuJoCo 제어/추적 상실 hold 검사도 통과했다.
