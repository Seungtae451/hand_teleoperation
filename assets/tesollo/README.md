# Tesollo 파생 모델

`generated/`는 `python -m benchmark build`가 생성하는 재현 가능한 출력이다.
원본은 `external/tesollo_model/dg5f/`에 있고 변경하지 않는다.

- `dg5f_right.xml`: actuator, site, scene을 추가한 MuJoCo 모델
- `dg5f_right.normalized.urdf`: 메시 URI와 시각 형식을 처리한 별도 import 입력
- `dg5f_right.provenance.json`: 원본 commit, 입력 해시, 설정, 변환 내역
- `meshes/`: 공식 collision STL 28개
- `TESOLLO_LICENSE`: 공식 BSD-3-Clause 라이선스

생성된 폴더 전체를 옮기면 MJCF와 normalized URDF를 다시 로드할 수 있다.
손끝 위치는 공식 `rl_dg_[1-5]_tip` 링크 원점이며 접촉 패드 표면 중심이 아니다.
상세한 정의와 동역학 설정은 `docs/ROBOT_MODEL.md`를 참조한다.
