# Quest → DG-5F 실시간 리타게팅

Quest 브라우저 한 곳에서 보낸 오른손 입력을 MANUS-style, AnyDex, Wuji, 학습된 GeoRT에
전달하고 PC에 MuJoCo 창 네 개를 띄운다. 각 창 왼쪽 위에 방법 이름과 추적 상태가 표시된다.
기존 upstream 코드와 기존 프로젝트 파일은 수정하지 않았다.

## 실행

PC의 그래픽 데스크톱 터미널에서 다음 명령을 실행한다.

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
MUJOCO_GL=glfw .venv/bin/python scripts/run_live_retargeting.py --port 8026
```

1. 콘솔에 네 방법의 `READY`가 표시될 때까지 기다린다.
2. 같은 네트워크의 Quest 브라우저에서 `https://192.168.100.136:8026/`에 접속한다.
   PC IP가 바뀌었다면 콘솔의 주소를 사용하고 인증서 설정을 확인한다.
3. 기존 연결 때처럼 인증서 경고를 처리하고 손 추적 시작 버튼을 누른다.
4. 컨트롤러를 내려놓고 오른손을 움직인다. PC 창이 겹치면 각각 옮겨 배치한다.
5. 터미널의 `Ctrl+C` 또는 MuJoCo 창 하나를 닫으면 전체 세션이 종료된다.

이미 실행 중인 세션에는 Quest만 연결하면 된다. 같은 포트의 서버를 중복 실행하지 않는다.
한 방법씩 보려면 다음처럼 선택한다.

```bash
.venv/bin/python scripts/run_live_retargeting.py --methods anydex --port 8026
.venv/bin/python scripts/run_live_retargeting.py --methods wuji --port 8026
.venv/bin/python scripts/run_live_retargeting.py --methods geort --port 8026
.venv/bin/python scripts/run_live_retargeting.py --methods manus --port 8026
```

## 실행 환경과 동작

- MANUS·AnyDex·Wuji는 `.venv`, GeoRT는 `.venv-geort`의 별도 프로세스를 사용한다.
- GeoRT 기본 체크포인트는 사용자가 학습한
  `results/geort_dg5f_workspace/training-2glhel2r/checkpoint/dg5f_right_geort_2026-10-18_00-40-37/last.pth`다.
  다른 모델은 `--checkpoint PATH --config PATH`로 명시한다. 학습은 실행하지 않는다.
- 기존 adapter와 공통 제어기를 재사용한다. 제어 목표 50 Hz, 물리 timestep 0.002초,
  관절 명령 속도 제한 π rad/s, 입력 timeout 0.25초다. 벽시계 실시간 주기는 시스템 부하의 영향을 받는다.
- 각 프로세스가 최신 입력을 소비하므로 같은 시각에 실제 소비한 프레임은 다를 수 있다.
  정량 평가에서 동일 프레임을 보장하려면 기존 offline benchmark를 사용한다.
- 입력이 끊기거나 유효하지 않으면 마지막 적용 명령을 유지한다.
- MANUS는 Quest 기하 입력 proxy다. 각 방법의 기존 필터·보정과 GeoRT 학습 결과는 유지한다.
- 접촉은 비활성 상태이며 실제 로봇을 구동하지 않는다.

`results/live-retargeting-*/`에 원본 Quest 입력 `quest_input.jsonl`,
방법별 원본 출력·관절 제한 이후 목표·제어 명령·실제 상태를 담은 `METHOD.jsonl`,
프로세스 콘솔과 `session.json`이 저장된다. `session.json`의 PID에 `kill -TERM PID`를 보내도
서버와 자식 프로세스가 정리된다. 연결 상태는 같은 주소의 `/status`에서 확인한다.

## 재현 검증

다음 검증은 실제 장치 대신 기존 녹화의 native 패킷 150개를 TLS 수신기로 전송한다.
네 방법의 TRACKING, 20관절 출력, 서로 다른 입력 시퀀스 소비와 전송 중단 후 HOLD를 검사한다.
별도 테스트 포트를 사용하며 종료 후 모든 테스트 프로세스를 정리한다.

```bash
.venv/bin/python scripts/validate_live_retargeting.py --viewer --port 8027
.venv/bin/python scripts/verify_phase7_sources.py
```

검증 결과: `results/live-validation-_y3whbcq/validation.json`.
네 창 표시와 전체 방법의 입력 전달·추적 중단 검증을 통과했다.
새 실제 Quest 세션의 연결은 사용자가 브라우저에서 손 추적을 시작한 뒤 확인한다.
