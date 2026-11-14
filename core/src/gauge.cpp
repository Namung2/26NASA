// C-30 게이지: 다음 경유지까지의 방위·거리·걷는 시간 (S3a §8)
#include "ctx.hpp"

bt_status bt_gauge_compute(const bt_ctx* c, bt_xy next_stop, const bt_path_metrics* leg, const bt_state* st, bt_gauge* out) {
  if (!c || !leg || !st || !out) return BT_ERR_ARG;
  const double dx = next_stop.x - st->pos.x, dy = next_stop.y - st->pos.y;   // 동쪽, 북쪽
  double b = std::atan2(dx, dy) * bt::RAD2DEG;                               // 0 = 북, 시계 방향
  if (b < 0) b += 360.0;
  if (b >= 360.0) b -= 360.0;
  out->bearing_deg = static_cast<float>(b);
  out->distance_m = leg->length_m;
  out->time_min = leg->time_min;
  return BT_OK;
}
