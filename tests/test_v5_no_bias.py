"""V-5 편향 억제 (docs/spec/S7 §2 V-5, R-52).

도구는 선택지를 나란히 보일 뿐 고르지 않는다. 그 약속이 자료 구조와 문장에 새지 않았는지 본다:
추천·순위·점수를 뜻하는 필드가 없고, 옵션은 만들어진 순서 그대로이며(정렬 안 함), 문장에 금지어가 없다.
화면 쪽 검사(카드가 같은 모양인지, 처음부터 골라진 카드가 없는지)는 screen/의 vitest 시험이 맡는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pydantic
import pytest

from host import convert as cv
from host import templates as tp
from host import wire as w
from tests.fixtures import mini_bundle as mb
from tests.helpers import base_passable, random_passable_xy
from tests.scene import Scene

ROOT = Path(__file__).resolve().parents[1]
BANNED_FIELD_PARTS = ("recommend", "default", "selected", "score", "rank", "best", "priority")
BANNED_WORDS = ("추천", "권장", "최적", "best", "recommended", "optimal", "should")


def _struct_fields(header: str, name: str) -> list[str]:
    """btcore.h에서 구조체 하나의 필드 이름들."""
    text = re.sub(r"/\*.*?\*/", "", header, flags=re.DOTALL)
    end = text.index("} " + name + ";")
    body = text[text.rindex("typedef struct {", 0, end) + len("typedef struct {"):end]
    names = []
    for decl in body.split(";"):
        decl = decl.strip()
        if not decl:
            continue
        first, *rest = decl.split(",")
        names.append(re.sub(r"\[.*?\]", "", first).split()[-1].lstrip("*"))
        names += [re.sub(r"\[.*?\]", "", r).strip().lstrip("*") for r in rest]
    return names


def test_v5_no_recommendation_fields():
    header = (ROOT / "core/include/btcore.h").read_text()
    core_fields = _struct_fields(header, "bt_option") + _struct_fields(header, "bt_decision")
    assert {"label", "kind", "time_min", "value_mean", "nlt_margin_min"} <= set(core_fields)      # 구조체를 제대로 읽었는지
    wire_fields = list(w.Option.model_fields) + list(w.DecisionPoint.model_fields)
    for f in core_fields + wire_fields:
        assert not any(p in f.lower() for p in BANNED_FIELD_PARTS), f
    # 와이어 모델은 정의하지 않은 필드를 받지 않는다 — 누가 "recommended" 같은 것을 슬쩍 실어 보낼 수 없다
    for model in (w.Option, w.DecisionPoint):
        assert model.model_config.get("extra") == "forbid"
    s = Scene()
    o = s.obs()
    dp = cv.decision_from_bt(s.core, s.decide(cause="obs", event=o), ["P1", "P2", "P3"])
    with pytest.raises(pydantic.ValidationError):
        w.Option.model_validate({**dp.options[0].model_dump(), "recommended": True})
    with pytest.raises(pydantic.ValidationError):
        w.DecisionPoint.model_validate({**dp.model_dump(), "best_option": "A"})


def test_v5_initial_sort_is_unsorted(seeded):
    """결정 지점 100개: 정렬 기준은 늘 "정렬 안 함"이고, 옵션의 이름표(A, B, C)는 만들어진 순서다.
    만들어지는 순서는 고정이다: 계획 유지 → 가설 목표 → 이전 계획으로 → 마지막 지점 빼기 → 머물기 → 귀환."""
    s = Scene()
    ok = base_passable(s.bundle, s.core.cfg.theta_max_deg)
    o = s.obs()
    h = s.hyp()
    n = 0
    for i in range(100):
        xy = random_passable_xy(seeded, ok, s.bundle.res_m)
        plan = seeded.choice((("P2", "P3"), ("P2",), ("P3", "P1"), ()))
        t = seeded.uniform(600.0, 7.5 * 3600.0)
        d = s.decide(xy, plan, cause="hyp" if i % 2 else "obs", event=h if i % 2 else o, t=t)
        if d.n_options == 0:
            continue                                   # 갇힌 자리 등 — 낼 것이 없다
        opts = s.options(d)
        assert [x.label for x in opts] == list(range(len(opts)))
        assert [x.label_key for x in opts] == sorted(x.label_key for x in opts)
        dp = cv.decision_from_bt(s.core, d, ["P1", "P2", "P3"])
        assert dp.sort_key == "unsorted" and [x.id for x in dp.options] == list("ABC"[: len(opts)])
        s.core.decision_close(d.seq)
        n += 1
    assert n >= 60
    assert mb.POIS                                     # (지형 모듈을 쓰는 시험임을 드러낸다)


def test_v5_templates_clean():
    tp.self_check()                                    # 템플릿 모듈이 스스로 하는 금지어 검사
    texts: list[str] = []
    for name in ("LABEL", "GRADE", "RULE", "DIRECTION", "CONFIDENCE", "BINDING", "HEADER", "CAUSE", "NOTICE"):
        table = getattr(tp, name)
        texts += [str(v) for v in (table.values() if isinstance(table, dict) else table)]
    s = Scene()
    s.obs()
    h = s.hyp()
    dp = cv.decision_from_bt(s.core, s.decide(cause="hyp", event=h), ["P1", "P2", "P3"])
    texts += tp.dp_text(dp)                            # 실제 결정 지점으로 만든 문장
    draft = w.HypDraft(rule="strata_continuity", direction_idx=4, extent_idx=1, confidence_idx=1)
    texts.append(tp.hyp_readback(draft, [100, 300, 1000]))
    assert len(texts) > 30
    for t in texts:
        assert not any(b in t.lower() for b in BANNED_WORDS), t
    # 가설이 낀 옵션은 가치를 한 숫자가 아니라 등급 + 범위로 쓴다
    hyp_line = next(line for line, o in zip(tp.dp_text(dp)[1:], dp.options, strict=False) if o.from_hypothesis)
    assert "~" in hyp_line
