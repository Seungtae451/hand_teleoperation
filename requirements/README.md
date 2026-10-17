# 환경 분리

Phase 1·2 의존성은 루트 `pyproject.toml`과 `uv.lock`에서 관리한다.
`uv sync --locked --python 3.10`으로 검증한 버전을 설치한다.

Quest Python SDK, AnyDex, Wuji, GeoRT는 아직 이 환경에 설치하지 않는다.
후속 Phase에서 검증한 adapter별 환경을 추가한다. 특히 스트리머 Unity 프로젝트의
Python 3.13 요구사항과 SDK의 Python 3.10 지원을 구분하고, GeoRT의 SAPIEN/CUDA
환경을 MuJoCo 실행 환경과 분리한다. 실제 선언은 `docs/REPOSITORY_AUDIT.md` 참조.
