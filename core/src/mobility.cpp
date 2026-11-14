// 보행 모델: 진행 방향의 경사 → 속도 (S3a §2, REFERENCE §4)
#include "ctx.hpp"

namespace bt {

// 평지 속도에 곱하는 배율. slope_deg = 진행 방향의 경사 (오르막 +, 내리막 -)
//  θ ≥ -10° : 1 - θ/75        (v = 0.75 - 0.01·θ m/s 를 평지 0.75로 나눈 것 — NASA ICES-2025-129 식 (2))
//  θ < -10° : -10°의 배율에서 1°마다 9.5 %씩 줄인다 (SEXTANT 속도 표의 급한 내리막 기울기)
double slope_factor(double th) {
  double f;
  if (th >= -10.0) {
    f = 1.0 - th / 75.0;
  } else {
    f = (1.0 + 10.0 / 75.0) * (1.0 - 0.095 * (-10.0 - th));
  }
  // 0으로 나누지 않게 하는 바닥. 통과 가능한 경사(±20°) 안에서는 닿지 않는다
  if (!(f > 0.05)) f = 0.05;
  return f;
}

double walk_mps(const bt_config& cfg, double slope_deg, int mode) {
  const double v0 = static_cast<double>(mode == BT_WALK_RETURN ? cfg.v_return_kmh : cfg.v_plan_kmh) / 3.6;
  return v0 * slope_factor(slope_deg);
}

}  // namespace bt

double bt_speed_mps(const bt_ctx* c, double slope_deg, bt_walk_mode mode) {
  if (!c) return 0.0;
  return bt::walk_mps(c->cfg, slope_deg, static_cast<int>(mode));
}
