# Phase 4 재현 범위와 입력 adapter

## 원본 재사용

대상 저장소는 `tesollodelto/dg5f_ros2`, 고정 commit은
`0cb45ae9474caa92410dfa820346da8ffbae8405`이다.
대상 파일은 `external/dg5f_ros2/dg5f_driver/script/manus_retarget/manus_retarget.py`,
함수는 `ManusBimanualRetarget._compute_mqd_from_q`이다.
전체 파일 SHA256은 `730f2b4e1c89669f2249c0e8476ded58333c019bbaf501523075abb2a57a3ca4`이다.

`benchmark/retargeting/manus_vendor.py`는 파일 해시를 확인하고 원본 함수 AST를 읽는다.
독립 함수로 호출하기 위해 staticmethod decorator만 제거하며 계산 본문은 변경하지 않는다.
ROS node 생성, MANUS 메시지 수신, 로봇 하드웨어 송신은 실행하지 않는다.
따라서 재현 범위는 원본의 **각도 입력→20개 목표각 계산 함수**이며 전체 ROS 노드 재현은 아니다.
원본 파일을 변경하면 adapter가 중단되므로 변경 내용을 먼저 검토해야 한다.

원본 thumb offset 58.5도/20도, finger offset 40도/30도와 calibration gain,
방향 부호, 음수 굽힘 처리, pinky 조건 분기를 그대로 유지한다.
원본 pinky 계산이 마지막 DIP 입력을 직접 사용하지 않는 동작도 유지한다.
원본 ROS 발행 경로는 `clamped_vals`를 계산하지만 `out_vals`를 발행한다.
이를 수정하지 않고 계산 함수 결과를 먼저 기록한 뒤 공통 URDF 관절 제한을 적용한다.

## Quest 입력 표현의 한계

`quest_ergonomics.py`는 기존 공통 21개 keypoint에서 각도를 계산한다.
이는 프로젝트에 필요한 입력 adapter이며 공식 MANUS sensor reconstruction이 아니다.
손가락별 정적 reference 차감, offset 상쇄, gain 보정, 데이터별 파라미터 학습은 없다.
원본의 MANUS 입력과 Quest proxy 간 차이도 이 방식의 적용 한계로 평가한다.
`feature_reference_deg`, `feature_gain`, `ergonomics_bias_deg` 설정은 거부한다.

좌표계는 먼저 기존 `world_points`로 source world에 복원한다. 사람 손 palm 축은
Z=손목0→중지 MCP9, Y=소지 MCP17→검지 MCP5를 Z에 직교화한 방향,
오른손 X=Y×Z이며 왼손 굽힘 계산에서는 X 부호를 뒤집는다.
위치 단위는 meter, 함수 출력은 degree, 최종 로봇 목표각은 radian이다.

20개 입력은 다음 순서다. 이 순서는 원본 함수의 입력 슬롯에 대응한다.

| 슬롯 | Quest proxy 정의 |
|---|---|
| 0 | thumb metacarpal(1→2)의 Y–Z 평면 방향 atan2(Z,Y) |
| 1 | 같은 벡터의 palmar elevation atan2(X,hypot(Y,Z)) |
| 2 | thumb 1→2와 2→3 사이 unsigned bend |
| 3 | thumb 2→3과 3→4 사이 unsigned bend |
| 4–7 | index spread, MCP flex, PIP bend, DIP bend |
| 8–11 | middle의 같은 네 각도 |
| 12–15 | ring의 같은 네 각도 |
| 16–19 | pinky의 같은 네 각도 |

Non-thumb spread는 proximal direction의 atan2(Y,hypot(X,Z)), MCP flex는
atan2(X,Z), PIP/DIP는 인접 bone 사이 acos 각도다. Unsigned bend이므로
PIP/DIP hyperextension을 구분하지 못한다. Thumb opposition/elevation과
MANUS 원래 ergonomics의 동등성은 검증하지 않았다. 관절 rotation은 사용하지 않는다.
퇴화한 bone/palm 축, 추적 무효 입력, 반대 손 입력과 같은 session의 시간 역행은 거부한다.

## 계층과 기록

`ManusRetargeter`는 기존 `BaseRetargeter`를 구현한다. 원본 매핑을 호출한 후
공통 관절 제한을 적용하며 `RetargetingResult`에 다음을 남긴다.

- `features_deg` / `ergonomics_proxy_deg`: 동일한 20개 입력 각도.
- `q_vendor_raw`: 제한을 적용하기 전 원본 함수 결과.
- `joint_limit_clipped`: 공통 URDF 제한 적용 여부.
- `preprocess_s`, `mapping_s`, `total_s`: 처리 시간.

`retarget_q_target`은 공통 제한 후 목표다. `simulation.q_command`는 downstream 속도
제한 후 actuator 명령, `simulation.q_actual`은 동역학 실제 상태다.
`simulation.q_target`은 기존 runner가 받은 명령이므로 이 실행기에서는
`q_command`와 같은 제어 입력이며 원본 출력은 `q_vendor_raw`에서 확인한다.
추적 손실 행의 `retarget_q_target`은 hold 명령이며 retarget metadata는 null이다.
출력이 생성되지 않은 행을 알고리즘의 새 출력으로 평가하지 않는다.

현재 제어 주기는 50 Hz, MuJoCo timestep은 0.002 s, 최대 명령 속도는 pi rad/s,
입력 유효기간은 0.25 s이다. 추가 필터나 optimizer는 없다. 추적 손실 시 마지막 적용
명령을 유지한다. 물리 상태는 이 명령을 향해 계속 안정화될 수 있다.
이 제어 정책은 retargeting 개선으로 평가하지 않으며 후속 방법에도 동일하게 적용해야 한다.

`ManusController`/`manus_cli.py`는 Phase 4 실행 계층이다. 기존 Phase 3 receiver를
상속하고 입력 JS/CSS를 그대로 재사용하여 8024 포트의 별도 페이지를 제공한다.
기존 코드 수정 없이 확장하기 위해 기존 CLI와 registry 전역 상태를 변경하지 않았다.
Python에서 registry 사용 시 `register_manus()`를 명시적으로 호출한다.

## 추가 파일

- `configs/manus_quest.json`: hand side, downstream 속도 설정, 입력 한계 설명.
- `benchmark/retargeting/{manus,manus_vendor,quest_ergonomics}.py`: adapter와 원본 계산 재사용.
- `benchmark/experiments/manus_{control,log,fixtures,cli}.py`, `manus_live.html`: 실행과 로그.
- `scripts/run_manus.py`, `scripts/validate_phase4.py`: 실행 및 검증 진입점.
- `tests/test_phase4_manus.py`: 재현성/원본 함수 일치/통합 테스트.
- `README_PHASE4.md`, 이 문서, `AGENTS.md`: 재현 절차와 평가 원칙.

Phase 4의 구현·오프라인 테스트는 수행했다. 실제 Quest와 MuJoCo 연결의 사용자 확인 및
성공적인 pinch 접촉 검증은 남아 있다. 녹화에 gesture 정답 label이 없어 해당 성공률은
계산하지 않는다. 후속 공통 benchmark에서 정규화 길이·정렬·지표·평가 구간을 정한 뒤
원본 출력의 기구학 평가와 공통 controller의 동역학 평가를 각각 수행한다.
