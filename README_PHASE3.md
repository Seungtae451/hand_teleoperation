# Phase 3 — Quest Browser 손 추적 수신·녹화·재생

Phase 3은 `humanoid_teleoperation`의 **HTTPS/WSS 연결 방식**을 참고해 별도 구현했다.
Quest Browser의 WebXR 손 추적을 사용하며, 기존 휴머노이드 서버·TLS helper·Phase 1·2 코드는 수정하지 않았다.
이 문서는 Phase 1·2용 루트 README와 구분한 Phase 3 실행 안내다.

현재 소프트웨어와 합성 입력을 이용한 HTTPS/WSS 검증을 완료했다.
**실제 Quest에서 추적 데이터가 수신되는지는 장치를 연결해서 확인해야 한다.**

## 연결 구조

```text
Quest Browser (WebXR 손 관절 25개, 위치·회전)
                │ HTTPS/WSS :8023
                ▼
       Python QuestReceiver
                │ 검증 · 이름 매핑 · 좌표 변환
                ▼
       공통 HandFrame (21개)
           ├── PC 손 골격 모니터
           ├── 원본/공통 데이터 JSONL 녹화
           └── 오프라인 재생 → 후속 Retargeter
```

기존 휴머노이드 서버의 8022와 충돌하지 않도록 8023을 사용한다.
Isaac Sim·Unity 앱·Quest Link는 이 입력 경로의 실행 의존성이 아니다.
로봇 목표각 생성은 아직 연결하지 않으며 MANUS-style adapter는 Phase 4에서 구현한다.

## 현재 PC에서 시작하기

작업 디렉터리: `/home/cocelo-server01/stkim_ws/Hand_teleoperation`.
이번 작업에서 확인한 PC IP는 `192.168.100.136`이다. IP가 바뀌면 주소와 인증서 설정을 갱신한다.

서버 실행:

```bash
.venv/bin/python scripts/run_quest_hand.py doctor
.venv/bin/python scripts/run_quest_hand.py serve --port 8023
```

1. PC와 Quest가 같은 로컬 네트워크에서 통신할 수 있게 한다.
2. Quest에서 손 추적을 활성화하고 컨트롤러를 내려놓는다.
3. Quest Browser에서 **https://192.168.100.136:8023/** 에 접속한다.
4. 새 로컬 인증서의 신뢰 처리를 Quest에서 직접 완료한다. WebXR에는 보안 연결과 손 추적 권한이 필요하다.
5. **Quest 손 추적 시작**을 누른다. 필요한 권한을 허용한 뒤 손가락을 움직인다.
6. PC 브라우저에서도 같은 URL을 열어 양손 골격과 수신 수 증가를 확인한다.

PC 페이지는 모니터 역할로 연결되어 Quest 입력 소유권을 가져가지 않는다.
추적 모드 중 Quest에는 투명 WebXR layer를 사용하며, 상세 모니터는 PC 페이지에서 확인한다.
Quest에서 AR 세션을 끝내거나 서버에서 Ctrl+C를 누르면 종료한다.

서버는 기본적으로 새로운 `recordings/quest-UTC시각.jsonl`을 만들고 입력을 즉시 기록한다.
기존 기록 파일은 덮어쓰지 않는다. 저장 경로를 지정하려면 아직 없는 파일명을 사용한다.

```bash
.venv/bin/python scripts/run_quest_hand.py serve \
  --record recordings/session_001.jsonl --frame wrist_rh --timeout 0.25
```

## 새 환경에서 설치

```bash
python3 scripts/fetch_external.py
uv sync --locked --python 3.10
uv pip install --python .venv/bin/python -r requirements/phase3.txt
```

Phase 3은 `websockets==16.1.1`을 직접 사용한다. 현재 Phase 2 lock에도 이미 포함된 버전이다.
Phase 2의 pyproject/lock을 수정하지 않고 직접 의존성을 별도 파일에 명시했다.
Python 3.10, NumPy, websockets와 표준 라이브러리를 사용한다. 테스트와 인증서 생성에는 openssl 명령이 필요하다.

## 인증서

공유 경로 `~/.config/xr_teleoperate/cert.pem`은 현재 IP를 검증할 SAN이 없어 이번 접속 검사에 실패했다.
공유 인증서와 개인키는 유지하고, 현재 IP·127.0.0.1·localhost를 포함하는 별도 인증서를
`results/phase3_tls/`에 생성했다. 개인키 권한은 0600, 폴더 권한은 0700이다.
이 폴더는 기존 `results/` ignore 규칙으로 Git에서 제외된다. 개인키를 공유하거나 배포하지 않는다.

새 환경에서 **최초 한 번만**, 아직 존재하지 않는 출력 폴더로 생성한다.

```bash
.venv/bin/python scripts/setup_quest_tls.py --host-ip 192.168.100.136
```

현재 PC에는 이미 생성되어 있으므로 같은 명령은 덮어쓰기를 거부한다.
IP 변경 시에는 새 폴더를 사용하고 명시적으로 지정한다.

```bash
.venv/bin/python scripts/setup_quest_tls.py --host-ip NEW_PC_IP --output results/quest_tls_new
.venv/bin/python scripts/run_quest_hand.py serve \
  --cert results/quest_tls_new/cert.pem --key results/quest_tls_new/key.pem
```

검색 순서: `--cert/--key` → `XR_TELEOP_CERT/XR_TELEOP_KEY` → 프로젝트 `results/phase3_tls/` → 공유 사용자 경로.
프로젝트는 시스템·브라우저 trust store를 변경하지 않는다. 인증서 신뢰 처리는 사용자가 장치에서 수행한다.

## Quest 없이 재현하기

수신 코드·좌표 변환·유효 상태·녹화·재생을 테스트할 수 있다.
합성 데이터는 실제 Quest 측정이나 retargeting 평가 결과가 아니다.

```bash
# 양손 합성 입력: 명시적인 추적 상실과 복귀 포함. 새 파일명을 사용한다.
.venv/bin/python scripts/run_quest_hand.py synthetic \
  --output recordings/phase3_synthetic_001.jsonl --frames 120

# 기록된 HandFrame 읽기, invalid 상태도 보존
.venv/bin/python scripts/run_quest_hand.py replay recordings/phase3_synthetic_001.jsonl

# 수신 시간 간격대로 1배속 재생, 오른손만 선택
.venv/bin/python scripts/run_quest_hand.py replay recordings/phase3_synthetic_001.jsonl \
  --realtime --speed 1 --hand right

# 동일 common frame을 새 JSONL로 내보내기
.venv/bin/python scripts/run_quest_hand.py replay recordings/phase3_synthetic_001.jsonl \
  --output results/phase3_canonical_001.jsonl

# 실제 TLS 검증을 켠 WSS loopback 통신으로 합성 입력 전송·저장·재생 검사
.venv/bin/python scripts/validate_phase3.py

# Phase 1·2 회귀 검사를 포함하는 전체 테스트
MUJOCO_GL=egl .venv/bin/python -m pytest -q --junitxml=results/phase3_pytest.xml
```

선택적으로 Node.js가 설치되어 있으면 `node scripts/test_webxr_client.cjs`로 브라우저 API mock 검사도 실행한다.
이 검사는 실제 Quest Browser 지원·권한·추적 품질을 검증하는 것은 아니다.

`validate_phase3.py`는 실행할 때마다 새로운 `results/phase3-*/synthetic_wss.jsonl`을 생성하고
`results/phase3_validation.json`에 실제 결과를 저장한다. 기존 입력 기록은 삭제하지 않는다.

## Python으로 후속 Retargeter에 연결

```python
from benchmark.tracking.recorder import replay_frames

for frame in replay_frames("recordings/session_001.jsonl"):
    if not frame.tracking_valid:
        # 후속 controller에서 유지/중단 정책을 명시적으로 적용한다.
        continue
    # frame.joint_positions: (21,3), m, 기본 wrist_rh
    # frame.joint_rotations: (21,4), xyzw, 같은 local frame
    # frame.wrist_position / wrist_rotation: 원본 WebXR world의 손목 pose
    # result = retargeter.retarget(frame)  # Phase 4 이후
```

실시간 연결도 `ReceiverState.latest["right"]`의 `HandFrame`을 같은 인터페이스로 읽을 수 있다.
현재 이 코드는 robot runner로 자동 전달하지 않는다. 사람 손 frame과 Tesollo palm 정렬 및
Quest→MANUS 입력 변환은 다음 단계의 보정·adapter 작업이다.

## 제한과 실기 확인 항목

- `hand-tracking`을 지원하고 권한을 부여한 Quest Browser가 필요하다. 실제 장치 동작은 미확인이다.
- WebXR 25개와 공통 21개 사이의 매핑은 이름으로 명시했다. HTS/OpenXR 숫자 인덱스와 혼용하지 않는다.
- WebXR는 RH이므로 Unity LH용 Y reflection을 적용하지 않는다.
- 기본 좌표는 wrist_rh. 선택적 palm_rh는 사람 손 기하에서 정의한 frame이며 로봇 보정이 아니다.
- 모든 native joint pose가 있어야 valid다. 누락·emulated pose·비정상 회전은 valid로 쓰지 않는다.
- 250ms 수신 timeout, 명시적 추적 상실, reference reset, disconnect를 기록한다.
  이전 좌표를 보유한 invalid frame에는 `held_pose=true`가 있으며 유효 입력으로 사용하면 안 된다.
- timeout은 수신 정지를 감지한다. source/PC 시계 동기화나 네트워크 지연의 절대 측정은 구현하지 않았다.
- 장치에서 실제 손 크기(m), 좌우손, 손목 회전, 가림/복귀, 실제 주기를 추가 확인해야 한다.

자세한 데이터 계약은 [프로토콜 문서](docs/PHASE3_PROTOCOL.md), 구현·테스트 결과는
[Phase 3 보고서](docs/PHASE3_REPORT.md)를 참조한다.
