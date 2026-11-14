"""C-10 지상 사전 계산 — 받은 원천 자료로 번들을 만든다 (docs/spec/S3a §1, S1 §5).

지구에서 미리 도는 오프라인 작업이다. 비행 하드웨어에 올라가지 않으므로 코어의 규칙(할당 금지 등)을 받지 않는다.

    python -m pipeline.build --site config/site.yaml --out data/bundles/jezero_west_v1

단계와 파일
    dtm.py       C-10a  고도 자료를 활동 구역의 로컬 격자로 다시 놓는다
    terrain.py   C-10b  경사, 거칠기, 그림자, 가시선
    suntable.py         태양 고도·방위 표 (NASA GISS Mars24 계산 절차)
    layers.py    C-10c  광물 지도, 지질 단위를 과학 격자에 맞춘다
    prior.py     C-10e  과학 가치 바탕 지도 (지질 단위 × 광물 표)
    poi.py       C-10f  지점 목록
    bundle.py    C-10g  파일 쓰기, 메타, 해시, 크기 검사
    build.py            위 단계를 차례로 부르는 진입점

고도 자료 하나만 있어도 끝까지 돈다. 광물·지질 자료가 없으면 그 항을 건너뛰고 메타의 missing_layers에 적는다.
"""
