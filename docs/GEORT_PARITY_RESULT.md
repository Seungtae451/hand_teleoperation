# 공개 Quest canonical parity 재학습 결과 — 2026-10-18

공개 데이터의 canonical X를 별도 adapter로 반전한 1k·3,498·10k 모델의 재학습을 완료했다.
모두 원본 GeoRT 200 epoch, seed 20261018, 동일 robot-only FK cache를 사용했다.
공식 데이터 모델과 이전 세 공개 데이터 모델은 보존했다. 원본 Git 코드는 수정하지 않았다.

**제공자 수집 코드가 없어 정확한 world 변환을 인증할 수 없다.** 사용자 양손 굽힘 관찰과
기하 진단에 근거한 명시적인 empirical parity 실험이다. 손목 quaternion은 임의로 바꾸지 않았고,
실시간 WebXR 입력에는 adapter를 적용하지 않는다.
근거와 재현은 [README_GEORT_PARITY.md](../README_GEORT_PARITY.md)를 참고한다.

## 완료한 검증

- 기존 train/validation/test episode 분할과 row ID·nested subset 보존.
- canonical X만 반전, Y/Z·단위·관절 간 거리·원본 입력 보존. 양손 표시 복사본 생성.
- 새 모델 각각 실제 0–199 epoch 로그·새 체크포인트 해시·8×20 유한 추론 확인.
- 동일 FK 및 robot-only 데이터 파일 해시 확인, 공식 모델 체크포인트 해시 유지.
- 네 모델의 recorded native packet 150개를 TLS/WebSocket으로 재생하여 MuJoCo 20관절 제어와
  tracking loss hold 통과. 실제 새 Quest 동작 시험이 아니라 headless 통합 검사다.
- 좌표/기존 검증 서버 테스트 5개 통과, 새 코드 Ruff 통과.
- 외부 저장소 8개 clean, 기존 Phase 7 이전 파일 96개 변경 없음.

## 동일 입력 진단

각 입력에서 동일한 균등 간격 512프레임을 모든 모델에 넣었다.
공개 validation은 고정 parity adapter를 적용한 좌표를 이전·새 모델 모두에 사용했다.
과거 실제 WebXR snapshot에는 반전하지 않았다. 해당 snapshot은 학습에 들어가지 않았다.
**test split은 점수 계산에 사용하지 않았다.**

아래 단위는 mm이며, 인간 wrist 기준 손끝과 로봇 palm 기준 FK 손끝의 평균 대응 거리다.
독립적인 정답 pose 오차나 공정한 알고리즘 최종 순위가 아니다. 제어기를 통과하기 전 모델 목표다.

| 학습 입력 | 공개 validation 이전 → 새 모델 | WebXR snapshot 이전 → 새 모델 |
|---|---:|---:|
| 공식 3,498 | 38.49 → 38.49 (동일 모델) | 46.61 → 46.61 (동일 모델) |
| 공개 1,000 | 93.39 → 40.31 | 98.98 → 62.94 |
| 공개 3,498 | 103.26 → 40.32 | 105.08 → 61.02 |
| 공개 10,000 | 105.08 → 40.00 | 107.05 → 52.71 |

좌표 불일치가 이전 공개 모델의 문제에 크게 기여했다는 근거다. 다만 공식 모델이 이 snapshot의
거리에서는 여전히 더 작고, 단일 seed·단일 과거 snapshot만으로 데이터 크기 효과를 일반화할 수 없다.
공개 validation 거리는 세 새 모델에서 거의 같다. 참가자 식별 정보가 없어 참가자 중복은 미검증이다.

잔여 문제도 남는다. 새 10k 모델의 WebXR 손가락별 평균 거리는 엄지 65.58, 검지 40.07,
중지 56.22, 약지 37.38, 새끼 64.29 mm다. 같은 28개 인간 pinch 기하 후보에서 로봇의 대응
손끝 간 평균 거리는 26.70 mm다. 접촉 성공을 검증한 것은 아니다.
원본 GeoRT의 목적함수와 로봇 형상 차이, 드문 동작 커버리지 및 공통 제어기의 속도 제한을
추가로 구분해서 봐야 한다. 이번 작업에서 loss·게인·보정 offset·속도 제한은 바꾸지 않았다.

## 산출물

- 모델 목록: `results/geort_data_size_parity_20261018/models.json`
- 입력/모델/소스 검사: 같은 폴더의 `dataset_verification.json`, `model_verification.json`,
  `source_integrity.json`
- 진단 전체 및 실제 모델 출력: 같은 폴더의 `parity_comparison.json`, `diagnostic_*.npz`
- 배포 이력 검사: `results/quest_coordinate_provenance_20261018/history_comparison.json`
- MuJoCo 통합 검사: `results/live-validation-3ak2venh/validation.json`
- 이전 모델: `results/geort_data_size_20261018/` — 기존 진단 재현용으로 보존.

후속 원인 분리: [GEORT_STACK_DIAGNOSIS.md](GEORT_STACK_DIAGNOSIS.md).
최근 실제 세션에서 정확 FK·신경망 FK·모델 목표·MuJoCo 추종·데이터 커버리지를 따로 검사했다.

공식 Allegro 대조 학습도 완료했다. 같은 개인 Quest 데이터에서 Allegro는 주먹 방향을 학습했고,
현재 DG-5F 개인 모델의 중지 역방향 반응은 Allegro에서 재현되지 않았다.
수치·제약·재현 명령은 [후속 대조 결과](GEORT_STACK_DIAGNOSIS.md#후속-공식-allegro-대조-실험-완료)를 참고한다.

요청한 DG-5F 비엄지 3·4번 관절 0~90° 학습 실험도 완료했다. 해당 역방향 출력은 차단되지만
펼침·주먹 대응은 해결되지 않았다. [범위 제한 대조 결과](GEORT_STACK_DIAGNOSIS.md#후속-dg-5f-학습-범위-제한-실험-완료)를 참고한다.
