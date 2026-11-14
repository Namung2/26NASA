"""시뮬레이터 — 센서·환경·링크를 흉내 내고 시나리오를 돌린다 (docs/spec/S5).

기기 프로그램과 로버 프로그램의 본체 클래스(DeviceNode, RoverService)를 그대로 한 프로세스 안에서 돌린다.
소켓과 화면만 빠진 것이고, 코어와 노드 코드는 실제 프로그램과 같다.
    scenario.py  시나리오 YAML의 모양과 읽기
    sim.py       Sim — 틱 루프, 승무원의 움직임, 링크, 이벤트 주입, 기록
    expect.py    시나리오의 expect 항목을 기록에서 판정
    runner.py    시나리오 실행 → 판정 → 리포트
    scenarios/   V1(아폴로 17 Station 4의 구조), V2(연결 끊김), D1(데모)
"""
