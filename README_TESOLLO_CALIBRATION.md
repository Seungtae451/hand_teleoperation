# DG-5F 로봇 설정과 보정 프로파일

기존 기본값 실행 결과를 보존하면서 로봇별 설정을 별도 프로파일로 추가했다.
원본 Git 저장소·공식 URDF·기존 adapter·학습 체크포인트는 수정하지 않았다.
프로파일은 `configs/tesollo_calibrated/profile.json`이다.

## 실행

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
MUJOCO_GL=glfw .venv/bin/python scripts/run_calibrated_retargeting.py --port 8026
```

Quest 브라우저에서 `https://192.168.100.136:8026/`에 접속해 손 추적을 시작한다.
이미 서버가 실행되어 있으면 새 서버를 실행하지 말고 브라우저만 새로 연결한다.
PC IP가 바뀌었다면 콘솔에 표시된 주소를 사용한다.
네 MuJoCo 창의 이름으로 방법을 구분하고, 겹친 창은 옮겨 배치한다.
`Ctrl+C` 또는 창 하나를 닫으면 전체 실행이 종료된다.

한 방법만 보려면 `--methods anydex`, `--methods wuji` 등을 추가한다.
다른 프로파일은 `--robot-profile PATH`로 선택한다.

기존 기본값 동작도 유지된다.

```bash
.venv/bin/python scripts/run_live_retargeting.py --port 8026
```

## 적용 범위

| 방법 | 적용 내용 | 보정 절차의 출처 |
|---|---|---|
| AnyDex | `mediapipe_rotation`, 손가락별 4개 `segment_scaling`, `pinch_scaling` | 고정된 공식 저장소의 rotation/scaling 함수 본문을 그대로 실행. Pinch는 공식 펼친 손 식지 도달 거리 비율 사용 |
| Wuji | `mediapipe_rotation`, 손가락별 3개 `segment_scaling`, 전역 `scaling` | 프로젝트의 로봇 기하 설정 adapter. 원본이 지원하는 설정 필드로 전달 |
| MANUS-style | 기존 공식 DG-5F 매핑과 보정값 유지 | Quest의 기하 proxy를 위한 공식 보정 절차는 확인되지 않아 새 gain·offset을 추가하지 않음 |
| GeoRT | 기존 DG-5F 설정과 사용자 학습 모델 유지 | 원본 로봇 설정·학습 절차 사용. 학습 후 입력 회전·스케일은 변경하지 않음 |

AnyDex는 손목→MCP와 세 지골의 길이를 각각 보정한다. Wuji는 손목→PIP/DIP/TIP
벡터 길이를 보정하므로 같은 `segment_scaling` 숫자를 복사하면 안 된다.
Wuji에는 AnyDex 공식 함수가 반환하는 누적 도달 거리 비율을 해당 필드 의미에 맞게 전달한다.
이 연결은 **공식 Wuji 자동 보정 절차가 아니다**. 포함된 Wuji 보정 스크립트는 Wuji 장갑과
전용 링크 이름에 묶여 있어 Quest/DG-5F에 그대로 적용하지 않았다.

AnyDex 공식 함수의 AST 본문은 수정 없이 읽어서 실행한다. 카메라·장치 import와 원본 YAML
덮어쓰기는 실행하지 않으며, DG-5F용 임시 바인딩은 새 프로파일 폴더 안에만 만든다.
`calibration.upstream_helpers_sha256`과 각 adapter provenance에 원본 출처를 기록한다.

목적함수·가중치·추가 제약·solver 설정·필터·공통 제어 정책은 변경하지 않았다.
보정 로더는 새 손실 가중치 등 기하 설정 이외의 retarget 항목을 거부한다.

## 현재 초기 프로파일

- 입력: `recordings/geort_train_session_001.jsonl`의 오른손.
- 입력 종류: Quest WebXR 추정 골격. 네이티브 Quest SDK의 직접 출력으로 표기하지 않는다.
- 선택: 가장 긴 연속 펼친 손 후보 중 앞 5초, 226프레임.
- 구간: 녹화 시작에서 약 5.4–10.4초. 정확한 수신 시각과 프레임 인덱스는 프로파일에 기록했다.
- 후보 기준: 비엄지 MCP 굽힘 절댓값 <25°, 모든 비엄지 PIP/DIP 굽힘 <25°,
  프레임 간격 ≤0.1초. 수동 동작 라벨이 아니며 펼친 손 자세의 사용자 확인은 아직 받지 않았다.
- 회전 보정 XYZ: 약 `[1.662, 2.724, -3.182]`도.
- AnyDex pinch 스케일 / Wuji 전역 도달 거리 스케일: `1.0844`.
- 분절별 값은 프로파일에 고정되어 있다. 추적 중 자동 재보정하지 않는다.

회전만 보정한 손가락 뿌리 위치 잔차는 엄지 약 33.3 mm, 새끼 약 24.5 mm다.
이 값은 인간 손목과 로봇 palm을 원점으로 비교한 형상 차이도 포함한다.
회전 보정으로 모든 위치 차이가 사라지는 것은 아니며, 임의의 위치 offset으로 맞추지 않았다.

같은 녹화를 GeoRT 학습에도 사용했다. 따라서 이 녹화를 보정 후 독립 test로 사용하면 안 된다.
참가자 정보가 없어 참가자 분리도 검증되지 않았다. 이번 작업은 실행 설정과 재현 검증이며,
기존 평가 보고서의 결과를 보정 후 결과로 바꾸거나 성능 향상을 주장하지 않는다.

## 새 데이터로 재생성

자연스럽게 손가락을 펴서 약 5초 이상 유지한 별도 Quest 녹화를 권장한다.
기존 녹화 형식 `quest_hand_recording_v1`을 그대로 사용한다.

```bash
.venv/bin/python scripts/calibrate_tesollo.py \
  --input recordings/YOUR_CALIBRATION.jsonl \
  --output configs/tesollo_calibration_session_002 --seconds 5

.venv/bin/python scripts/run_calibrated_retargeting.py \
  --robot-profile configs/tesollo_calibration_session_002/profile.json --port 8026
```

출력 폴더는 새 경로여야 한다. 기존 파일은 덮어쓰지 않는다.
펼친 손 후보가 충분하지 않으면 실패하며, 임의 keypoint나 보정 기본값을 생성하지 않는다.
보정 데이터로 설정을 고정한 다음 별도의 세션을 평가에 사용한다.

현재 입력을 사용한 재현 명령은 다음과 같다.

```bash
.venv/bin/python scripts/calibrate_tesollo.py \
  --input recordings/geort_train_session_001.jsonl \
  --output results/tesollo_calibration_reproduction --seconds 5
```

## 검증

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/validate_live_retargeting.py \
  --viewer --port 8027 --robot-profile configs/tesollo_calibrated/profile.json
.venv/bin/python scripts/verify_phase7_sources.py
```

- 전체 테스트: 148 passed, 1 skipped. Skip은 별도 GeoRT 환경에서 실행하는 GPU/SAPIEN 검사다.
- AnyDex/Wuji 원본 API 직접 호출과 보정 adapter의 출력 일치 검증 통과.
- 각 방법에서 0자세·20개 개별 관절·무작위 12개 자세의 FK를 MuJoCo와 비교했다.
  최대 좌표 차이 `5.55e-17 m`. 이는 모델 연결 검증이며 사람 손 모양의 정확도 지표는 아니다.
- 녹화 native 패킷 150개를 HTTPS/WSS 수신기로 보내 네 창의 입력 전달과 timeout HOLD를 확인했다.
  결과: `results/live-validation-i9_ge72p/validation.json`.
- 동일 입력으로 프로파일을 다시 생성했을 때 SHA-256이 동일했다.
  결과: `results/tesollo-calibration-repro-szoxde2t/verification.json`.
- 외부 저장소 8개 clean, 보존 대상 기존 프로젝트 파일 96개 unchanged.

세션 로그는 `results/live-retargeting-*/`에 저장된다. 헤더에 실제 설정·프로파일 hash·출처가 기록되고,
원본 출력, 관절 제한 이후 목표, 제어 명령, 실제 시뮬레이션 상태는 구분되어 기록된다.
