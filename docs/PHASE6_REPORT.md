# Phase 6 — Wuji 원본 재현과 세 방법 비교

## 구현 범위와 소스 보존

고정 저장소는 `https://github.com/wuji-technology/wuji-retargeting`, commit은
`531f6ed4250b475d2e9231f54e988fc9b1c5b4ea`이다. MIT 라이선스 원본을 유지했다.
`Retargeter` / `AdaptiveOptimizerAnalytical` / `RobotWrapper`를 실제 checkout에서 직접 import한다.
commit 및 tracked source 변경 여부를 확인하고 Python source SHA256을 provenance로 저장한다.
원본 source, 원본 URDF, 기존 Phase 1–5 코드·설정·테스트·문서를 변경하지 않았다.

원본 `optimizer.urdf_path`와 `optimizer.link_naming` 설정이 사용자 로봇을 지원하므로,
DG-5F binding을 신규 adapter에 작성했다. 링크나 관절을 새로 만들지 않았다.

| 의미 | 실제 DG-5F 이름 |
|---|---|
| palm | rl_dg_palm |
| fingertip | rl_dg_[1–5]_tip |
| PIP 역할 | rl_dg_[1–5]_3 → rj_dg_[1–5]_3 |
| DIP 역할 | rl_dg_[1–5]_4 → rj_dg_[1–5]_4 |
| link1, optional finger-plane용 | rl_dg_[1–5]_1 |

Thumb의 PIP/DIP 역할은 각각 thumb MCP/IP를 뜻한다. 이 이름을 사람 thumb에
실제로 PIP/DIP가 존재한다는 의미로 사용하지 않는다.
Wuji의 link1은 finger-plane projection에 쓰인다. baseline의 `project_tip_dir=false`에서
해당 plane projection은 비활성화되어 있다. AnyDex adapter의 non-thumb link1은
MCP flexion-axis frame `_2`를 지정한다. 이 차이를 입력점 보정으로 숨기지 않는다.

원본 `RobotWrapper.get_actuated_qpos_index`가 link의 실제 parent joint를 찾아
PIP/DIP 10개 인덱스를 구성하는 것을 검증했다. Pinocchio의 전체 관절 순서는
joint name으로 공통 DG-5F 20개 순서로 재배열한다. FK와 Jacobian은 MuJoCo와 일치했다.

## 보존한 기본 설정과 제약 감사

`retarget: {}`로 코드 기본값을 사용한다. 공식 Wuji Glove/영상 YAML의 장치 보정 수치를
DG-5F나 공개 입력에 복사하지 않았다. 임의 gain/offset, 새로운 penalty나 필터를 추가하지 않았다.

| 항목 | Wuji 원본 기본값 |
|---|---|
| NLopt | LD_SLSQP, maxeval 50, ftol_abs 1e-4 |
| huber_delta / huber_delta_dir | 2.0 cm / 0.5 |
| norm_delta | 0.04 |
| w_pos / w_dir / w_full_hand | 1 / 10 / 1 |
| scaling / segment_scaling | 모두 1 |
| adaptive pinch | d1=2 cm, d2=4 cm, alpha 최대 0.7 |
| output filter | LPFilter alpha=0.2, 활성화 |
| thumb_skip_pip | false |
| w_hyper / soft_min | 0 / 0 rad |
| w_couple / couple_ratio | 0 / 0.7 |
| wrist/thumb offsets | 0 m |
| initial / warm start | 처음에는 관절 범위 중간값, 이후 이전 해 |

DG-5F의 해당 PIP/DIP 관절은 모두 ±pi/2 범위를 가지며 mimic은 없다.
Thumb PIP/DIP 역할 관절의 local axis는 둘 다 X, 나머지 손가락은 둘 다 Y다.
같은 손가락의 두 회전 방향이 일관됨을 확인했으나 이것이 사람의 DIP=0.7×PIP 비율이
로봇의 실제 제약임을 뜻하지 않는다. URDF는 독립적인 20개 관절을 제공한다.
공식 MANUS mapping도 해당 굽힘 입력을 양의 방향으로 출력하지만,
음수 관절각을 금지하는 것은 URDF 자체의 제한이 아니다.

원본 hyperextension 항은 max(soft_min−q, 0)의 제곱, coupling 항은
(DIP−couple_ratio×PIP)의 제곱으로 구성된다. baseline에서는 weight 0을 유지한다.
별도 진단 테스트에서 원본 Glove 예제에 존재하는 weight 1.0/0.1을 사용해
cost 차이와 gradient, 전체 목적함수 중앙차분을 검증했다. 이 진단 설정은
벤치마크에 사용하지 않았으며 DG-5F용으로 최적 weight를 찾은 것이 아니다.

## AnyDex와의 공통점과 차이

두 구현을 완전히 독립적인 알고리즘으로 취급하지 않는다. 아래 내용은 확보한 고정
commit의 실제 코드를 비교한 결과이며 이후 upstream 변경에 대한 주장은 아니다.

| 구분 | 공통 또는 차이 |
|---|---|
| 공통 구조 | MediaPipe 변환, Huber 위치/방향 loss, full-hand vectors, 거리 기반 adaptive pinch, 관절 regularization, SLSQP, LPFilter |
| 기본 파라미터 | 이번 baseline의 주요 loss weight·threshold·filter·budget 동일 |
| AnyDex FullHandVec | wrist→MCP→PIP→DIP→TIP segment를 순차적으로 scaling |
| Wuji FullHandVec | wrist→PIP/DIP/TIP 각 ray를 각각 scaling |
| AnyDex 확장 | 여러 robot/finger 수, mimic/point offset, lateral scaling, configurable pinch alpha, pinch scaling/contact 항 |
| Wuji 확장 | thumb PIP mask, hyperextension/coupling soft penalty, wrist/thumb offset |
| 기본값에서 확장 | 모두 현재 기본값에서는 비활성 또는 항등 변환 |
| warm start precision | AnyDex는 float64 optimizer 해를 저장하고 float32 반환, Wuji는 float32로 만든 해를 float64로 저장 |

모든 segment scale이 1이면 두 FullHandVec 방식은 같은 wrist-relative target으로 환원된다.
AnyDex base의 `finger_root_vectors` cache/comment만으로 robot mount anchoring을 추정하면
안 된다. 현재 `_compute_full_hand_vectors`의 실제 본문은 사람의 palm/segment 방향을
사용하며 cache를 target에 더하지 않는다. 원본을 수정하지 않고 실제 계산을 기준으로 비교했다.

고정 synthetic Open/Close/Pinch 3종 × 무작위 관절각 10개에서 기본 loss와 gradient를
직접 비교했다. 수치 오차 범위에서 같은 기본 목적함수라는 결과를 얻었다.
Sequential 해가 완전히 같아야 한다는 뜻은 아니다. warm start precision,
부동소수점 연산 순서와 NLopt 종료 조건에 따라 해가 달라질 수 있다.
그 차이를 새 알고리즘 기능의 효과로 해석하지 않는다.

## 공개 입력과 동일 조건

기존 `geort_alex` 3,498프레임, `anydex_avp1` 2,751프레임의 공통 HandFrame을 그대로 사용했다.
재생 시간은 기본 가정 30 FPS이며 원래 측정 FPS가 아니다.
세 방법 모두 common runner의 50 Hz control, 0.002 s physics timestep,
pi rad/s 명령 제한, 250 ms timeout, 동일한 DG-5F 모델을 사용한다.
초기 실제 상태는 영 자세다. optimizer 내부 초기값과 filter는 각각 원본을 유지한다.
마지막 source 프레임까지 소비하며 입력 스트림 hash 일치를 검사한다.

Wuji 예제 `example/data/avp1.pkl`의 checkout 파일은 pickle 본체가 아니라 Git LFS pointer다.
포인터의 object SHA256은
`95538edc0119ecf3e82093f6363a6c3376c5d7bb11de9e379efacebeecbb5506`, 크기는 1,689,467 bytes다.
이미 확보한 AnyDex 예제와 같으므로 추가 다운로드나 별도 독립 데이터셋 집계를 하지 않았다.
오른손 21개 keypoint와 출처·라이선스 metadata는 기존 adapter를 재사용한다.
참가자 ID가 없어 subject-disjoint는 검증할 수 없고 development-only 정책을 유지한다.

## 테스트와 실제 실행 결과

전체 테스트 **124개 통과**. 추가 12개에는 다음 검증이 포함된다.

- Wuji adapter와 원본 직접 호출의 출력 일치, reset 후 재현성.
- Pinocchio–MuJoCo FK/Jacobian 및 실제 PIP/DIP 인덱스.
- 기본값 비활성 제약과 원본 선택 penalty의 cost/gradient·중앙차분.
- 세 자세에서 AnyDex/Wuji의 공유 목적함수 확인.
- 무효/반대 손/역행/퇴화 입력 거부 및 회전·이동한 입력의 canonical 변환 일치.
- 세 방법의 동일 입력 hash, 결정성, 끝 프레임 소비, tracking loss hold.
- registry 등록/복원, LFS example의 동일 blob 확인.

기존 native SWIG/coal의 deprecation warning 3건은 남아 있다.
Ruff와 `uv pip check`도 통과했다. 외부 Git 저장소 8개는 고정 commit에서 clean이며,
Phase 6 시작 전 파일 86개는 변경되지 않았다. PROJECT_SPEC 17절은 이전 사용자 요청으로
추가된 부분이며 원래 prefix가 보존된 것을 기존 검증 경로에서 확인한다.
검사 기준은 `docs/phase6_existing_files.sha256.json`에 영구 보존했다.

| 입력 | 방법 | source 프레임 | 평균 ms | P95 ms | 정규화 tip 대응 오차 평균 | 횟수 예산 도달 |
|---|---|---:|---:|---:|---:|---:|
| geort_alex | manus | 3498 | 0.138 | 0.147 | 0.503362 | 0 |
| geort_alex | anydex | 3498 | 8.657 | 14.217 | 0.205747 | 49 |
| geort_alex | wuji | 3498 | 5.250 | 8.577 | 0.205748 | 48 |
| anydex_avp1 | manus | 2751 | 0.143 | 0.154 | 0.582854 | 0 |
| anydex_avp1 | anydex | 2751 | 6.790 | 15.129 | 0.186484 | 160 |
| anydex_avp1 | wuji | 2751 | 4.164 | 9.093 | 0.186473 | 167 |

이 표의 오차는 공통 URDF 제한 후 pipeline 목표각을 이용한 정규화 tip 대응 지표다.
사람은 wrist 기준 palm frame, 로봇은 URDF palm frame으로 계산하고 각각
wrist/palm→중지 MCP 길이로 정규화한다. AnyDex/Wuji 원본 출력 필터가 포함되어 있다.
독립적인 실제 사람 손 정답에 대한 정확도, 일반적인 알고리즘 우열이나 접촉 성공률이 아니다.
두 손의 origin·reference length와 추정 skeleton 품질에 영향을 받는다.
처리 시간은 전처리·원본 verbose solve/filter/진단을 포함하고 physics·평가 FK·logging·render를 제외한다.

기본 목적함수 비교 30건에서 loss와 gradient의 최대 차이는 모두 0이었다.

| AnyDex–Wuji 목표각 차이 | 전체 control tick·관절의 평균 절댓값 rad | 최대 절댓값 rad |
|---|---:|---:|
| geort_alex | 0.00000193 | 0.001680 |
| anydex_avp1 | 0.00016537 | 0.212414 |

AVP 일부 구간에서 최대 차이 약 0.212 rad가 관찰되었다. 이를 숨기거나 해를 맞추도록
원본을 수정하지 않았다. 두 코드의 실제 warm-start 저장 precision 차이는 확인했지만,
이 최대 차이의 원인을 precision만으로 완전히 분리해 증명한 것은 아니다.

접촉은 비활성화되어 있어 pinch/contact/grasp 성공을 주장하지 않는다.
전체 시퀀스 로그, 공통 입력과 짧은 비교 영상 6개를 생성한다.
최신 정확한 측정치와 산출물 경로는 `results/phase6_validation_latest.json`을 기준으로 한다.

## 생성 파일과 다음 단계

- `benchmark/retargeting/wuji.py`: 고정 원본 import·모델 binding·공통 출력 adapter.
- `benchmark/experiments/phase6_cli.py`, `scripts/run_phase6.py`: 세 방법 비교 진입점.
- `requirements/phase6.txt`: 기존 numerical stack과 SciPy 고정.
- `scripts/validate_phase6.py`, `verify_phase6_sources.py`: 전체 입력·영상·소스 보존 검증.
- `tests/test_phase6_wuji.py`, `docs/phase6_existing_files.sha256.json`.
- `README_PHASE6.md`, 이 보고서.

실제 Quest→Wuji 실시간 동작은 이번 단계의 검증 범위에 포함되지 않는다.
기존 Quest 녹화의 오프라인 재생 경로는 새 CLI에서도 사용할 수 있다.
다음 알고리즘 작업은 Phase 7 GeoRT의 DG-5F용 설정·학습·추론이며,
SHOW3D 작은 sequence 연결은 별도 공개 데이터 작업으로 남아 있다.
학습/평가 participant·sequence 중복을 확인하고 학습에 쓴 공개 예제를 held-out 점수로
재사용하지 않아야 한다. 네 방법 전체 비교는 GeoRT까지 연결한 뒤 수행한다.
