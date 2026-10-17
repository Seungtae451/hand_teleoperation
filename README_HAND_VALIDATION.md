# 공개 손 골격과 실제 Quest 입력 검증

PC: **http://127.0.0.1:8029/inspect**

Quest: **https://192.168.100.136:8028/**

1. Quest에서 위 HTTPS 주소에 접속해 손 추적 시작 버튼을 누른다. PC의 HTTP 화면은 관찰 전용이다.
2. 공개 후보에서 펼친 손을 선택하고 실제 오른손을 편다.
3. X–Z 측면에서 검지를 손바닥 쪽으로 천천히 굽혀 방향을 비교한다.
4. 최대 굴곡 후보와 pinch 후보도 비교한다. 재생 버튼과 프레임 slider로 같은 에피소드의
   전후 30프레임을 확인할 수 있다.
5. 필요하면 진단용 반사 표시를 켠다. det=-1 반사는 화면 복사본에만 적용한다.
6. 공개·실제 왼손도 비교한다. 좌우 손 라벨 문제인지 판단할 근거로 사용한다.

정면 Y–Z에서는 X 반사가 보이지 않으므로 측면 X–Z를 확인한다.
모든 그림은 같은 mm 스케일이며 격자는 10 mm다. 마우스를 관절 근처에 올리면 이름·좌표가 나온다.
관절 번호와 원본 에피소드·프레임·제공자의 동작 문자열도 표시한다.
후보 이름은 기하 기준 자동 선택이며 실제 동작의 정답 라벨이 아니다.

공개 학습 export와 검증 화면의 좌표 변환 차이는 0 m로 확인했다.
실제 오른손 입력도 기존 GeoRT canonical adapter와 비교한 차이를 화면 아래에 표시한다.
이는 같은 변환을 실행한다는 검사이며 **해부학적 방향의 정답을 보증하지 않는다**.
왼손에는 같은 기하 축 구성을 사용해 비교하되 오른손 모델에 전달하지 않는다.

이번 화면은 입력 의미 검증 도구다. 모델을 구동하거나 제어기를 바꾸지 않는다.
반사 후 모양이 비슷해지는 사실만으로 변환을 확정하지 않고, 제공자 좌표 규약·수집 코드·손 라벨과
해부학적 굽힘 방향을 함께 확인해야 한다. 확인 전에는 재학습하지 않는다.
모델 목표와 제어 추종의 분리는 기존 진단 보고서/실시간 관절 로그를 사용한다.

## 재현

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
# 최초 1회: 새 samples 파일을 생성한다. 기존 파일은 덮어쓰지 않는다.
.venv-data-audit/bin/python scripts/prepare_hand_validation.py

# samples 파일이 있으면 이 명령만 실행한다.
.venv/bin/python scripts/run_hand_validation.py --port 8028 --monitor-port 8029

.venv/bin/python -m pytest -q tests/test_hand_validation.py
```

이미 서버가 실행 중이면 중복 실행하지 않는다. 종료는 실행 터미널의 Ctrl+C,
또는 `results/hand-validation-*/session.json`의 PID에 `kill -TERM PID`를 사용한다.
실제 PC IP가 바뀌면 콘솔에 출력된 HTTPS 주소를 사용한다.

공개 자료는 현재 10k 학습 부분집합에서 후보를 고르고, 같은 학습 에피소드의 원본 26관절을
common21로 선택했다. 공개 test·validation은 사용하지 않았다.
`results/hand_validation_public_20261018.json`에 양손의 원본 canonical 좌표와 출처가 보존된다.
새 Quest 입력은 `results/hand-validation-*/diagnostic_quest_input.jsonl`에 진단용으로만 기록하며
학습에 자동 추가하지 않는다. 원본 Git·학습 입력·체크포인트는 변경하지 않는다.

HTTP/WSS 검사: `results/hand-validation-rx87q1bu/validation.json`.
브라우저 표시 검사: 같은 폴더의 `screen.png`.
이 검사는 통신과 좌표 변환의 재현성을 확인하며 실제 손 방향 검증은 사용자의 동작 관찰이 필요하다.

## X 방향 관찰 이후

사용자가 양손의 X 굽힘 반대를 확인했다. 배포 이력 조사와 별도 parity adapter를 사용하는
재학습 실험은 [README_GEORT_PARITY.md](README_GEORT_PARITY.md)에 기록한다.
이 화면과 원본 samples는 이전 입력을 그대로 보존하며, 반사 checkbox도 여전히 표시 전용이다.
수집 코드가 없어 제공자 확인 변환으로 단정하지 않고 empirical parity 실험으로 구분한다.
