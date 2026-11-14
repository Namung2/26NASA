// C-33 링크 상태기계: 채널 추정과 모드 판정 (S3a §9). 소켓·타이머는 호스트의 일이다
#include "ctx.hpp"

namespace {

struct Out { uint8_t mode_changed, lost; };

void go_down(bt_link* s, bt_channel* ch, bool is_uhf, double t_ms, Out* o) {
  if (ch->state == BT_CHS_DOWN) return;
  ch->state = BT_CHS_DOWN;
  ch->down_since = t_ms;
  ch->ack_run = 0;
  if (is_uhf) {
    if (s->mode != BT_LINK_LOCAL) o->mode_changed = 1;
    s->mode = BT_LINK_LOCAL;
    s->lost_fired = 0;
  }
}

void go_up(bt_link* s, bt_channel* ch, bool is_uhf, Out* o) {
  ch->state = BT_CHS_UP;
  ch->miss_run = 0;
  ch->down_since = 0.0;
  if (is_uhf) {
    if (s->mode != BT_LINK_FULL) o->mode_changed = 1;
    s->mode = BT_LINK_FULL;
    s->lost_fired = 0;
  }
}

// 응답 한계를 넘긴 하트비트를 miss로 센다. count = false면 세지 않고 지우기만 한다(틱이 밀린 구간)
void expire(bt_link* s, bt_channel* ch, const bt_link_cfg& k, bool is_uhf, double t_ms, bool count, Out* o) {
  if (!ch->pending || !(t_ms - ch->pending_t_ms > static_cast<double>(k.timeout_ms))) return;
  ch->pending = 0;
  if (!count) return;
  if (ch->miss_run < 255) ch->miss_run += 1;
  ch->ack_run = 0;
  ch->loss = k.ewma_alpha * 1.0f + (1.0f - k.ewma_alpha) * ch->loss;
  if (ch->state == BT_CHS_UP && (ch->miss_run >= k.n_down || ch->loss > k.loss_down)) go_down(s, ch, is_uhf, t_ms, o);
}

}  // namespace

bt_status bt_link_step(const bt_ctx* c, bt_link* s, const bt_link_in* in, uint8_t* out_mode_changed, uint8_t* out_lost_trigger) {
  if (!c || !s || !in) return BT_ERR_ARG;
  if (in->kind > BT_NET_TICK) return BT_ERR_ARG;
  if (in->kind != BT_NET_TICK && in->ch > BT_CH_WIFI) return BT_ERR_ARG;
  const bt_config& cfg = c->cfg;
  Out o{0, 0};
  const double t = in->t_ms;

  if (in->kind == BT_NET_TICK) {
    // 틱 간격이 2 / hb_hz 를 넘으면(호스트 타이머가 느려짐) 그 구간의 miss는 세지 않는다
    const double max_gap = cfg.hb_hz > 0 ? 2000.0 / static_cast<double>(cfg.hb_hz) : 0.0;
    const bool count = !(max_gap > 0 && t - s->last_tick_ms > max_gap);
    expire(s, &s->uhf, cfg.uhf, true, t, count, &o);
    expire(s, &s->wifi, cfg.wifi, false, t, count, &o);
    s->last_tick_ms = t;
    if (s->uhf.state == BT_CHS_DOWN && !s->lost_fired &&
        (t - s->uhf.down_since) / 1000.0 > static_cast<double>(cfg.lost_dp_s)) {   // 트리거 ③: 두절이 오래 이어짐
      s->lost_fired = 1;
      o.lost = 1;
    }
  } else {
    const bool is_uhf = (in->ch == BT_CH_UHF);
    bt_channel* ch = is_uhf ? &s->uhf : &s->wifi;
    const bt_link_cfg& k = is_uhf ? cfg.uhf : cfg.wifi;
    if (in->kind == BT_NET_SENT) {
      expire(s, ch, k, is_uhf, t, true, &o);
      ch->pending = 1;
      ch->pending_seq = in->seq;
      ch->pending_t_ms = t;
    } else if (in->kind == BT_NET_ACK) {
      if (ch->pending && ch->pending_seq == in->seq && !(t - ch->pending_t_ms > static_cast<double>(k.timeout_ms))) {
        const float rtt = static_cast<float>(t - ch->pending_t_ms);
        ch->pending = 0;
        ch->miss_run = 0;
        if (ch->ack_run < 255) ch->ack_run += 1;
        ch->loss = (1.0f - k.ewma_alpha) * ch->loss;
        ch->rtt_ms = (ch->rtt_ms > 0.0f) ? k.ewma_alpha * rtt + (1.0f - k.ewma_alpha) * ch->rtt_ms : rtt;
        if (ch->state == BT_CHS_DOWN) {
          if (ch->ack_run >= k.n_up) go_up(s, ch, is_uhf, &o);            // 복구는 느리게
        } else if (k.rtt_down_ms > 0 && ch->rtt_ms > k.rtt_down_ms) {
          go_down(s, ch, is_uhf, t, &o);
        }
      }
      // 한계를 넘겨 온 응답과 모르는 번호의 응답은 버린다
    } else {                                                              // SEND_ERROR → 즉시 DOWN
      ch->pending = 0;
      ch->ack_run = 0;
      go_down(s, ch, is_uhf, t, &o);
    }
  }
  if (out_mode_changed) *out_mode_changed = o.mode_changed;
  if (out_lost_trigger) *out_lost_trigger = o.lost;
  return BT_OK;
}
