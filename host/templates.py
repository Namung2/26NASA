"""템플릿 문장 — 화면에 그대로 보일 글 (docs/spec/S3c §6.4, R-50).

프로그램이 문장을 만들어 스냅샷에 실어 보내고 화면은 그대로 표시한다. 화면은 문장을 짓지 않는다.

지키는 것
  · 슬롯에 들어가는 것은 와이어 모델의 필드뿐이다. 숫자는 코어가 표시 정밀도로 맞춰 준 값을 그대로 쓴다.
  · 권하는 말을 쓰지 않는다. 금지어: 추천, 권장, 최적, best, recommended, optimal, should (V-5가 검사한다).
    선택지는 나란히 보일 뿐이고 고르는 것은 사람이다.
  · 가설이 낀 옵션의 가치는 한 숫자가 아니라 "등급 (낮은 값~높은 값)"으로 쓴다.
  · 문장은 영어다(2026-11-14, 화면 전체를 영어로 바꾸며). 낱말은 화면의 screen/src/shared/i18n.ts와 맞춘다.
"""
from __future__ import annotations

from . import wire as w

BANNED = ("추천", "권장", "최적", "best", "recommended", "optimal", "should")

LABEL = {"continue_plan": "Keep plan", "hyp_target": "Hypothesis target", "restore_plan": "Back to earlier plan", "drop_last": "Drop last stop",
         "stay": "Stay here", "return_rover": "Return to rover"}
GRADE = {"LOW": "Low", "MED": "Medium", "HIGH": "High"}
RULE = {"strata_continuity": "Strata continuity", "proximity": "Proximity cluster", "unit_boundary": "Unit boundary", "erosion_exposure": "Erosion exposure"}
DIRECTION = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
CONFIDENCE = ["Unlikely", "About even", "Likely"]
BINDING = {"sunset": "Sunset", "eva_max": "EVA max time"}

HEADER = {
    ("fork", "route"): "Fork in the route. Two or more similar routes exist.",
    ("fork", "obs"): "An observation changed the map.",
    ("fork", "hyp"): "A hypothesis changed the map.",
    ("env", "other"): "The environment changed.",
    ("safety", "other"): "A safety threshold was reached.",
    ("user_request", "other"): "Return was requested.",
}
CAUSE = {"dust": "Dust passed the warning threshold.", "shadow": "The shadow time bin changed.", "sunset": "The margin to sunset shrank.",
         "nlt": "The departure limit was reached. Time to return to the rover.", "spe": "Solar particle alert. Take shelter in the rover."}
NOTICE = {
    "hyp_unreachable_within_nlt": "The hypothesis target cannot be visited within the departure limit, so it is not among the options.",
    "hyp_no_effect": "The hypothesis did not raise map values in that direction, so there is no hypothesis target.",
    "no_feasible_return": "No route to the rover was found.",
    "bundle_mismatch": "The device and the rover hold different map bundles.",
    "options_paused": "Options paused — the rover link is down, so no new options can arrive.",
    "tau_warn": "Dust optical depth passed the warning threshold.",
    "nlt_warn": "The departure limit is near.",
    "pos_warn": "Position error is large.",
    "late": "The departure limit has already passed.",
}


def approx_time(minutes: float) -> str:
    """걷는 시간의 표기: "about N min M s". 시간은 어림값이라 늘 about을 붙인다(2026-11-14 결정. 그때는 한글 '약'이었고 영어로 바꾸며 about이 됐다).

    코어가 10초 단위로 맞춰 준 값(config/params.yaml display_precision.time_min)을 분·초로 나눠 적을 뿐, 다시 계산하지 않는다.
    """
    m, sec = divmod(round(minutes * 60.0), 60)
    return f"about {m} min {sec} s" if sec else f"about {m} min"


def confidence_name(p: float) -> str:
    """확신(0~1) → 메뉴의 세 이름. 구간은 0~33 % / 33~66 % / 66~100 % (S3c §7, IPCC 가능성 척도)."""
    return CONFIDENCE[0 if p < 1.0 / 3.0 else (1 if p < 2.0 / 3.0 else 2)]


def render_dp_header(dp: w.DecisionPoint) -> str:
    """이 카드 묶음이 왜 떴는지 한 문장."""
    if dp.cause in CAUSE:
        return CAUSE[dp.cause]
    return HEADER.get((dp.trigger, dp.cause_kind), HEADER.get((dp.trigger, "other"), ""))


def render_option(o: w.Option) -> str:
    """옵션 하나를 한 줄로. 모든 옵션이 같은 틀이다(순서·강조가 없다)."""
    if o.from_hypothesis:
        value = f"{GRADE[o.value_grade]} ({o.value_lo:.1f}~{o.value_hi:.1f})"
    else:
        value = f"{GRADE[o.value_grade]} ({o.value_mean:.1f})"
    late = f" {-o.nlt_margin_min:.0f} min past the limit." if o.late else f" {o.nlt_margin_min:.0f} min to departure."
    return (f"{o.id} {LABEL.get(o.label_key, o.label_key)}: {approx_time(o.time_min)}, max slope {o.max_slope_deg:.0f}°, dose {o.dose_uSv:.1f} µSv, "
            f"science value {value}, info gain {o.info_gain:.1f}, comm loss {o.comm_loss_min:.0f} min.{late}")


def render_notice(key: str) -> str:
    return NOTICE.get(key, key)


def dp_text(dp: w.DecisionPoint) -> list[str]:
    """스냅샷의 dp_text: 머리 문장, 옵션마다 한 줄, 알림."""
    return [render_dp_header(dp)] + [render_option(o) for o in dp.options] + [render_notice(k) for k in dp.notices]


def hyp_readback(d: w.HypDraft, extent_levels: list[float]) -> str:
    """가설 확인 창의 되읽기 문장. 네 칸이 다 찼을 때만 문장이 된다."""
    if d.withdraw_hyp_id:
        return f"Withdraw hypothesis {d.withdraw_hyp_id}. The map goes back to how it was without this hypothesis."
    if d.missing or d.rule is None:
        return ""
    where = "" if d.rule == "proximity" else f"toward the {DIRECTION[d.direction_idx]}, "
    return f"{RULE[d.rule]} hypothesis: from the anchor point, {where}out to {extent_levels[d.extent_idx]:.0f} m, confidence '{CONFIDENCE[d.confidence_idx]}'."


def self_check() -> None:
    """문장 틀에 금지어가 없는지 본다(불러올 때 한 번)."""
    texts = list(LABEL.values()) + list(HEADER.values()) + list(CAUSE.values()) + list(NOTICE.values())
    for t in texts:
        for bad in BANNED:
            if bad in t.lower():
                raise ValueError(f"템플릿에 금지어 '{bad}': {t}")


self_check()
