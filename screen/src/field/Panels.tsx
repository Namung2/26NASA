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
      <h3>관측</h3>
      <label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> 다시 확인했음</label>
      <textarea placeholder="자유 메모 (선택) — 글자 그대로 저장됩니다" maxLength={max} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button type="button" onClick={() => onSend({ kind: "obs", found: true, confirmed, note })}>발견</button>
        <button type="button" onClick={() => onSend({ kind: "obs", found: false, confirmed, note })}>없음</button>
        <button type="button" onClick={onClose}>닫기</button>
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
      <h3>새 지점 · 막힘</h3>
      <input placeholder="지점 이름" maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
      <textarea placeholder="자유 메모 (선택)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button type="button" disabled={!name} onClick={() => onSend({ kind: "mark", what: "poi", name, radius_idx: 0, note })}>현재 위치를 새 지점으로</button>
      </div>
      <div className="row">막힘 반경 {radii.map((r, i) => <button type="button" key={r} className={radius === i ? "on" : ""} onClick={() => setRadius(i)}>{r} m</button>)}
        <button type="button" disabled={radius === null} onClick={() => radius !== null && onSend({ kind: "mark", what: "blocked", name, radius_idx: radius, note })}>여기가 막힘</button>
      </div>
      <div className="row"><button type="button" onClick={onClose}>닫기</button></div>
    </div>
  );
}
