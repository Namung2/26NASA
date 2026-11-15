# syntax=docker/dockerfile:1
# BingoTime — 서버 하나를 컨테이너 하나에 담는다. 주소도 하나다:
#   화면(screen/dist) + 실시간 서버(sim/live.py) + 코어(libbtcore.so) + 지도 번들(data/bundles) 이 한 프로세스로 뜬다.
#
#   docker build -t bingotime .
#   docker run --rm -p 8000:8000 bingotime          →  http://localhost:8000/
#
# 세 단계로 만든다. 앞의 두 단계는 만드는 도구(Node, 컴파일러)만 쓰고 버린다 — 마지막 이미지에는 결과물만 들어간다.

# ── 1. 화면 빌드 (Node) ──────────────────────────────────────────────────────────────────────────────
FROM node:20-bookworm-slim AS screen
WORKDIR /src/screen
COPY screen/package.json screen/package-lock.json ./
RUN npm ci
COPY screen/ ./
RUN npm run build

# ── 2. 코어 빌드 (C++17) ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS core
RUN apt-get update && apt-get install -y --no-install-recommends g++ make && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "cmake>=4"
WORKDIR /src
COPY CMakeLists.txt CMakePresets.json ./
COPY core/ core/
# 자체 시험까지 돌린다 — 리눅스에서 코어가 맥과 같은 답을 내지 않으면 이미지를 만들지 않는다
RUN cmake --preset native && cmake --build --preset native && ./build/native/bt_selftest

# ── 3. 실행 이미지 ──────────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm
# libexpat1: rasterio(로버 쪽이 번들의 래스터를 읽는 데 쓴다)가 실행할 때 찾는 시스템 라이브러리. slim 이미지에는 없다
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libexpat1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# 파이썬 의존성: pyproject.toml의 목록을 그대로 쓴다(목록을 두 군데에 적지 않으려고)
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt
COPY config/ config/
COPY host/ host/
COPY device/ device/
COPY rover/ rover/
COPY sim/ sim/
COPY --from=core /src/build/native/libbtcore.so build/native/libbtcore.so
COPY --from=screen /src/screen/dist screen/dist
# 지도 번들: 저장소의 release/*.zip을 만드는 동안에만 붙여서 풀고, zip 자체는 이미지에 넣지 않는다(크기와 SHA-256은 host/fetch.py가 확인한다)
RUN --mount=type=bind,source=release,target=/app/release python -m host.fetch --all
# 호스팅 서비스가 PORT를 정해 주면 그 번호로 듣는다. 없으면 8000
# BT_PHOTO_LIMIT: 공개 주소에서는 아무나 사진을 올릴 수 있으므로 한 번의 실행에 5장까지만 받는다(sim/live.py의 PHOTO_LIMIT)
ENV PORT=8000 PYTHONUNBUFFERED=1 BT_PHOTO_LIMIT=5
EXPOSE 8000
CMD ["sh", "-c", "exec python -m sim.live --host 0.0.0.0 --port ${PORT} --scenario D1_demo --speed 10"]
