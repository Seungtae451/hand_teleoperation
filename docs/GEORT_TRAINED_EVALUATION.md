# 학습한 GeoRT 평가 — 2026-10-18

학습 완료와 실제 checkpoint 추론을 확인했다. Neural FK는 새 관절 표본에서 millimeter
수준의 근사 오차를 보였다. 반면 이번 GeoRT retargeting 모델은 손끝 대응과 pinch에서
한계가 있으며, 같은 이전 녹화에 대한 AnyDex/Wuji 기본 설정보다 대응 오차가 컸다.
원본 코드·파라미터·학습 결과를 수정하거나 재학습하지 않고 측정한 결과다.

## 대상과 검증 범위

- 학습 실행: `results/geort_dg5f_workspace/training-2glhel2r`, status completed.
- seed: 20261018. Neural FK와 IK 모두 epoch 0–199의 로그 확인.
- IK checkpoint: `checkpoint/dg5f_right_geort_2026-10-18_00-40-37/last.pth`.
- 학습 녹화: `recordings/geort_train_session_001.jsonl`, 유효 오른손 3,991프레임.
- 다른 세션: `recordings/quest-20261017T135937-204414Z.jsonl`, 유효 오른손 3,236프레임.

다른 세션은 학습 manifest의 recording hash와 다르다. 참가자 ID가 없어 subject-held-out
검증으로 표시하지 않는다. 별도의 사전 지정 평가 세트도 없으므로 이번 결과는
학습 녹화 점검과 이전 세션에 대한 탐색적 비교다. 공개 데이터셋이나 synthetic 입력을
실제 Quest 평가 데이터로 바꾸어 사용하지 않았다.

## 학습 로그

| 항목 | 첫 epoch | 마지막 epoch |
|---|---:|---:|
| Neural FK MSE | 0.00809798 | 0.00000867678 |
| IK Direction | 0.0735 | -0.9127 |
| IK Chamfer | 0.0034 | 0.00081404 |
| IK Pinch | 0.1322 | 0.0108 |

Neural FK 값은 epoch 평균이다. IK 값은 각 epoch에서 출력한 batch 0의 값이며
전체 epoch 평균이나 validation loss가 아니다. Direction 항은 원본의 negative cosine
형태라 음수 값이 정상이다. Collision 항은 원본에서 비활성 placeholder이므로 0이라는
사실로 충돌 회피가 검증됐다고 판단하지 않는다.

[학습 곡선](../results/geort-evaluation-yw5i3hyk/training_curves.png)

## Neural FK: 새 관절 표본 검증

공식 DG-5F 관절 범위에서 고정 seed로 새 관절 벡터 1,024개를 생성했다.
기존 FK 학습 벡터 100,000개와 exact vector hash 중복이 0임을 확인했다.
원본 FKModel을 eval/inference 모드로 실행하고, MuJoCo 실제 기구학의 다섯 손끝 위치와 비교했다.

| 손끝 3D 거리 오차 | mm |
|---|---:|
| 평균 | 2.170 |
| 중앙값 | 1.939 |
| P95 | 4.612 |
| 최대 | 9.141 |

좌표 성분 RMSE는 1.435 mm다. 이는 같은 로봇 관절 분포의 neural FK 근사 성능이며,
사람 손 retargeting 정확도를 뜻하지 않는다. FK probe 입력과 실제/예측 위치는
`neural_fk_probe.npz`에 보존했다.

## 실제 녹화의 GeoRT 출력

추적 무효 frame을 제외한 **모든 유효 source frame**을 직접 추론했다.
학습 때와 같은 원본 canonical 변환, 실제 checkpoint와 export config를 사용했다.
20회 warm-up은 직접 추론 시간 통계에서 제외했다.

| 항목 | 학습 녹화 | 이전 녹화 |
|---|---:|---:|
| 유효 오른손 프레임 | 3,991 | 3,236 |
| 평균 정규화 손끝 대응 오차 | 0.6423 | 0.6529 |
| canonical 좌표에서 raw 손끝 대응 거리 평균 | 60.32 mm | 61.04 mm |
| 평균 wrapper 추론 시간 | 0.681 ms | 0.679 ms |
| 원본 목표각의 최대 관절 범위 초과 | 0 rad | 0 rad |

Raw 거리에는 사람/로봇 크기와 wrist/palm 원점 차이가 포함된다. 정규화 값은 기존 공통
지표의 정의를 사용한다. 모두 추정한 사람 손 pose에 대한 기하학적 대응값이며
독립적인 사람 손 또는 로봇 관절 정답에 대한 오차가 아니다.
모든 목표각은 finite 20차원으로 생성됐으며 실제 renderer/MuJoCo 재생이 성공했다.

### Pinch 관련 관찰

원본 학습의 거리 기준을 참고해 사람 thumb–index 거리가 15 mm 미만인 프레임을
후보로 선택했다. 정답 gesture label은 없으며 성공률로 사용하지 않는다.

| 항목 | 학습 녹화 | 이전 녹화 |
|---|---:|---:|
| 사람 thumb–index <15 mm 후보 | 117프레임 | 17프레임 |
| 해당 후보의 로봇 tip-frame 거리 평균 | 31.98 mm | 28.33 mm |
| 해당 후보의 로봇 tip-frame 거리 P95 | 36.90 mm | 37.19 mm |

학습 loss가 감소했지만 로봇 손끝을 충분히 가깝게 대응시키지 못하는 사례가 남았다.
접촉은 비활성화되어 있으므로 표면 접촉·물체 grasp 성공은 검증하지 않았다.
거리 측정 대상은 공식 fingertip link frame이며 mesh 표면 사이의 거리와 다르다.

[학습 녹화의 가장 가까운 사람 thumb–index 입력에 대한 로봇 목표 자세](../results/geort-evaluation-yw5i3hyk/training_session_closest_human_thumb_index.png)

## 네 방법의 동일 이전 세션 비교

기존 common runner와 모델을 그대로 사용했다. control은 50 Hz, physics timestep 0.002 s,
명령 속도 제한은 pi rad/s다. 각 원본의 기본 output filter도 유지했다.
control 시간 격자에서 소비된 서로 다른 유효 입력은 각 방법 **3,224개**이며,
네 방법의 `common_input_stream_sha256`이 일치했다. 위 직접 추론 표는 모든 유효
source frame 3,236개를 사용하므로 표본 수가 다르다.

| 방법 | 평균 정규화 tip 대응 오차 ↓ | 평균 wrapper 처리 ms |
|---|---:|---:|
| MANUS | 0.4461 | 0.140 |
| AnyDex | 0.2378 | 7.188 |
| Wuji | 0.2378 | 4.379 |
| 학습한 GeoRT | 0.6530 | 0.732 |

현재 세션/설정/모델에서는 GeoRT가 빠르게 목표값을 생성하지만 기하학적 대응 오차가
가장 컸다. 이것을 GeoRT 방식 일반의 우열로 확장하지 않는다. AnyDex와 Wuji는 현재
기본값에서 공유하는 목적함수가 있어 결과가 유사하다.
시간은 각 adapter의 원본 전처리·solve/inference·filter/진단을 포함한다. GPU/CPU 실행과
진단 비용이 다르며 순수 kernel 시간이나 통신/렌더링 포함 latency는 아니다.

[대응 오차 분포와 비교 그래프](../results/geort-evaluation-yw5i3hyk/correspondence.png)

## 해석과 다음 판단

학습·checkpoint 저장·추론 연결은 정상 동작했다. 현재 모델의 pinch/손모양 재현이
충분하다고 결론 내릴 근거는 없다. Neural FK 오차가 작은 것과 retargeting 대응 품질은
별개의 항목이다. 학습 녹화에서도 대응 오차가 있으므로 새 세션 일반화 문제만으로
설명할 수 없다. 데이터 범위, 원본의 unpaired 학습 목적과 손 크기/좌표 의미가 관여할 수
있지만 이번 평가에서 원인을 분리해 증명하지는 않았다.

원본 코드를 바꾸거나 epoch/loss weight를 조절해 점수를 맞추지 않았다.
이 checkpoint와 결과를 현재 baseline으로 보존하고, 다음 정식 비교에서는 별도 평가용
녹화·gesture 기준·허용 오차를 사전에 정해 검증하는 것이 적절하다.
재학습이나 retargeting 알고리즘 개선은 이번 요청에서 실행하지 않았다.

## 산출물 및 재현

전체 산출물 폴더: `results/geort-evaluation-yw5i3hyk`.

- `evaluation.json`: provenance, checkpoint hash, 모든 통계와 비교.
- `training_console.txt`: 제공된 학습 로그 사본.
- `*_direct.npz`, `neural_fk_probe.npz`: 목표각·손끝·probe 입력과 결과.
- `prior_session_dynamic/`, `prior_session_baselines/`: 같은 입력의 네 방법 로그.
- `training_preview/geort.mp4`: 학습 녹화 앞 300 source frame의 실제 MuJoCo 동역학 영상.
- `*_closest_human_thumb_index.png` 등: 명시한 frame의 target FK 자세 렌더링.

[MuJoCo 재생 영상](../results/geort-evaluation-yw5i3hyk/training_preview/geort.mp4)

기존 소스를 수정하지 않고 새 평가 실행기만 추가했다. 다음 명령으로 새 결과 폴더에
재현할 수 있으며 재학습을 시작하지 않는다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
MUJOCO_GL=egl .venv-geort/bin/python scripts/evaluate_trained_geort.py \
  --run results/geort_dg5f_workspace/training-2glhel2r \
  --log results/geort-evaluation-yw5i3hyk/training_console.txt \
  --train-recording recordings/geort_train_session_001.jsonl \
  --cross-recording recordings/quest-20261017T135937-204414Z.jsonl \
  --compare-baselines
```

평가 script는 입력 녹화와 checkpoint의 실행 전후 hash를 검사하며 원본 파일을 덮어쓰지 않는다.
기존 source 보존 검사와 Ruff도 통과했다.
