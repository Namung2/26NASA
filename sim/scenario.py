"""시나리오 YAML의 모양 (docs/spec/S5 §4).

시나리오는 "언제 무슨 일이 생기는가"(events)와 "승무원이 카드를 어떻게 고르는가"(choices), 그리고 검증 시나리오라면
"무엇이 성립해야 하는가"(expect)를 적는다. 좌표는 적지 않는다 — 지점은 번들의 배치(P1, P2, P3, 주차점)를 이름으로 가리킨다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class At(_M):
    """이벤트가 일어나는 때. 한 가지 형태만 채운다."""
    t_min: float | None = None            # EVA 경과 분
    poi: str | None = None                # 그 지점에 도착한 뒤
    dwell_min: float = 0                  #   … dwell_min 분
    after_event: int | None = None        # 앞의 이벤트(1부터 셈)가 일어난 뒤
    delay_min: float = 0                  #   … delay_min 분


class ScenarioEvent(_M):
    at: At
    type: Literal["obs", "hyp", "link", "spe", "env", "sigma", "photo", "return"]
    payload: dict = {}


class ChoiceRule(_M):
    """승무원이 카드를 고르는 규칙. 옵션의 "성질"로 고른다(A·B·C 같은 이름표로 고르면 순서가 바뀔 때 깨진다)."""
    when: dict = {}                       # trigger, cause_event, forced 가운데 일부
    pick: dict                            # from_hypothesis | label_key | kind 가운데 하나
    delay_s: float = 0


class Start(_M):
    eva_elapsed_min: float = 0            # 시나리오가 시작할 때 이미 지난 EVA 시간
    pos: dict | list | None = None        # {poi: P1} 또는 [x, y]. 없으면 로버 주차점
    sigma_m: float = 0
    rover_park: str = "park1"


class Scenario(_M):
    scenario: str
    kind: Literal["V", "D"]
    site: str                             # 번들 id
    seed: int = 17
    nodes: list[str] = ["suit-A"]
    start: Start = Start()
    poi_plan: list[str]
    dwell_min: dict[str, float] = {}
    until_min: float | None = None        # 이 EVA 경과 분에 끝낸다(없으면 로버에 돌아오거나 8시간)
    events: list[ScenarioEvent] = []
    choices: list[ChoiceRule] = []
    expect: list[dict] = []
    timing: list[dict] = []


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(Path(path).read_text()))
