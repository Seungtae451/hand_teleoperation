# GeoRT 네 모델 실시간 비교

하나의 Quest 오른손 입력을 네 GeoRT 모델에 전달하고 MuJoCo 창 네 개를 띄운다.

| 창 왼쪽 위 이름 | 학습 데이터 |
|---|---|
| `OFFICIAL_3498` | 공식 human_alex 3,498프레임 |
| `QUEST_1000` | 공개 Quest 1,000프레임 |
| `QUEST_3498` | 공개 Quest 3,498프레임 |
| `QUEST_10000` | 공개 Quest 10,000프레임 |

```bash
cd /home/cocelo-server01/stkim_ws/Hand_teleoperation
MUJOCO_GL=glfw .venv/bin/python scripts/run_geort_models_live.py --port 8026
```

네 이름의 `READY`가 출력되면 Quest 브라우저에서 `https://192.168.100.136:8026/`에
접속하고 손 추적을 시작한다. IP가 바뀌면 콘솔에 표시된 주소를 사용한다.
기존 페이지가 열려 있으면 새로고침한다. PC의 네 창이 겹치면 옮겨 배치한다.
서버가 이미 실행 중이면 명령을 중복 실행하지 않는다.

오른손을 펴기·주먹 쥐기·엄지와 각 손가락 pinch·한 손가락씩 굽히기를 천천히 반복하면
모델별 차이를 관찰하기 쉽다. 왼손은 표시만 하고 DG-5F는 오른손으로 제어한다.
창 하나를 닫거나 실행 터미널에서 `Ctrl+C`를 누르면 전체 세션이 종료된다.

특정 모델만 보려면 `--methods official_3498 quest_10000`처럼 선택한다.
모델 목록은 기본적으로 `results/geort_data_size_20261018/models.json`에서 읽으며,
다른 목록은 `--geort-study PATH`로 명시한다. 로딩 전에 완료 상태와 체크포인트 hash를 검사한다.
원본 GeoRT와 학습 체크포인트는 수정하지 않는다. 추가 보정 프로파일을 적용하지 않는다.

네 프로세스 모두 `.venv-geort`를 사용한다. 공통 제어 목표 50 Hz, 물리 timestep 0.002초,
명령 속도 제한 π rad/s, 추적 timeout 0.25초를 유지한다. 접촉은 비활성이다.
추적이 끊기면 마지막 적용 명령을 유지한다.

동일한 최신 입력을 각 프로세스에 전달하지만 프로세스 스케줄링에 따라 실제 소비한 프레임은
다를 수 있다. 따라서 이 실행은 정성적 관찰용이며 동일 프레임의 정량 offline 평가를 대체하지 않는다.

`results/live-retargeting-*/`에 입력 녹화, 모델별 목표·명령·실제 관절 상태, 프로세스 콘솔,
`session.json`을 저장한다. 모델별 JSONL 헤더에 실제 체크포인트 hash가 기록된다.
이 관찰 세션을 이후 학습 데이터로 자동 추가하지 않는다.

## 검증 재현

```bash
MUJOCO_GL=glfw .venv/bin/python scripts/validate_live_retargeting.py \
  --viewer --port 8027 --geort-study results/geort_data_size_20261018/models.json
```

기존 녹화 패킷 150개로 네 모델의 입력 전달·20관절 출력·전송 중단 후 HOLD를 확인했다.
이 녹화는 통신 경로 검사에만 사용했으며 네 모델의 학습이나 성능 평가에는 사용하지 않았다.
검증 결과: `results/live-validation-2m43svdr/validation.json`.
