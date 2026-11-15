// 가설 메뉴와 확인 창 (S3c §7, R-20).
//
// 네 칸(규칙·방향·범위·확신)을 전부 골라야 보낼 수 있다. 기본값이 없다 — 시스템은 빈칸을 채우지 않는다
// (지어낸 방향·거리가 지도와 경로에 들어가면 안 된다). 보낸 뒤에는 프로그램이 되읽기 문장을 만들어 스냅샷의 hyp_draft에 싣고,
// 확인 창이 그 문장을 그대로 보인다: 승인 / 수정 / 거절.
import { useState } from "react";
import { CONFIDENCE, CONFIDENCE_RANGE, DIRECTION, RULE } from "../shared/i18n";
import { paramList, type Meta } from "../shared/meta";
import { SourceTip } from "../shared/SourceTip";
import type { CmdHyp, HypDraft } from "../types";

type Rule = CmdHyp["rule"];

export function HypothesisMenu({ meta, draft, onSubmit, onClose }: { meta: Meta; draft: HypDraft | null; onSubmit: (c: CmdHyp) => void; onClose: () => void }) {
  // "수정"으로 돌아왔을 때만 앞서 고른 값이 들어 있다. 처음 열면 네 칸 모두 비어 있다
  const [rule, setRule] = useState<Rule | null>(draft?.rule ?? null);
  const [dir, setDir] = useState<number | null>(draft?.direction_idx ?? null);
  const [ext, setExt] = useState<number | null>(draft?.extent_idx ?? null);
  const [conf, setConf] = useState<number | null>(draft?.confidence_idx ?? null);
  const extents = paramList(meta, "menu.extent_levels_m");
  const ready = rule !== null && dir !== null && ext !== null && conf !== null;
  return (
    <div className="panel wide">
      <h3>Hypothesis <small>— Pick all four. The anchor is where you stand now.</small></h3>
      <div className="row"><span className="lbl">Rule</span>{(Object.keys(RULE) as Rule[]).map((r) => <button type="button" key={r} className={rule === r ? "on" : ""} onClick={() => setRule(r)}>{RULE[r]}</button>)}</div>
      <div className="row"><span className="lbl">Direction</span>{DIRECTION.map((d, i) => <button type="button" key={d} className={dir === i ? "on" : ""} onClick={() => setDir(i)}>{d}</button>)}</div>
      <div className="row"><span className="lbl">Extent <SourceTip meta={meta} k="menu.extent_levels_m" /></span>{extents.map((m, i) => <button type="button" key={m} className={ext === i ? "on" : ""} onClick={() => setExt(i)}>{m} m</button>)}</div>
      <div className="row"><span className="lbl">Confidence <SourceTip meta={meta} k="menu.confidence_levels" /></span>{CONFIDENCE.map((c, i) => <button type="button" key={c} className={conf === i ? "on" : ""} onClick={() => setConf(i)}>{c} <small>{CONFIDENCE_RANGE[i]}</small></button>)}</div>
      <div className="row">
        <button type="button" disabled={!ready} onClick={() => ready && onSubmit({ kind: "hyp", rule: rule!, direction_idx: dir!, extent_idx: ext!, confidence_idx: conf! })}>Review</button>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

export function HypConfirmDialog({ draft, onReply }: { draft: HypDraft; onReply: (r: "approve" | "reject" | "edit") => void }) {
  return (
    <div className="panel wide confirm">
      <h3>{draft.withdraw_hyp_id ? "Confirm withdrawal" : "Confirm hypothesis"}</h3>
      <p className="readback">{draft.readback}</p>
      <div className="row">
        <button type="button" onClick={() => onReply("approve")}>Approve</button>
        {!draft.withdraw_hyp_id && <button type="button" onClick={() => onReply("edit")}>Edit</button>}
        <button type="button" onClick={() => onReply("reject")}>Reject</button>
      </div>
    </div>
  );
}
