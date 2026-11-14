// 격자: 좌표 ↔ 칸, 방향 번호, 래스터 읽기
#pragma once
#include "btcore.h"
#include <cmath>
#include <cstdint>

namespace bt {

// 방향 번호: 0 북, 1 북동, 2 동, 3 남동, 4 남, 5 남서, 6 서, 7 북서 (row 0 = 북)
constexpr int DR[8] = {-1, -1, 0, 1, 1, 1, 0, -1};
constexpr int DC[8] = {0, 1, 1, 1, 0, -1, -1, -1};
constexpr double SQRT2 = 1.4142135623730951;
constexpr double RAD2DEG = 57.29577951308232;
constexpr double PI = 3.141592653589793;
constexpr float F_INF = __builtin_huge_valf();
constexpr double D_INF = __builtin_huge_val();

struct Geom { double ox, oy, res; uint32_t h, w; };

inline bool xy_to_cell(const Geom& g, bt_xy p, int32_t* row, int32_t* col) {
  if (!(p.x == p.x) || !(p.y == p.y)) return false;
  const double c = std::floor((p.x - g.ox) / g.res);
  const double r = std::floor((g.oy - p.y) / g.res);
  if (c < 0 || r < 0 || c >= static_cast<double>(g.w) || r >= static_cast<double>(g.h)) return false;
  *row = static_cast<int32_t>(r);
  *col = static_cast<int32_t>(c);
  return true;
}
inline bt_xy cell_center(const Geom& g, int32_t row, int32_t col) {
  bt_xy p;
  p.x = g.ox + (static_cast<double>(col) + 0.5) * g.res;
  p.y = g.oy - (static_cast<double>(row) + 0.5) * g.res;
  return p;
}
inline Geom geom_of(const bt_raster& r) { return Geom{r.origin.x, r.origin.y, static_cast<double>(r.res_m), r.h, r.w}; }
inline Geom geom_of(const bt_grid_geom& g) { return Geom{g.origin.x, g.origin.y, static_cast<double>(g.res_m), g.h, g.w}; }

// 래스터 한 칸 읽기 (값 없음 = NaN)
inline float raster_f(const bt_raster& r, uint64_t i) {
  if (r.dtype == BT_DT_F32) return static_cast<const float*>(r.data)[i];
  if (r.dtype == BT_DT_U16) {
    const uint16_t v = static_cast<const uint16_t*>(r.data)[i];
    if (v == BT_U16_NODATA) return __builtin_nanf("");
    return static_cast<float>(v) * r.scale + r.offset;
  }
  if (r.dtype == BT_DT_U8) return static_cast<float>(static_cast<const uint8_t*>(r.data)[i]);
  return __builtin_nanf("");
}
inline uint64_t plane_bytes(const bt_raster& r) { return (static_cast<uint64_t>(r.h) * r.w + 7) / 8; }
inline uint8_t raster_bit(const bt_raster& r, uint32_t plane, uint64_t i) {
  const uint8_t* p = static_cast<const uint8_t*>(r.data) + plane_bytes(r) * plane;
  return static_cast<uint8_t>((p[i >> 3] >> (7 - (i & 7))) & 1u);
}
inline uint64_t raster_bytes(const bt_raster& r) {
  const uint64_t n = static_cast<uint64_t>(r.h) * r.w;
  const uint64_t planes = r.planes ? r.planes : 1;
  if (r.dtype == BT_DT_F32) return n * 4 * planes;
  if (r.dtype == BT_DT_U16) return n * 2 * planes;
  if (r.dtype == BT_DT_U8) return n * planes;
  return plane_bytes(r) * planes;
}

}  // namespace bt
