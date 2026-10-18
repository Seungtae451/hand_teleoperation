# 환경 분리

기본 시뮬레이터는 루트 `pyproject.toml`·`uv.lock`으로 설치한다.

- `phase3.txt`: Quest HTTPS/WSS 서버.
- `phase5.txt`: AnyDex의 Pinocchio·NLopt numerical stack.
- `phase6.txt`: 위 stack과 Wuji 의존성.
- `phase7-torch.txt`, `phase7.txt`: 별도 `.venv-geort`의 Torch·SAPIEN·NumPy 1.x.
- `phase7-environment.lock.txt`: GeoRT 환경 전체 당시 버전.
- `figures.txt`: 문서 그림 재생성용 matplotlib.

번호는 설치 이력이며 현재 설치 순서와 명령은 [RUNNING.md](../docs/RUNNING.md)를 따른다. GeoRT 환경과 기본 NumPy 2.x 환경을 합치지 않는다.
