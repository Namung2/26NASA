// C-37 이벤트 로그: 고정 용량, lamport 순서, 병합 (S3a §4). 문자열은 다루지 않는다
#include "ctx.hpp"

using namespace bt;

namespace {

inline bool key_less(uint32_t lts_a, uint8_t node_a, uint32_t lts_b, uint8_t node_b) {
  if (lts_a != lts_b) return lts_a < lts_b;
  return node_a < node_b;
}

// (lts, node)가 들어갈 자리. 이미 있으면 *exists = true
uint32_t find_slot(const bt_ctx* c, uint32_t lts, uint8_t node, bool* exists) {
  uint32_t lo = 0, hi = c->log_n;
  while (lo < hi) {                                 // 상한: log2(용량)
    const uint32_t mid = lo + (hi - lo) / 2;
    if (key_less(c->log[mid].lts, c->log[mid].node, lts, node)) lo = mid + 1; else hi = mid;
  }
  *exists = (lo < c->log_n && c->log[lo].lts == lts && c->log[lo].node == node);
  return lo;
}

bt_status insert_at(bt_ctx* c, uint32_t at, const bt_event& ev) {
  if (c->log_n >= BT_MAX_EVENTS) return BT_ERR_CAPACITY;   // 조용히 버리지 않는다
  std::memmove(c->log + at + 1, c->log + at, static_cast<uint64_t>(c->log_n - at) * sizeof(bt_event));
  c->log[at] = ev;
  c->log[at]._pad = 0;
  c->log_n += 1;
  return BT_OK;
}

}  // namespace

namespace bt {
const bt_event* log_find(const bt_ctx* c, uint32_t lts, uint8_t node) {
  bool exists;
  const uint32_t at = find_slot(c, lts, node, &exists);
  return exists ? &c->log[at] : nullptr;
}
}  // namespace bt

bt_status bt_log_append(bt_ctx* c, bt_event* ev) {
  if (!c || !ev) return BT_ERR_ARG;
  if (ev->type > BT_EV_MARK) return BT_ERR_ARG;
  if (c->log_n >= BT_MAX_EVENTS) return BT_ERR_CAPACITY;
  ev->lts = c->clock + 1;
  ev->node = c->cfg.node;
  bool exists;
  const uint32_t at = find_slot(c, ev->lts, ev->node, &exists);
  const bt_status st = insert_at(c, at, *ev);
  if (st != BT_OK) return st;
  c->clock += 1;
  return BT_OK;
}

bt_status bt_log_merge(bt_ctx* c, const bt_event* evs, uint32_t n, uint32_t* out_fresh) {
  if (!c || (!evs && n > 0)) return BT_ERR_ARG;
  uint32_t fresh = 0;
  if (out_fresh) *out_fresh = 0;
  for (uint32_t k = 0; k < n; ++k) {
    const bt_event& r = evs[k];
    if (r.lts == 0 || r.node >= BT_MAX_NODES || r.type > BT_EV_MARK) return BT_ERR_ARG;
    bool exists;
    const uint32_t at = find_slot(c, r.lts, r.node, &exists);
    if (!exists) {
      const bt_status st = insert_at(c, at, r);
      if (st != BT_OK) { if (out_fresh) *out_fresh = fresh; return st; }
      fresh += 1;
    }
    if (r.lts > c->clock) c->clock = r.lts;
  }
  if (out_fresh) *out_fresh = fresh;
  return BT_OK;
}

bt_status bt_log_since(const bt_ctx* c, const uint32_t have_lts[BT_MAX_NODES], bt_event* out, uint32_t cap, uint32_t* n) {
  if (!c || !have_lts || !n || (!out && cap > 0)) return BT_ERR_ARG;
  uint32_t k = 0;
  bool more = false;
  for (uint32_t i = 0; i < c->log_n; ++i) {
    const bt_event& e = c->log[i];
    if (e.lts <= have_lts[e.node]) continue;
    if (k >= cap) { more = true; break; }
    out[k] = e;
    k += 1;
  }
  *n = k;
  return more ? BT_PARTIAL : BT_OK;                 // BT_PARTIAL = 더 남았다. 받은 쪽의 have가 오르면 이어서 보낸다
}

bt_status bt_log_have(const bt_ctx* c, uint32_t out_have_lts[BT_MAX_NODES]) {
  if (!c || !out_have_lts) return BT_ERR_ARG;
  for (int k = 0; k < BT_MAX_NODES; ++k) out_have_lts[k] = 0;
  for (uint32_t i = 0; i < c->log_n; ++i) {
    const bt_event& e = c->log[i];
    if (e.lts > out_have_lts[e.node]) out_have_lts[e.node] = e.lts;
  }
  return BT_OK;
}

bt_status bt_log_view(const bt_ctx* c, const bt_event** out, uint32_t* n) {
  if (!c || !out || !n) return BT_ERR_ARG;
  *out = c->log;
  *n = c->log_n;
  return BT_OK;
}

uint64_t bt_log_digest(const bt_ctx* c) {
  if (!c) return 0;
  uint64_t h = FNV_OFFSET;
  for (uint32_t i = 0; i < c->log_n; ++i) {
    const bt_event& e = c->log[i];
    h = fnv(h, e.lts); h = fnv(h, e.node); h = fnv(h, e.type); h = fnv(h, e.kind); h = fnv(h, e.flags);
    h = fnv(h, e.ts); h = fnv(h, e.x); h = fnv(h, e.y);
    h = fnv(h, e.a); h = fnv(h, e.b); h = fnv(h, e.c); h = fnv(h, e.d);
    h = fnv(h, e.ref_lts); h = fnv(h, e.ref_node); h = fnv(h, e.rule); h = fnv(h, e.seq); h = fnv(h, e.aux);
  }
  return h;
}
