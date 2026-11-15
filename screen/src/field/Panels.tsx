// 관측, 새 지점·막힘 입력 (S3c §7). 누른 것을 명령으로 보낼 뿐이다 — 위치·시각·번호는 프로그램이 채운다.
// 자유 메모는 글자 그대로 저장되고 지도에 보인다. 시스템은 그 글자를 해석하지 않는다.
import { useState } from "react";
import { paramList, type Meta } from "../shared/meta";
import type { CmdMark, CmdObs } from "../types";

export function ObsPanel({ meta, onSend, onClose }: { meta: Meta; onSend: (c: CmdObs) => void; onClose: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const max = Number(meta.params.find((p) => p.key === "menu.note_max_chars")?.value ?? 200);
  return (
    <div className="panel">
      <h3>Observation</h3>
      <label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> Re-checked</label>
      <textarea placeholder="Free note (optional) — saved exactly as typed" maxLength={max} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button type="button" onClick={() => onSend({ kind: "obs", found: true, confirmed, note })}>Found</button>
        <button type="button" onClick={() => onSend({ kind: "obs", found: false, confirmed, note })}>None</button>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

export function MarkPanel({ meta, onSend, onClose }: { meta: Meta; onSend: (c: CmdMark) => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [radius, setRadius] = useState<number | null>(null);
  const radii = paramList(meta, "menu.mark_radius_levels_m");
  return (
    <div className="panel">
      <h3>New site · Blocked</h3>
      <input placeholder="Site name" maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
      <textarea placeholder="Free note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button type="button" disabled={!name} onClick={() => onSend({ kind: "mark", what: "poi", name, radius_idx: 0, note })}>Mark this spot as a new site</button>
      </div>
      <div className="row">Blocked radius {radii.map((r, i) => <button type="button" key={r} className={radius === i ? "on" : ""} onClick={() => setRadius(i)}>{r} m</button>)}
        <button type="button" disabled={radius === null} onClick={() => radius !== null && onSend({ kind: "mark", what: "blocked", name, radius_idx: radius, note })}>Blocked here</button>
      </div>
      <div className="row"><button type="button" onClick={onClose}>Close</button></div>
    </div>
  );
}
