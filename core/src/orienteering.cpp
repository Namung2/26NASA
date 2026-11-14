// C-21b 들를 지점과 순서 고르기 (S3a §3.1). 지점이 8개 이하라 모든 순서를 차례로 살핀다(재귀 없이 다음 순열로 넘어가며)
#include "ctx.hpp"

using namespace bt;

namespace {

constexpr uint32_t N_MAX = BT_MAX_STOPS;

// 다음 순열(사전순). 마지막이면 false
bool next_perm(uint8_t* p, uint32_t n) {
  if (n < 2) return false;
  int32_t i = static_cast<int32_t>(n) - 2;
  while (i >= 0 && p[i] >= p[i + 1]) i -= 1;        // 상한: n
  if (i < 0) return false;
  int32_t j = static_cast<int32_t>(n) - 1;
  while (p[j] <= p[i]) j -= 1;                      // 상한: n
  const uint8_t t = p[i]; p[i] = p[j]; p[j] = t;
  for (int32_t a = i + 1, b = static_cast<int32_t>(n) - 1; a < b; ++a, --b) { const uint8_t u = p[a]; p[a] = p[b]; p[b] = u; }
  return true;
}

}  // namespace

bt_status bt_select_pois(bt_ctx* c, const bt_stop* pois, uint32_t n, bt_xy start, bt_xy end,
                         const bt_budget* budget, bt_stop* out, uint32_t* out_n) {
  if (!c || !budget || !out_n || (!pois && n > 0) || (!out && n > 0)) return BT_ERR_ARG;
  *out_n = 0;
  if (n > N_MAX) return BT_ERR_CAPACITY;
  if (!c->cm.built || !c->s.g) return BT_ERR_NOT_READY;
  if (n == 0) return BT_OK;

  // 지점 사이의 걷는 시간(초). 0 = 출발, 1..n = 지점, n+1 = 도착. 경사 때문에 가는 길과 오는 길의 시간이 다르다
  double T[N_MAX + 2][N_MAX + 2];
  bt_xy node[N_MAX + 2];
  node[0] = start;
  for (uint32_t k = 0; k < n; ++k) node[k + 1] = pois[k].xy;
  node[n + 1] = end;
  bt_budget leg = *budget;
  leg.time_s = 0.0;                                  // 구간 하나에는 시간 상한을 걸지 않는다
  bt_state dummy;
  std::memset(&dummy, 0, sizeof(dummy));
  bt_path p;
  for (uint32_t i = 0; i < n + 2; ++i) {
    for (uint32_t j = 0; j < n + 2; ++j) T[i][j] = (i == j) ? 0.0 : D_INF;
  }
  for (uint32_t i = 0; i < n + 2; ++i) {
    for (uint32_t j = i + 1; j < n + 2; ++j) {
      if (i == 0 && j == n + 1) continue;            // 출발 → 도착 직행은 쓰지 않는다
      std::memset(&p, 0, sizeof(p));
      p.cells = c->dec.alt;                          // 갈림길 검사용 버퍼를 빌려 쓴다
      p.cap = c->dec.alt_per * BT_MAX_PROFILES;
      const bt_status st = plan_ex(c, node[i], node[j], &leg, &p, true);
      if (st == BT_ERR_CAPACITY) return st;
      if (st < 0 || !path_reaches(c, &p, node[j])) continue;   // 길이 없거나 그 지점까지 닿지 못했다
      bt_path_metrics m;
      if (bt_path_measure(c, &p, &dummy, BT_WALK_PLAN, &m) != BT_OK) continue;
      T[i][j] = static_cast<double>(m.time_min) * 60.0;
      for (uint32_t a = 0, b = p.len - 1; a < b; ++a, --b) { const bt_cell t = p.cells[a]; p.cells[a] = p.cells[b]; p.cells[b] = t; }   // 같은 길을 거꾸로
      if (bt_path_measure(c, &p, &dummy, BT_WALK_PLAN, &m) == BT_OK) T[j][i] = static_cast<double>(m.time_min) * 60.0;
    }
  }

  // 지점의 가치: 그 자리의 과학 가치(기대값). 지도가 아직 없으면 전부 1(= 많이 들르는 쪽)
  double value[N_MAX];
  for (uint32_t k = 0; k < n; ++k) {
    bt_path_value pv;
    value[k] = (c->sci.ready && bt_path_evaluate(c, nullptr, &pois[k], 1, &pv) == BT_OK) ? static_cast<double>(pv.value_mean) : 1.0;
  }

  const double limit = budget->time_s > 0 ? budget->time_s : D_INF;
  uint8_t perm[N_MAX], best[N_MAX];
  for (uint32_t k = 0; k < n; ++k) perm[k] = static_cast<uint8_t>(k);
  uint32_t best_len = 0;
  double best_value = -1.0, best_time = D_INF;
  for (uint32_t guard = 0; guard < 40320u; ++guard) {            // 상한: 8! 가지
    double t = 0.0, v = 0.0;
    uint32_t prev = 0;
    for (uint32_t m = 0; m < n; ++m) {                           // 앞에서부터 들를 수 있는 데까지
      const uint32_t k = perm[m];
      t += T[prev][k + 1] + static_cast<double>(pois[k].dwell_min) * 60.0;
      if (!(t < D_INF)) break;
      v += value[k];
      prev = k + 1;
      const double total = t + T[prev][n + 1];
      if (!(total <= limit)) continue;                           // 여기서 끝내면 시간을 넘긴다 — 더 들르면 더 넘기지만 순열마다 다르니 계속 본다
      if (v > best_value + 1e-9 || (v > best_value - 1e-9 && total < best_time - 1e-9)) {
        best_value = v; best_time = total; best_len = m + 1;
        for (uint32_t q = 0; q <= m; ++q) best[q] = perm[q];
      }
    }
    if (!next_perm(perm, n)) break;
  }
  for (uint32_t q = 0; q < best_len; ++q) out[q] = pois[best[q]];
  *out_n = best_len;
  return BT_OK;
}
