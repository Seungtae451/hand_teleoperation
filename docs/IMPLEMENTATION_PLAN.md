# Phase 1·2 구현 전 점검한 계획

점검일: 2026-10-17, Asia/Seoul. 기준 문서: 루트 `PROJECT_SPEC.md`.

## 범위와 원본 변경 정책

첫 산출물은 공식 DG-5F 오른손 20-DoF 시뮬레이터다. 기존 모델·명세 파일을 덮어쓰지 않고
외부 GitHub 소스는 고정 commit에서 읽기 전용으로 사용한다. 원본 수정이 필요할 경우에는
변경 이유, 대상 파일, adapter로 해결할 수 없는 이유를 먼저 설명하고 사용자 확인을 받는다.
이번 구현은 원본 수정 없이 프로젝트 소유의 새 모듈과 파생 산출물로 처리할 수 있다고 판단했다.

## 사전 조사로 확인한 결정

1. ROS가 없는 Ubuntu/Python 3.10 환경이므로 Phase 2는 ROS 없이 MuJoCo Python에서 실행한다.
2. 공식 모델은 xacro 확장 없이 읽을 수 있는 URDF다. 오른손 20개 revolute와 7개 fixed joint,
   28개 link, mimic 없음, 실제 fingertip 링크 5개를 확인했다.
3. 관절 순서는 설정 파일에 명시하고 URDF 실제 관절 집합과 일치하는지 검증한다.
   MuJoCo/Pinocchio의 내부 인덱스에 의존하지 않는다.
4. URDF의 DAE visual은 MuJoCo 직접 로드 대상이 아니므로 별도 import 입력에서 제외하고
   제공된 공식 STL collision geometry를 렌더링에 재사용한다. 원본 URDF는 유지한다.
5. fixed link를 보존해 palm과 fingertip 좌표를 실제 URDF frame으로 계산한다.
6. 실제 actuator 구동과 별도 MjData를 사용하는 기구학 평가를 분리한다.
7. Phase 2 수용 검증은 중력 보상·접촉 비활성의 자유 운동으로 범위를 명시한다.
   접촉/파지 성능은 검증 범위에 포함하지 않는다.

## 작업 순서와 수용 조건

| 순서 | 구현 | 통과 기준 |
|---|---|---|
| 1 | 저장소 확보 및 실제 소스 분석 | 필수 7개와 발견한 Python SDK의 commit·라이선스·의존성 기록 |
| 2 | 프로젝트 패키지·가상환경·lock | `uv sync --locked`로 실행 환경 재현 |
| 3 | 별도 URDF 변환기 | 원본 해시 유지, portable MJCF bundle, 20/20/20 nq/nv/nu |
| 4 | 20 position actuator·입력 검증 | 개별 관절·동시 구동 수렴, 비정상 입력 거부, 제한 적용 |
| 5 | tip site·FK·Jacobian | 독립 NumPy URDF chain 및 유한차분과 일치 |
| 6 | Viewer·영상·로그·재생 | 실제 렌더 픽셀/움직임 확인, 종료 정상, 재생 actual state 일치 |
| 7 | 문서·실측 보고서 | 실행 명령, 좌표계, 제한사항, 다음 Phase 명시 |

## 후속 연결 설계

`HandFrame`은 스트리머 실제 21-point layout, 미제공 관절 회전(None), source frame 및
timestamp domain을 명시한다. Phase 3에서 SDK 수신·좌표 변환·timeout 기반 tracking validity와
입력 recorder/replay를 추가한다. `BaseRetargeter`에는 reset과 독립 retarget 진입점을 두고
MANUS, AnyDex, Wuji, GeoRT는 동등한 네 모듈로 등록한다. Phase 1·2에서는 알고리즘을
간이 구현으로 대체하지 않으며 실제 adapter는 순서대로 Phase 4~7에서 추가한다.

## 점검 후 구현 중 보완한 사항

- 실제 qpos의 경계 초과/수치 오차를 target clipping과 구별하는 FK 옵션을 추가했다.
- MuJoCo passive Viewer의 비동기 close 후 렌더 스레드를 기다리는 실행 래퍼를 추가했다.
  설치된 MuJoCo 소스와 외부 저장소 소스는 수정하지 않았다.
- 파생 MJCF/메시 자체의 해시도 검사하여 잘못 수정된 bundle로 결과를 재생하지 않게 했다.
