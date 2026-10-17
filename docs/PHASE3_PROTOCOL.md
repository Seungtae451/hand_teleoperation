# Phase 3 데이터 계약

## 근거와 기존 코드 재사용 범위

참고한 로컬 파일:

- `../humanoid_teleoperation/scripts/run_quest.py`: HTTPS/WSS, 별도 source와 viewer, session 관리
- `../humanoid_teleoperation/web/client.js`: WebXR 세션 시작과 user activation 처리
- `../humanoid_teleoperation/hteleop/input.py`: sequence 및 수신 timeout 처리 개념
- `../quest_robot_isaac/teleop/xr_tls.py`: 인증서 경로 검색 방식

기존 파일을 import/patch하여 휴머노이드 동작을 바꾸지 않았다. 별도 입력 전용 서버를 작성했다.
특정 Isaac/Three.js 설치 경로를 실행 의존성으로 가져오지 않는다.

외부 API는 [W3C WebXR Hand Input](https://www.w3.org/TR/webxr-hand-input-1/),
[WebXR Device API](https://www.w3.org/TR/webxr/), 실제 설치한 websockets 16.1.1의 공개 API를 확인했다.
WebXR 입력을 쓰는 선택은 사용자가 승인한 Phase 3 입력 경로다. HTS SDK 네트워크 수신 adapter는 이번 범위에 추가하지 않았다.

## 네트워크

단일 HTTPS 포트 기본값 8023. `/`은 웹 화면, `/client.js`와 `/style.css`는 로컬 정적 파일,
`/protocol.json`은 명시적인 이름/단위 계약, `/status`는 최신 유효 상태를 반환한다.

`/ws?role=source`는 입력 소스 하나만 허용한다. `/ws?role=viewer`는 읽기 전용이다.
PC에서 모니터를 열어도 소스 소유권이 바뀌지 않는다. source의 session ID는 서버가 생성한다.
동시에 두 번째 source가 연결하면 기존 연결을 유지하고 두 번째 연결에 오류를 반환한다.

클라이언트의 각 패킷은 아래 필드를 가진다.

| 필드 | 의미 |
|---|---|
| version | 정수 1 |
| type | frame / tracking_stopped / reference_reset |
| sequence | 세션 안에서 증가하는 정수 |
| source_time_ms | 브라우저 performance.now() 시계의 ms |
| reference_space | local-floor 또는 local |
| reference_epoch | reference reset 때 증가 |
| joint_names | frame일 때 native 25개 이름을 정해진 순서로 전송 |
| hands.left / hands.right | 각 손의 valid 상태 및 pose 배열 |

valid인 손은 `emulated=false`, `positions=(25,3)`, `rotations=(25,4)`를 보낸다.
회전은 단위 xyzw quaternion이다. invalid 손은 valid=false와 reason을 보낸다.
클라이언트는 최대 60Hz를 목표로 전송하며 backpressure가 쌓이면 과거 프레임을 더 큐잉하지 않는다.
이 값은 Quest에서 실측한 추적 주파수가 아니다.

sequence·source timestamp·reference epoch가 역행하는 패킷은 거부한다.
형식 오류, 잘못된 크기, NaN/Inf, 미확인 joint name/order, emulated pose는 공통 valid frame으로 반영하지 않는다.
한 손 검증이 실패하면 패킷의 다른 손도 부분 반영하지 않는다.

## 25 → 21 이름 매핑

WebXR native index는 wrist=0이다. HTS 소스에서 사용한 OpenXR wrist=1 인덱스와 다르다.

| 공통 index | WebXR native index | 역할 |
|---|---|---|
| 0 | 0 | wrist |
| 1~4 | 1,2,3,4 | thumb metacarpal/proximal/distal/tip |
| 5~8 | 6,7,8,9 | index proximal/intermediate/distal/tip |
| 9~12 | 11,12,13,14 | middle proximal/intermediate/distal/tip |
| 13~16 | 16,17,18,19 | ring proximal/intermediate/distal/tip |
| 17~20 | 21,22,23,24 | pinky proximal/intermediate/distal/tip |

thumb 외 네 metacarpal을 제외한다. 원본 25개 위치·회전은 native_packet 이벤트에 모두 남는다.
common frame은 기존 `HandFrame`에 맞는 21개 위치·회전이다.

## 좌표와 시간

WebXR reference 좌표는 RH이며 위치는 m이다. Unity LH 변환을 추가하지 않는다.
기본 `wrist_rh`는 `R_world_wrist.T @ (p_world - t_world_wrist)`이며,
관절 회전도 `R_world_wrist.T @ R_world_joint`로 변환한다.

선택적 `palm_rh`는 원점=wrist, +Z=wrist→middle MCP,
+Y=pinky MCP→index MCP를 +Z와 직교화한 방향, +X=+Y×+Z다.
좌우손 라벨은 유지한다. 이것은 기하학적 사람 손 frame이며 로봇 palm 정렬·크기 보정을 뜻하지 않는다.
축이 퇴화한 자세는 유효한 palm frame으로 만들지 않는다.

`HandFrame.wrist_position/wrist_rotation`은 좌표 변환 이후에도 원본 WebXR world의 손목 pose다.
`joint_rotations`는 `joint_positions`와 같은 frame이다. source frame과 reference epoch는 metadata에 남는다.

공통 `timestamp`는 PC 수신 monotonic seconds다. source_time_ms와 선택적인 XR callback 시간은
원본 패킷에 보존한다. 서로 다른 시계를 같은 값으로 비교하지 않는다.
기본 timeout 0.25초는 마지막 valid 수신 시각에 적용하며, 잘못된 패킷은 유효 시각을 갱신하지 않는다.

## Tracking loss

- 첫 valid pose 이전에는 가짜 좌표를 만들지 않는다. status frame은 null이다.
- valid pose 이후 누락/timeout/중단/disconnect이면 tracking_lost 이벤트를 남긴다.
- 마지막 pose를 가진 invalid HandFrame도 기록하되 `tracking_valid=false`, `held_pose=true`,
  invalid_reason 및 last_valid_receive_time_s를 붙인다. 새 측정으로 해석하면 안 된다.
- 정상 데이터가 돌아오면 새 valid frame으로 갱신한다.
- 새 source session은 순서·이전 pose·유효 시각을 초기화한다.
- reference reset은 별도 무효화 이벤트로 남는다. 후속 retargeter의 보정/재개 정책은 Phase 4에서 정한다.

## 녹화와 재생

JSONL 첫 줄은 schema=`quest_hand_recording_v1` header다.
header에는 source_kind, target frame, timeout, native/common layout 및 생성 시각이 있다.
event는 session_start/end, native_packet, hand_frame, tracking_lost, rejected_packet이다.

`webxr_live`와 합성 검증 데이터의 source_kind를 구분한다. 합성 입력을 실제 Quest 녹화라고 표시하지 않는다.
기존 녹화 파일을 덮어쓰지 않고 exclusive create한다.

`replay_frames()`는 기록된 common HandFrame의 값·metadata·유효 상태를 그대로 반환한다.
옵션으로 receive timestamp 간격에 맞춘 재생 속도와 handedness를 선택할 수 있다.
원본 timestamp를 현재 시각으로 교체하지 않는다. 실시간 controller에 재생 입력을 붙일 때에는
녹화 시간과 재생 스케줄 시각을 구분하는 별도 adapter가 필요하다.
