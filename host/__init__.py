"""두 프로그램(기기, 로버)이 함께 쓰는 Python 껍데기 코드 (docs/spec/S1 §2, S3b §0).

판단 로직은 여기에 두지 않는다. 경로·선택지·안전 판정·지도 갱신은 전부 C++ 코어(core/)의 일이고,
껍데기가 하는 일은 입출력(파일, 소켓), 문자열 보관, 구조체 변환뿐이다.

    btcore.py   코어 라이브러리 바인딩 (ctypes) — 구조체 미러, 함수 원형, numpy 배열 전달
    config.py   tiers.yaml·params.yaml → 코어 설정 구조체(bt_config)
    bundle.py   번들 읽기 — 배열을 메모리에 올려 코어에 연결
"""
