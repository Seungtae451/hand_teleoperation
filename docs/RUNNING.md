# 설치·촬영·재생

모든 명령은 프로젝트 루트에서 실행한다. Ubuntu 22.04 / Python 3.10 / MuJoCo 3.16.0 기준이며 ROS는 필요 없다. 원본 소스는 lock의 commit으로 확보하고 수정하지 않는다. 개인 녹화·checkpoint는 Git에 포함되지 않으므로 새 clone에는 별도로 제공해야 한다.

## 환경 설치

```bash
python3 scripts/fetch_external.py
uv sync --locked --python 3.10
uv pip install --python .venv/bin/python -r requirements/phase3.txt
uv pip install --python .venv/bin/python -r requirements/phase6.txt
.venv/bin/python -m benchmark build
.venv/bin/python -m benchmark inspect

uv venv .venv-geort --python 3.10
uv pip install --python .venv-geort/bin/python -r requirements/phase7-torch.txt
uv pip install --python .venv-geort/bin/python -r requirements/phase7.txt
uv pip install --python .venv-geort/bin/python -r requirements/figures.txt
uv pip check --python .venv-geort/bin/python
```

SAPIEN 2.x와 NumPy 1.x를 쓰는 GeoRT를 기본 NumPy 2.x 환경과 분리한다. 기존 환경이 있다면 venv를 다시 만들지 않는다. 전체 당시 버전은 `requirements/phase7-environment.lock.txt`에 있다. EGL 렌더링은 GPU 드라이버, GUI는 접근 가능한 그래픽 데스크톱이 필요하다.

## 실시간 네 방법 보기

```bash
MUJOCO_GL=glfw .venv/bin/python scripts/run_calibrated_retargeting.py --port 8026
```

터미널에 네 방법이 READY가 된 뒤 같은 네트워크의 Quest Browser에서 출력된 `https://PC_IP:8026/`에 접속한다. 컨트롤러를 내려놓고 손 추적을 시작한다. 종료는 Ctrl+C다. 한 방법만 보려면 `--methods anydex`처럼 지정한다. 사용 중인 포트로 서버를 중복 실행하지 않는다.

필요한 TLS 인증서는 다음처럼 만든다. IP는 실제 PC 주소로 바꾼다. 생성한 `results/phase3_tls/`와 개인 키는 Git에 올리지 않는다.

```bash
.venv/bin/python scripts/setup_quest_tls.py --host-ip YOUR_PC_IP
```

기본 GeoRT는 현재 공개 비교에 사용한 개인 full-range 모델이다.

```text
results/geort_dg5f_workspace/training-f9nel4wo/checkpoint/
  dg5f_right_geort_2026-10-18_03-29-30/{last.pth,config.json}
```

다른 모델은 `--checkpoint PATH/last.pth --config PATH/config.json`을 함께 지정한다. `run_live_retargeting.py`는 프로파일 없는 기본 설정, `run_calibrated_retargeting.py`는 고정 프로파일을 명시하는 실행기다. 동일 결과를 보려면 후자를 사용한다. 제한 범위 모델은 다른 adapter가 필요하므로 여기에 대체하지 않는다.

## 새 실제 손 + 관절 동시 녹화

우선 9초 예비 촬영으로 손·SRC 숫자가 녹화에 보이는지 확인한다.

```bash
.venv/bin/python scripts/record_comparison_take.py \
  --port 8036 --routine preflight --stage-seconds 3 \
  --output recordings/video_preflight_003
```

1. Quest 시스템의 영상 녹화를 먼저 시작한다.
2. Quest Browser에서 `https://PC_IP:8036/`에 접속하고 손 추적을 시작한다.
3. 화면 중앙 안내를 따라 오른손을 움직인다. DONE 후 추적과 시스템 녹화를 끝낸다.
4. PC에서 Ctrl+C로 정상 종료한다. Quest MP4를 해당 take의 `human.mp4`로 복사한다.
5. 실제 손·SRC·SYNC START/END가 보이는지 원본 영상을 재생해 확인한다.

본 촬영은 108초다. 기존 take를 덮어쓰지 않고 새 이름을 쓴다.

```bash
.venv/bin/python scripts/record_comparison_take.py \
  --port 8036 --routine benchmark --stage-seconds 6 \
  --output recordings/video_benchmark_003

.venv/bin/python scripts/inspect_comparison_take.py recordings/video_benchmark_003 \
  --output results/video_benchmark_003_audit.json
```

서버는 `quest_input.jsonl`, `markers.jsonl`, `take.json`을 만든다. MP4는 Quest 시스템 녹화에서 따로 옮긴다. 손끝이 잘 보이도록 조명·거리를 유지하고 녹화 중에는 다른 추적 XR 세션을 종료한다. 원본 녹화는 학습 데이터로 자동 합치지 않는다.

영상 시작·중간·끝에서 SRC 숫자를 읽고 PTS 초와 함께 anchor를 입력한다. 아래 숫자는 **예시**이며 새 영상에서는 직접 읽은 값으로 바꾼다.

```bash
.venv-geort/bin/python scripts/inspect_comparison_take.py recordings/video_benchmark_003 \
  --video recordings/video_benchmark_003/human.mp4 \
  --anchor 5.20:13020.0 --anchor 55.20:63020.0 --anchor 105.20:113020.0 \
  --output results/video_benchmark_003_alignment.json
```

## 현재 영상 재현

기본 MANUS 입력은 `thumb_axes_v2`다. 현재 공개 영상의 재생 상태는 `results/video_benchmark_002/manus_thumb_v2/replay/`, 이전 v1은 `results/video_benchmark_002/replay_full/`에 보존한다. MANUS 엄지 방향 수정만 비교한 현재 출판에서는 다른 세 방법의 기존 상태를 재사용했다. 아래 전체 재현 명령은 네 방법을 새로 실행하므로 timing은 다를 수 있다.

현재 원본은 `recordings/video_benchmark_002/human.mp4`다. 동영상 내용·hash는 그대로 유지하고 루트에서 take 폴더로 정리했다. 아래 출력 경로는 새 폴더여야 한다.

```bash
MUJOCO_GL=egl .venv/bin/python scripts/export_take_retargeting.py \
  --take recordings/video_benchmark_002 --output results/reproduction_full

MUJOCO_GL=egl .venv/bin/python scripts/rerender_take_camera.py \
  --source results/reproduction_full --output results/reproduction_palm

.venv-geort/bin/python scripts/publish_take_media.py \
  --take recordings/video_benchmark_002 --replay results/reproduction_palm \
  --alignment results/video_benchmark_002/alignment.json \
  --output results/reproduction_media
```

이미 저장된 실제 상태를 쓰려면 두 번째 명령의 source를 `results/video_benchmark_002/manus_thumb_v2/replay`로 지정한다. 재추론·재학습 없이 손바닥 카메라로 다시 그릴 수 있다.

카메라 215°/+20°, 로봇 화면 960×720, 합성 2560×1440, 25 FPS다. 16동작×6초와 그룹 clip 4개, 개별 방법·전체 영상을 생성한다. 공개 사본은 `docs/media/video_benchmark_002/`다. 재실행한 계산 시간이 과거와 완전히 일치한다고 보장하지 않는다.

## GeoRT 学習を再実行する場合

현재 모델은 학습 완료됐고 위 재생 명령은 재학습하지 않는다. 별도 실험으로 학습을 다시 할 때만 아래 명령을 쓴다.

```bash
# 새 workspace를 사용한다. 기존 모델을 덮어쓰지 않는다.
.venv-geort/bin/python scripts/run_geort.py prepare --workspace results/geort_reproduction
.venv-geort/bin/python scripts/run_geort.py train \
  --workspace results/geort_reproduction \
  --human-data data/geort/quest_train_session_002/human.npy \
  --manifest data/geort/quest_train_session_002/manifest.json

# plan_only를 확인한 뒤 같은 인자에 --execute를 추가하면 학습 시작
```

새 기록을 쓴다면 `run_geort.py export-input --input YOUR.jsonl --output data/geort/NEW --split train --drop-invalid`로 manifest를 포함한 export를 만든다. 무효 점을 생성하지 않고 같은 canonical 변환을 쓴다. 원래 학습 조건을 유지해도 GPU·난수·환경에 따라 가중치의 완전한 일치는 보장하지 않는다.

## 最小限の確認

```bash
.venv/bin/python scripts/verify_sources.py
MUJOCO_GL=egl .venv/bin/python -m pytest -q
.venv/bin/ruff check benchmark scripts tests
MUJOCO_GL=egl .venv-geort/bin/python scripts/build_explanation_figures.py
```

현재 실험의 모델·제어·촬영 회귀 테스트는 유지했다. 과거 phase snapshot 검증과 일회성 진단은 [외부 보관](PROJECT_LAYOUT.md)으로 분리했다. 원리 설명은 개념도로 표시하고 측정 그래프는 입력 출처를 명시한다.
