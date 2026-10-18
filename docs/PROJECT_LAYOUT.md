# 현재 실험과 과거 자료 분리

현재 실험은 Quest의 동시 추적·실제 손 영상, DG-5F 오른손, 네 방법의 동일 입력 재생과 비교다. 이 경로와 재현에 필요한 코드는 프로젝트에 남겼다. 과거 시행착오 자료는 삭제하지 않고 같은 파일시스템에서 이동했다.

## 프로젝트에 남긴 것

| 경로 | 남긴 이유 |
|---|---|
| `benchmark/` | HandFrame·전송·원본 알고리즘 adapter·학습·로봇·공통 제어 |
| `scripts/` | 설치·촬영·기본 학습·실시간 비교·offline 재생·렌더·출판 진입점 |
| `configs/`, `requirements/`, lock 파일 | 공식 관절 매핑, 고정 보정, 환경·원본 commit 재현 |
| `docs/` | 원리·수식·수집·평가·실패 기록·현재 결과 영상과 그래프 |
| `tests/` | 현재 모델·제어·입력·촬영·보정·GeoRT 준비의 핵심 회귀 테스트 |
| `recordings/video_benchmark_002/` | 현재 MP4·원본 WebXR·시간 표식 |
| `recordings/quest_train_session_002.jsonl` | 선택한 GeoRT 모델의 원본 학습 입력 |
| `recordings/geort_train_session_001.jsonl` | 고정 보정 프로파일의 원본 입력 |
| `data/geort/quest_train_session_002/` | 학습에 사용한 canonical export와 provenance manifest |
| `results/geort_dg5f_workspace/` | 실제 로봇 asset·학습 run manifest·로봇 표본·FK·선택한 최종 checkpoint |
| `results/video_benchmark_002/replay_full/` | 원본 실제 상태·목표·명령·동일 입력 digest; 카메라 재렌더 가능 |
| `results/video_benchmark_002/alignment.json` | 현재 실제 손 영상의 SRC anchor |
| `results/phase3_tls/` | 현재 연결 인증서와 개인 키, Git 제외 |
| `.venv/`, `.venv-geort/` | 실행 환경. 절대경로가 포함되므로 옮기지 않음 |
| `external/`, `assets/` | 수정하지 않은 고정 원본과 재생성 모델 |

`manus_fixtures.py` 등 일부 작은 합성 fixture는 현재 회귀 테스트가 사용하므로 유지했다. `offline_benchmark.py`와 공개 데이터 adapter는 현재 공통 controller의 의존성이므로 유지했다. 원본 Git checkout은 수정하거나 이동하지 않았다.

## 외부로 옮긴 것

실제 보관 경로:

```text
/home/cocelo-server01/stkim_ws/Hand_teleoperation_other/archive_20261018/
  README_before_cleanup.md
  archive_manifest.json             파일별 SHA256·크기·기존 tracked 여부
  git_status_before_cleanup.txt
  metadata_before_video_relocation/ 원본 영상 경로 정리 전 metadata
  README_PHASE*.md                  과거 단계별 완료 당시 문서
  docs/                            과거 상세 진단·phase report·snapshot
  scripts/                         일회성 분석·좌표 검증·범위 실험
  tests/                           과거 phase·공개 데이터·범위 전용 검사
  results/                         이전 모델·중간 epoch·중복 렌더·진단 결과
  recordings/                      과거 평가·preflight·추적 입력
  data/                            과거 공개 데이터·다른 export
  .venv-data-audit/                 더 이상 사용하지 않는 공개 데이터 감사 환경
  tesollo_model-main/               공식 pinned checkout과 중복된 초기 모델 사본
```

**435개 이동 항목, 9,447개 파일, 8,274,626,711 bytes(약 8.27 GB)**를 보관했다. 이 수치는 환경 내 symlink의 대상 크기를 포함한 manifest 논리 크기다. 원본 녹화·checkpoint를 삭제하지 않았다. 실패한 GeoRT 제한 학습도 외부 보관했다.

원래 루트의 `com.oculus.vrshell-20261018-050834-0.mp4`는 현재 take 안의 `human.mp4`로 옮겼다. 영상 내용과 SHA256은 그대로다. alignment의 **경로 필드만** 바꾸고 이전 metadata도 보관했다. 공개 manifest에는 변경된 경로 metadata의 hash를 갱신했다. 로봇·모델·영상 프레임을 바꾼 작업이 아니다.

[프로젝트 공개 이동 요약](archive_manifest.json)에 각 원래 상대경로와 보관 경로·이유·tracked 파일 목록이 있다. 외부의 전체 manifest에는 개별 파일 SHA256을 추가 기록했다. 외부 보관 폴더는 프로젝트의 상위 Git 루트 밖에 있으므로 이 저장소에는 포함되지 않는다.

## 이전 실험 복구

필요한 항목을 전체 manifest에서 찾고 원래 상대경로로 복사한다. **현재 파일이 있으면 덮어쓰지 않는다.** 이전 실험이 여러 모듈·configs·결과를 함께 참조하면 관련 항목도 같이 복구해야 한다. 옛 phase snapshot은 완료 당시 소스·README에 대한 검사이므로 현재 트리에 그대로 실행하면 통과를 보장하지 않는다. 이번 정리로 hash를 덮어써 과거 검사를 통과시키지 않았다.

과거 상세 GeoRT 보고서는 보관 폴더의 `docs/GEORT_STACK_DIAGNOSIS.md`, `GEORT_FAILURE_DIAGNOSIS.md`, `GEORT_PARITY_RESULT.md`에 있다. 공개용 요약은 [GEORT_FAILURES.md](GEORT_FAILURES.md)에 통합했다.

## 정리 후 확인

- 현재 회귀 테스트: 92 passed, 1 skipped(분리 GeoRT 환경 검사).
- 분리 GeoRT runtime: 1 passed. 별도 실행해 SAPIEN·MuJoCo FK와 네트워크 구조 검사.
- 실제 현재 take의 1초를 네 방법으로 재생: 모두 완료, 소비 입력 digest 일치.
- 해당 actual 상태의 손바닥 재렌더: 수치·상태 파일 byte 일치.
- 과거 실험 폴더 없이 현재 108초 상태에서 분석 그래프 재생성.
- Ruff와 Markdown 로컬 링크 검사, 원본 8개 checkout clean 확인.

Git index의 SHA256은 이동 전후 같다. `git add/commit/push`는 실행하지 않았다. `git status`의 삭제 표시는 외부 보관으로 이동한 tracked 파일이며 실제 소실이 아니다. 원본 MP4도 tracked 위치에서 이동했으므로 루트 항목의 삭제가 보인다. 새 `recordings/` 경로는 ignore 대상이다. 현재 로컬 코드의 기본 GeoRT 경로는 공개 영상에 사용한 최종 모델로 맞췄으며, adapter 수식과 외부 소스는 바꾸지 않았다.
