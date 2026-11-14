// 로버 콘솔의 목록들: 지점, 바탕표, 메모, 가설 양식 (S3c §6.1).
import { useState } from "react";
import { CONFIDENCE, CONFIDENCE_RANGE, DIRECTION, MINERAL, RULE, clock } from "../shared/i18n";
import { paramList, type Meta } from "../shared/meta";
import type { CmdHyp, ConsoleCmd, HypDraft, HypView, ObsMark } from "../types";

export function PoiList({ meta }: { meta: Meta }) {
  return (
    <table className="plain">
      <thead><tr><th>지점</th><th>가치</th><th>분산</th><th>접근(분)</th></tr></thead>
      <tbody>{meta.pois.map((p) => <tr key={p.id} title={`${p.source.product_id} — ${p.source.note}`}><td>{p.name}</td><td>{p.value_mu ?? "–"}</td><td>{p.value_var ?? "–"}</td><td>{p.access_cost_min ?? "–"}</td></tr>)}</tbody>
    </table>
  );
}

// 바탕표 열람(편집 없음). 값은 보정된 확률이 아니라 상대 지수이고, 전문가 검토 전의 예시값이다 — 그 사실을 표 위에 늘 적어 둔다
export function PriorPanel({ meta }: { meta: Meta }) {
  return (
    <>
      <p className="caution">전문가 검토 전 예시값 · 보정된 확률이 아닌 상대 지수 · 출처: config/prior_table.yaml (근거는 REFERENCE §4.1)</p>
      <table className="plain">
        <thead><tr><th>지질 단위</th><th>광물</th><th>값</th><th>분산</th></tr></thead>
        <tbody>{meta.prior_values.map((v, i) => <tr key={i}><td>{v.unit ?? "(없음)"}</td><td>{v.mineral ? MINERAL[v.mineral] ?? v.mineral : "(없음)"}</td><td>{v.mu}</td><td>{v.var}</td></tr>)}</tbody>
      </table>
    </>
  );
}

export function MemoList({ obs, anchor, onPick }: { obs: ObsMark[]; anchor: string | null; onPick: (id: string | null) => void }) {
  if (obs.length === 0) return <p className="none">아직 관측이 없습니다.</p>;
  return (
    <ul className="memos">
      {[...obs].reverse().map((o) => (
        <li key={o.id} className={anchor === o.id ? "picked" : ""} onClick={() => onPick(anchor === o.id ? null : o.id)}>
          <b>{o.found ? "발견" : "없음"}{o.confirmed ? " · 다시 확인함" : ""}</b> <small>{o.node} · EVA {clock(o.ts)} · ({o.xy[0].toFixed(0)}, {o.xy[1].toFixed(0)})</small>
          {o.note && <p>{o.note}</p>}
        </li>
      ))}
    </ul>
  );
}

type Rule = CmdHyp["rule"];

// 가설 양식 (R-29): 네 칸을 전부 골라야 하고 기본값이 없다. 기준점은 위 목록에서 고른 관측의 자리다
export function HypForm({ meta, anchor, draft, hyps, onSend }: { meta: Meta; anchor: string | null; draft: HypDraft | null; hyps: HypView[]; onSend: (m: ConsoleCmd) => void }) {
  const [rule, setRule] = useState<Rule | "">("");
  const [dir, setDir] = useState("");
  const [ext, setExt] = useState("");
  const [conf, setConf] = useState("");
  const extents = paramList(meta, "menu.extent_levels_m");
  const ready = anchor !== null && rule !== "" && dir !== "" && ext !== "" && conf !== "";
  if (draft) {
    return (
      <div className="hypform confirm">
        <p className="readback">{draft.readback}</p>
        <div className="row">
          <button type="button" onClick={() => onSend({ type: "console_command", cmd: { kind: "hyp_reply", reply: "approve" }, anchor_event: null })}>승인</button>
          <button type="button" onClick={() => onSend({ type: "console_command", cmd: { kind: "hyp_reply", reply: "reject" }, anchor_event: null })}>거절</button>
        </div>
      </div>
    );
  }
  return (
    <div className="hypform">
      <div className="row">
        <select value={rule} onChange={(e) => setRule(e.target.value as Rule | "")}><option value="">규칙…</option>{Object.entries(RULE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={dir} onChange={(e) => setDir(e.target.value)}><option value="">방향…</option>{DIRECTION.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
        <select value={ext} onChange={(e) => setExt(e.target.value)}><option value="">범위…</option>{extents.map((m, i) => <option key={m} value={i}>{m} m</option>)}</select>
        <select value={conf} onChange={(e) => setConf(e.target.value)}><option value="">확신…</option>{CONFIDENCE.map((c, i) => <option key={c} value={i}>{c} ({CONFIDENCE_RANGE[i]})</option>)}</select>
        <button type="button" disabled={!ready} onClick={() => ready && onSend({ type: "console_command", anchor_event: anchor,
          cmd: { kind: "hyp", rule: rule as Rule, direction_idx: Number(dir), extent_idx: Number(ext), confidence_idx: Number(conf) } })}>확인 창으로</button>
      </div>
      <small>{anchor ? `기준점: 관측 ${anchor}` : "기준점이 될 관측을 위 목록이나 지도에서 고르세요."}</small>
      {hyps.length > 0 && <ul className="recent">{hyps.map((h) => <li key={h.hyp_id}>{h.hyp_id} · {RULE[h.rule]} · {h.extent_m} m · 처음: {h.conf_chosen_name} → 지금: {h.conf_now_name}</li>)}</ul>}
    </div>
  );
}
