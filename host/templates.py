"""템플릿 문장 — 화면에 그대로 보일 글 (docs/spec/S3c §6.4, R-50).

프로그램이 문장을 만들어 스냅샷에 실어 보내고 화면은 그대로 표시한다. 화면은 문장을 짓지 않는다.

지키는 것
  · 슬롯에 들어가는 것은 와이어 모델의 필드뿐이다. 숫자는 코어가 표시 정밀도로 맞춰 준 값을 그대로 쓴다.
  · 권하는 말을 쓰지 않는다. 금지어: 추천, 권장, 최적, best, recommended, optimal, should (V-5가 검사한다).
    선택지는 나란히 보일 뿐이고 고르는 것은 사람이다.
  · 가설이 낀 옵션의 가치는 한 숫자가 아니라 "등급 (낮은 값~높은 값)"으로 쓴다.
"""
from __future__ import annotations

from . import wire as w

BANNED = ("추천", "권장", "최적", "best", "recommended", "optimal", "should")

LABEL = {"continue_plan": "계획 유지", "hyp_target": "가설 목표", "restore_plan": "이전 계획으로", "drop_last": "마지막 지점 빼기",
         "stay": "여기서 머물기", "return_rover": "로버로 귀환"}
GRADE = {"LOW": "낮음", "MED": "보통", "HIGH": "높음"}
RULE = {"strata_continuity": "층서 연속", "proximity": "근접 군집", "unit_boundary": "단위 경계", "erosion_exposure": "침식 노출"}
DIRECTION = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"]
CONFIDENCE = ["가능성 낮음", "반반", "가능성 높음"]
BINDING = {"sunset": "일몰", "eva_max": "EVA 최대 시간"}

HEADER = {
    ("fork", "route"): "갈림길입니다. 비슷한 경로가 둘 이상 있습니다.",
    ("fork", "obs"): "관측으로 지도가 바뀌었습니다.",
    ("fork", "hyp"): "가설로 지도가 바뀌었습니다.",
    ("env", "other"): "환경이 바뀌었습니다.",
    ("safety", "other"): "안전 임계에 닿았습니다.",
    ("user_request", "other"): "귀환을 요청했습니다.",
}
CAUSE = {"dust": "먼지가 경고 임계를 넘었습니다.", "shadow": "그림자 구간이 바뀌었습니다.", "sunset": "일몰까지 여유가 줄었습니다.",
         "nlt": "출발 한계에 닿았습니다. 로버로 돌아갈 시간입니다.", "spe": "태양 입자 경보입니다. 로버로 대피합니다."}
NOTICE = {
    "hyp_unreachable_within_nlt": "가설 목표는 출발 한계 안에 다녀올 수 없어 선택지에 없습니다.",
    "hyp_no_effect": "가설이 그 방향의 지도 값을 올리지 않아 가설 목표가 없습니다.",
    "no_feasible_return": "로버까지 가는 길을 찾지 못했습니다.",
    "bundle_mismatch": "기기와 로버의 지도 묶음이 다릅니다.",
    "options_paused": "선택지 정지 — 로버와 연결이 끊겨 새 선택지를 받지 못합니다.",
    "tau_warn": "먼지 광학 두께가 경고 임계를 넘었습니다.",
    "nlt_warn": "출발 한계가 가까워졌습니다.",
    "pos_warn": "위치 오차가 큽니다.",
    "late": "출발 한계를 이미 넘겼습니다.",
}


def approx_time(minutes: float) -> str:
    """걷는 시간의 표기: "약 N분 M초". 시간은 어림값이라 늘 '약'을 붙인다(2026-11-14 결정).

    코어가 10초 단위로 맞춰 준 값(config/params.yaml display_precision.time_min)을 분·초로 나눠 적을 뿐, 다시 계산하지 않는다.
    """
    m, sec = divmod(round(minutes * 60.0), 60)
    return f"약 {m}분 {sec}초" if sec else f"약 {m}분"


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
    late = f" 한계를 {-o.nlt_margin_min:.0f}분 넘김." if o.late else f" 출발까지 {o.nlt_margin_min:.0f}분."
    return (f"{o.id} {LABEL.get(o.label_key, o.label_key)}: {approx_time(o.time_min)}, 최대 경사 {o.max_slope_deg:.0f}°, 선량 {o.dose_uSv:.1f} µSv, "
            f"과학 가치 {value}, 정보 이득 {o.info_gain:.1f}, 통신 두절 {o.comm_loss_min:.0f}분.{late}")


def render_notice(key: str) -> str:
    return NOTICE.get(key, key)


def dp_text(dp: w.DecisionPoint) -> list[str]:
    """스냅샷의 dp_text: 머리 문장, 옵션마다 한 줄, 알림."""
    return [render_dp_header(dp)] + [render_option(o) for o in dp.options] + [render_notice(k) for k in dp.notices]


def hyp_readback(d: w.HypDraft, extent_levels: list[float]) -> str:
    """가설 확인 창의 되읽기 문장. 네 칸이 다 찼을 때만 문장이 된다."""
    if d.withdraw_hyp_id:
        return f"가설 {d.withdraw_hyp_id}을(를) 거둡니다. 지도가 이 가설이 없던 상태로 돌아갑니다."
    if d.missing or d.rule is None:
        return ""
    where = "" if d.rule == "proximity" else f"{DIRECTION[d.direction_idx]}쪽으로 "
    return f"{RULE[d.rule]} 가설: 여기서 {where}{extent_levels[d.extent_idx]:.0f} m까지, 확신은 '{CONFIDENCE[d.confidence_idx]}'."


def self_check() -> None:
    """문장 틀에 금지어가 없는지 본다(불러올 때 한 번)."""
    texts = list(LABEL.values()) + list(HEADER.values()) + list(CAUSE.values()) + list(NOTICE.values())
    for t in texts:
        for bad in BANNED:
            if bad in t.lower():
                raise ValueError(f"템플릿에 금지어 '{bad}': {t}")


self_check()
