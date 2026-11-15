// FNV-1a 64 다이제스트. 구조체의 정해진 필드 순서로 돈다 (자리 채움 바이트는 넣지 않는다)
#include "ctx.hpp"

namespace bt {
uint64_t fnv_bytes(uint64_t h, const void* p, uint64_t n) {
  const uint8_t* b = static_cast<const uint8_t*>(p);
  for (uint64_t i = 0; i < n; ++i) {
    h ^= b[i];
    h *= 1099511628211ull;
  }
  return h;
}
}  // namespace bt

using namespace bt;

uint64_t bt_config_digest(const bt_ctx* c) {
  if (!c) return 0;
  uint64_t h = fnv_bytes(FNV_OFFSET, &c->cfg, sizeof(bt_config));   // bt_config에는 빈 자리가 없다 (api.cpp에서 확인)
  for (int k = 0; k < BT_LAYER_COUNT; ++k) {
    h = fnv(h, c->layer_set[k]);
    if (c->layer_set[k]) h = fnv(h, c->layer_digest[k]);
  }
  return h;
}

uint64_t bt_option_digest(const bt_option* o) {
  if (!o) return 0;
  uint64_t h = FNV_OFFSET;
  h = fnv(h, o->label); h = fnv(h, o->kind); h = fnv(h, o->label_key); h = fnv(h, o->flags);
  h = fnv(h, o->over_limit); h = fnv(h, o->n_stops); h = fnv(h, o->n_reasons);
  h = fnv(h, o->value_grade); h = fnv(h, o->nlt_binding);
  for (uint32_t i = 0; i < o->n_stops && i < BT_MAX_STOPS; ++i) {
    const bt_stop& s = o->stops[i];
    h = fnv(h, s.xy.x); h = fnv(h, s.xy.y); h = fnv(h, s.dwell_min); h = fnv(h, s.purpose); h = fnv(h, s.poi); h = fnv(h, s.profile);
  }
  h = fnv(h, o->path_len);
  h = fnv(h, o->time_min); h = fnv(h, o->max_slope_deg); h = fnv(h, o->dose_uSv);
  h = fnv(h, o->value_mean); h = fnv(h, o->value_var); h = fnv(h, o->value_lo); h = fnv(h, o->value_hi);
  h = fnv(h, o->info_gain); h = fnv(h, o->explore_count);
  h = fnv(h, o->comm_loss_min); h = fnv(h, o->nlt_margin_min); h = fnv(h, o->return_time_min);
  for (int i = 0; i < BT_OPTION_HYPS; ++i) h = fnv(h, o->hyp_seq[i]);
  for (uint32_t i = 0; i < o->n_reasons && i < BT_MAX_REASONS; ++i) {
    const bt_reason& r = o->reasons[i];
    h = fnv(h, r.layer); h = fnv(h, r.value); h = fnv(h, r.cell.row); h = fnv(h, r.cell.col); h = fnv(h, r.res_m);
  }
  return h;
}

uint64_t bt_decision_digest(const bt_decision* d) {
  if (!d) return 0;
  uint64_t h = FNV_OFFSET;
  // seq(결정 지점 번호)는 이름이지 내용이 아니라서 넣지 않는다 — 같은 입력이면 같은 값이 나와야 한다 (V-7)
  h = fnv(h, d->trigger); h = fnv(h, d->cause_kind); h = fnv(h, d->forced);
  h = fnv(h, d->n_options); h = fnv(h, d->cause_lts); h = fnv(h, d->cause_node); h = fnv(h, d->node);
  h = fnv(h, d->notices); h = fnv(h, d->ts);
  for (uint32_t i = 0; i < d->n_options && i < BT_MAX_OPTIONS; ++i) {
    const uint64_t od = bt_option_digest(&d->options[i]);
    h = fnv(h, od);
  }
  h = fnv(h, d->inputs_digest);
  return h;
}
