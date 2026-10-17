# Phase 3 구현 및 검증 보고서

날짜: 2026-10-17, Asia/Seoul.

**소프트웨어 구현과 오프라인/네트워크 테스트를 완료했다. 실제 Quest 장치의 손 추적 수신 검증은 남아 있다.**
실측과 합성 데이터를 구분하며, 장치 연결 완료 조건을 달성했다고 주장하지 않는다.

## 구현한 기능

- 참고 프로젝트의 HTTPS/WSS 구조를 이용한 별도 Quest 입력 서버, 기본 포트 8023
- WebXR `hand-tracking`을 요청하는 Quest Browser 클라이언트
- 양손 25개 named joint의 위치·xyzw 회전 수집, 명시적인 21개 common joint 매핑
- world RH → wrist RH 및 선택적 geometric palm RH 변환
- source session 소유권, 순서 검증, 250ms 기본 timeout, tracking loss/disconnect/reference reset 기록
- PC에서 양손 골격과 유효 상태를 확인하는 읽기 전용 모니터
- raw native packet과 common HandFrame을 구분한 JSONL 녹화
- timestamp·metadata·invalid 상태를 보존하는 입력 replay와 선택적 실시간 pacing
- 실제 Quest 없이 시험하는 합성 fixture 및 TLS 검증을 켠 WSS 통합 검사
- 공유 인증서를 보존하는 별도 SAN 인증서 생성 도구

로봇 제어, Quest→MANUS 변환 및 네 retargeter 연결은 이 Phase에서 추가하지 않았다.
Phase 2의 합성 관절 명령 demo와 Phase 3의 합성 **사람 손 입력**은 서로 다른 테스트다.

## 원본 보존

Phase 3 시작 시 기존 코드·문서 및 참고 프로젝트 파일 66개의 해시를 기록했고,
구현 후 변경 파일은 **0개**였다. `HandFrame`, Phase 2 CLI, pyproject, uv.lock, 루트 README도 유지했다.
원본 모델·명세 261개 파일과 외부 GitHub checkout 8개의 무변경 검사도 통과했다.

루트 README를 수정하지 않고 새 실행 안내를 `README_PHASE3.md`에 작성했다.
추가 의존성도 `requirements/phase3.txt`에 별도로 명시했다.

## 생성한 주요 파일

| 경로 | 기능 |
|---|---|
| `benchmark/tracking/webxr_protocol.py` | 25/21 이름·순서 계약 및 입력 검증 |
| `benchmark/tracking/coordinate_transform.py` | RH 좌표 변환·quaternion 처리 |
| `benchmark/tracking/receiver_state.py` | 최신 상태·session·순서·timeout·loss |
| `benchmark/tracking/recorder.py` | 원본/공통 frame 녹화·재생 |
| `benchmark/tracking/quest_receiver.py` | HTTPS/WSS·정적 파일·PC viewer |
| `benchmark/tracking/quest_cli.py` | serve / doctor / synthetic / replay |
| `benchmark/tracking/synthetic.py` | 합성 WebXR 패킷 fixture |
| `benchmark/tracking/web/` | Quest 수집 및 PC 골격 모니터 UI |
| `scripts/run_quest_hand.py` | Phase 3 실행 진입점 |
| `scripts/setup_quest_tls.py` | 기존 인증서를 교체하지 않는 별도 인증서 생성 |
| `scripts/validate_phase3.py` | 합성 WSS 수신→녹화→재생 실측 |
| `scripts/test_webxr_client.cjs` | 브라우저 API mock 검사 |
| `tests/test_phase3_tracking.py` | 매핑·좌표·tracking·녹화/replay 검사 |
| `tests/test_phase3_transport.py` | 실제 TLS/WSS 및 인증서 무덮어쓰기 검사 |
| `README_PHASE3.md`, `docs/PHASE3_PROTOCOL.md` | 실행 방법과 데이터 계약 |

## 실제 실행 결과

환경: 기존 Python 3.10.12 가상환경, NumPy 2.2.6, websockets 16.1.1, OpenSSL 3.0.2.

| 항목 | 결과 |
|---|---|
| 전체 pytest | **88 passed**, 2.78초; 기존 66개 회귀 검사 포함 |
| Ruff check / format check | 통과 |
| 25→21 매핑 | 실제 WebXR 이름과 fingertip index 매핑 통과 |
| 좌표 변환 | 전체 손의 회전·이동 후 wrist/palm local geometry 불변 및 world roundtrip 통과 |
| 회전 | 무작위 및 π 회전 quaternion roundtrip 통과 |
| loss 처리 | 명시적 invalid, 수신 timeout, disconnect, reference reset, 복귀 검사 통과 |
| 순서·형식 | sequence/clock 역행 및 malformed/NaN/shape/회전 오류 거부 통과 |
| 실제 TLS/WSS | 검증된 테스트 인증서로 수신·모니터·중복 source 거부 통과 |
| 합성 WSS 수용 검증 | 121패킷 수신, valid common hand frame 222개, 거부 0개 |
| 녹화→재생 | 총 228개 common frame 중 invalid 6개 포함, 값과 metadata 동일 |
| 브라우저 API mock | hand feature 요청, reference fallback, 25개 수집, backpressure, loss/reset/end 검사 통과 |
| 현재 LAN URL 사전 점검 | 새 인증서로 hostname/IP 검증, HTTPS 4개 경로와 WSS viewer 연결 통과 |

합성 전송은 가속 실행했다. 위 패킷 수는 실제 Quest FPS나 장치 지연 측정치가 아니다.
브라우저 mock은 실제 Quest Browser의 지원/권한이나 화면 렌더링 검증을 대신하지 않는다.

실행 산출물:

- `results/phase3_pytest.xml`
- `results/phase3_validation.json`
- `results/phase3-*/synthetic_wss.jsonl`
- `results/phase3_browser_mock.json`
- `results/phase3_live_preflight.json`
- `results/phase3_integrity.json`, `results/phase3_upstream_integrity.json`

## 발견한 TLS 문제와 해결

공유 인증서는 로드는 가능했지만 현재 IP `192.168.100.136`에 대한 인증서 주소 검증에 실패했다.
공유 경로를 변경하지 않고 `results/phase3_tls/`에 현재 IP·127.0.0.1·localhost를 포함하는
별도 self-signed 인증서를 생성했다. 개인키는 0600, 디렉터리는 0700이며 기존 Git ignore 범위다.
동일 경로의 인증서 재생성은 거부하며, 자동으로 기존 인증서를 덮어쓰거나 trust store를 변경하지 않는다.

PC의 Python HTTPS/WSS 검사에서는 이 인증서를 명시적으로 신뢰하는 context를 사용했고
주소 검증을 활성화한 상태로 접속에 성공했다. 실제 Quest에서는 사용자가 새 인증서를 신뢰하는
절차를 직접 진행해야 한다.

## 현재 장치 연결 준비 상태

실행한 서버 URL: **https://192.168.100.136:8023/**.
사전 점검 시 PC viewer 연결을 확인했고 실제 Quest source 패킷은 0개였다.
따라서 실기 테스트는 아직 pending이다. 실행 세션이 종료되었으면 아래 명령으로 다시 시작한다.

```bash
.venv/bin/python scripts/run_quest_hand.py serve --port 8023
```

## 남은 문제와 다음 단계

1. Quest에서 인증서 신뢰·WebXR 손 추적 권한을 확인하고 실제 양손 데이터 갱신을 검증한다.
2. 실제 손 크기(m), 좌우손, wrist rotation, 손 가림/복귀, reference reset, 전송 주기를 점검한다.
3. 실제 입력 파일을 저장하고 Quest 없이 같은 frame이 재생되는지 확인한다.
4. 그 기록을 Phase 4의 MANUS-style adapter 입력으로 사용하고 사람 손 frame→로봇 palm 보정을 진행한다.

아직 구현하지 않은 항목: HTS SDK 수신 adapter, 네트워크 단방향 지연 측정/시계 동기화,
robot palm calibration, 실제 Quest→로봇 joint mapping, 네 retargeter 실행.
기존 Git 코드를 변경해야 하는 상황이 생기면 이유와 범위를 먼저 설명하고 사용자 확인을 받는다.
