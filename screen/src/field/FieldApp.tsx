// 현장 화면 (태블릿) — 기기 프로그램의 /ws/screen에 붙는다 (S3c §6.2).
//
// 이 화면에는 판단이 없다. 스냅샷(types.ts의 Snapshot)을 그리고, 누른 것을 명령(ScreenCmd)으로 보낼 뿐이다.
// 화면이 스스로 하는 일은 카드 정렬과 레이어·패널 켜고 끄기뿐이다.
// 구성: 위 = 계기 넷(다음 지점 · 출발 한계 · 링크 · 시각) / 가운데 = 지도(범례와 넣어 둔 가설이 얹힌다) / 지도 오른쪽에 뜬 조작 단추 줄(Dock) / 아래 = 결정 지점 카드
// 모양은 shared/style.css에 있다. 여기서는 받은 값을 어느 자리에 놓을지만 정한다.
import { useEffect, useRef, useState } from "react";
import { DecisionCards } from "../shared/DecisionCards";
import { BINDING, approx, clock } from "../shared/i18n";
import { Dock } from "../shared/Dock";
import { DEFAULT_LAYERS, LayerPanel } from "../shared/LayerPanel";
import { Loader } from "../shared/Loader";
import { MapLegend, MapView } from "../shared/MapView";
import { useMeta, type XY } from "../shared/meta";
import { SimBar } from "../shared/SimBar";
import { useSocket } from "../shared/socket";
import { SourceTip } from "../shared/SourceTip";
import type { ScreenCmd, Snapshot, Stop } from "../types";
import { CameraPanel } from "./Camera";
import { HypConfirmDialog, HypothesisMenu } from "./Hypothesis";
import { MarkPanel, ObsPanel } from "./Panels";

type Cmd = ScreenCmd["cmd"];
type Panel = null | "obs" | "hyp" | "photo" | "mark" | "layers" | "plan";

// 조작 단추의 그림. 뜻을 돕는 선 그림일 뿐이다
const ICON: Record<string, JSX.Element> = {
  obs: <svg viewBox="0 0 24 24"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>,
  hyp: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M15.5 8.5l-2 5-5 2 2-5z" /></svg>,
  photo: <svg viewBox="0 0 24 24"><path d="M4 8h3l1.5-2.5h7L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></svg>,
  mark: <svg viewBox="0 0 24 24"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0113 0c0 5-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" /></svg>,
  home: <svg viewBox="0 0 24 24"><path d="M9 14l-5-5 5-5" /><path d="M4 9h10a6 6 0 010 12h-3" /></svg>,
  plan: <svg viewBox="0 0 24 24"><circle cx="5" cy="18" r="2.2" /><circle cx="12" cy="7" r="2.2" /><circle cx="19" cy="15" r="2.2" /><path d="M6.4 16.2l4.3-7.3M13.9 8.6l3.8 4.6" /></svg>,
  layers: <svg viewBox="0 0 24 24"><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></svg>,
};

export function FieldApp() {
  const meta = useMeta();
  const { snap, connected, send } = useSocket<Snapshot>("/ws/screen");
  const [layers, setLayers] = useState(DEFAULT_LAYERS);
  const [panel, setPanel] = useState<Panel>(null);
  const [pickedHyp, setPickedHyp] = useState<string | null>(null);   // 눌러서 골라 둔 가설(다시 누르면 풀린다) — 그 가설의 점선이 계속 보인다
  const [hoverHyp, setHoverHyp] = useState<string | null>(null);     // "넣어 둔 가설" 목록에서 마우스를 올린 가설
  const togglePick = (id: string) => setPickedHyp((cur) => (cur === id ? null : id));
  const [preview, setPreview] = useState<string | null>(null);     // 마우스를 올린 카드(그 카드의 경로만 지도에 미리 보인다)
  const dpId = snap?.dp?.dp_id ?? null;
  useEffect(() => setPreview(null), [dpId]);                        // 카드 묶음이 바뀌면 미리 보기를 지운다
  // 가설 목표에 닿으면 관측 입력 창을 연다. 가설 목표는 거기서 관측을 남겨야 끝난다(코어의 규칙) — 그냥 지나가면 같은 목표가 다시 나온다.
  // "닿았다"는 프로그램이 정해 보낸 것(스냅샷의 visited)이고, 화면은 그 목록이 늘어난 것을 보고 창을 열 뿐이다. 관측을 대신 넣지 않는다.
  // 다른 창이 열려 있으면 건드리지 않는다. 화면을 처음 열었을 때 이미 다녀온 것에는 열지 않는다.
  const reached = snap ? snap.visited.filter((v) => v.purpose === "hyp_target").length : null;
  const seen = useRef<number | null>(null);
  const [atTarget, setAtTarget] = useState(false);                  // 관측 창을 가설 목표 도착 때문에 열었는가(창에 한 줄 알림을 보인다)
  useEffect(() => {
    if (reached === null) return;
    if (seen.current !== null && reached > seen.current) { setAtTarget(true); setPanel((cur) => cur ?? "obs"); }
    seen.current = reached;
  }, [reached]);
  useEffect(() => { if (panel !== "obs") setAtTarget(false); }, [panel]);
  // 경로 재설정: 지도에서 정지점을 차례로 눌러 순서를 짠다. 보낸다고 계획이 바뀌지 않는다 — 로버가 그 순서를 계산해
  // "My plan" 카드로 다른 카드 옆에 띄우고, 그 카드를 골라야 바뀐다. 화면은 누른 순서를 모아 보낼 뿐이다(시간·경사·안전은 따지지 않는다)
  const [planPicks, setPlanPicks] = useState<string[]>([]);
  useEffect(() => { if (panel !== "plan") setPlanPicks([]); }, [panel]);
  const cmd = (c: Cmd) => send({ type: "command", cmd: c } satisfies ScreenCmd);

  if (!meta) return <div className="wait"><Loader label="Reading bundle metadata" /></div>;
  if (!snap) return <div className="wait"><Loader label={connected ? "Waiting for the first snapshot" : "Connecting to the device program"} /><SimBar /></div>;
  const s = snap.state, g = snap.gauge, n = snap.nlt, uhf = snap.channels.uhf, wifi = snap.channels.wifi;
  const draft = snap.hyp_draft;
  // 누를 수 있는 정지점: 번들의 지점(P1…)과, 스냅샷에 실려 온 가설 목표(계획에 든 것과 떠 있는 카드의 것).
  // 머무는 시간은 스냅샷에 그 정지점이 실려 있으면 그 값을 그대로 쓰고, 없으면 0으로 보낸다(계약의 기본값) — 화면이 시간을 지어내지 않는다
  const known: Stop[] = [...snap.plan, ...snap.visited, ...(snap.dp?.options.flatMap((o) => o.stops) ?? [])];
  const planCands: { key: string; stop: Stop; label: string }[] = [
    ...meta.pois.map((q) => ({ key: q.id, label: q.name || q.id,
      stop: { xy: q.xy, poi_id: q.id, purpose: "poi" as const, profile: "balanced" as const, dwell_min: known.find((k) => k.poi_id === q.id)?.dwell_min ?? 0 } })),
    ...known.filter((k) => k.purpose === "hyp_target" && !k.poi_id).filter((k, i, a) => a.findIndex((x) => x.xy.join() === k.xy.join()) === i)
      .map((k) => ({ key: `hyp:${k.xy.join()}`, label: "Hypothesis target", stop: { ...k, profile: "balanced" as const } })),
  ];
  const planStops = planPicks.map((k) => planCands.find((c) => c.key === k)).filter((c): c is (typeof planCands)[number] => !!c);
  const togglePlan = (key: string) => setPlanPicks((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : cur.length < 8 ? [...cur, key] : cur));

  return (
    <div className="app field">
      <header className="top">
        <div className="brand"><a href="/" title="Back to map and scenario selection"><b>BINGOTIME</b></a><span>FIELD · {s.node}</span></div>
        <div className="inst">
          <span className="inst-label">NEXT STOP</span>
          {g ? (
            <div className="inst-main">
              <span className="compass" title={`Bearing ${Math.round(g.bearing_deg)}° (north is up)`}><i style={{ transform: `rotate(${g.bearing_deg}deg)` }} /></span>
              <div>
                <div className="inst-read"><b className="num">{g.distance_m}<u>m</u></b></div>
                <span className="inst-sub">{approx(g.time_min)} · bearing {Math.round(g.bearing_deg)}°</span>
              </div>
            </div>
          ) : <b className="state">No planned stop</b>}
        </div>
        <div className={`inst${snap.nlt_warn ? " warn" : ""}`}>
          <span className="inst-label">DEPART LIMIT <SourceTip meta={meta} k="safety.nlt_force_min" /></span>
          {n ? <div className="inst-read"><b className="num">{n.slack_min}<u>min left</u></b><span className="chip plain">{BINDING[n.binding]}</span></div> : <b className="state">No return map</b>}
          {n && <span className="inst-sub"><b>{n.return_dist_m} m</b> to rover · {approx(n.return_time_min)}{n.degraded ? " · nearest-path estimate" : ""}</span>}
        </div>
        <div className={`inst ${s.link_mode === "LOCAL" ? "local" : "full"}`}>
          <span className="inst-label">LINK</span>
          <b className="state">{s.link_mode === "LOCAL" ? "Local mode — no reply from rover" : "Connected"}</b>
          <span className="inst-sub">
            <span className={`chip ${uhf.state === "UP" ? "up" : "down"}`}>UHF {uhf.state === "UP" ? "up" : `down ${Math.round(uhf.down_for_s ?? 0)} s`}</span>
            <span className={`chip ${wifi.state === "UP" ? "up" : ""}`}>Wi-Fi {wifi.state === "UP" ? "up" : "down"}</span>
            {snap.options_paused && <span className="chip hold">Options paused</span>}
            {(snap.options_paused || snap.pending_events > 0) && <span className="chip plain">{snap.pending_events} queued</span>}
          </span>
        </div>
        <div className="inst">
          <span className="inst-label">TIME</span>
          <div className="inst-read"><b className="num">{clock(s.t)}</b><span className="chip plain">LMST {snap.lmst}</span></div>
          <span className="inst-sub">Dust τ <b>{s.tau_dust}</b><SourceTip meta={meta} k="env.dust_tau_warn" /> · total <b>{s.dose_cum_uSv} µSv</b> · {snap.log_count} log entries</span>
        </div>
      </header>

      {(snap.notices.length > 0 || !connected) && (
        <div className="banner">{!connected && <span className="plain"><Loader />Lost the device program — this is the last screen. Reconnecting</span>}{snap.notices.map((x, i) => <span key={i}>{x}</span>)}</div>
      )}

      <main className="mid">
        <MapView meta={meta} layersOn={layers} shadowBin={snap.shadow_bin} pos={s.pos as XY} sigma={snap.sigma_m} rover={s.rover_pos as XY | null}
          route={snap.route as XY[]} back={snap.return_rover as XY[]} track={snap.track as XY[]} visited={snap.visited} plan={snap.plan} traces={snap.traces} obs={snap.obs} hyps={snap.hyps}
          options={snap.dp?.options.filter((o) => o.id === preview)} follow onPickHyp={togglePick} shownHyp={hoverHyp ?? pickedHyp} hideRoute={preview !== null || panel === "plan"}
          planning={panel === "plan" ? { candidates: planCands, picked: planPicks, onPick: togglePlan } : null} />
        <MapLegend track />
        {snap.hyps.length > 0 && (
          <div className="float hyplist">
            <small>HYPOTHESES</small>
            {snap.hyps.map((h) => (
              <div key={h.hyp_id} className={pickedHyp === h.hyp_id ? "picked" : ""} title="Hover to show its direction and extent on the map. Click to keep it shown"
                onPointerEnter={() => setHoverHyp(h.hyp_id)} onPointerLeave={() => setHoverHyp(null)} onClick={() => togglePick(h.hyp_id)}>
                <span>{h.hyp_id}<br /><i>At entry: {h.conf_chosen_name} → now: {h.conf_now_name}</i></span>
                <button type="button" onClick={(e) => { e.stopPropagation(); cmd({ kind: "hyp_withdraw", hyp_id: h.hyp_id }); }}>Withdraw</button>
              </div>
            ))}
          </div>
        )}
        <Dock label="Actions" items={[
          { key: "obs", icon: ICON.obs, label: "Observe", on: panel === "obs", onClick: () => setPanel(panel === "obs" ? null : "obs") },
          { key: "hyp", icon: ICON.hyp, label: "Hypo.", title: "Hypothesis", on: panel === "hyp", onClick: () => setPanel(panel === "hyp" ? null : "hyp") },
          { key: "photo", icon: ICON.photo, label: "Photo", on: panel === "photo", onClick: () => setPanel(panel === "photo" ? null : "photo") },
          { key: "mark", icon: ICON.mark, label: "Mark", title: "New site · Blocked", on: panel === "mark", onClick: () => setPanel(panel === "mark" ? null : "mark") },
          { key: "plan", icon: ICON.plan, label: "Replan", title: "Replan — build your own stop order", on: panel === "plan", onClick: () => setPanel(panel === "plan" ? null : "plan") },
          { key: "layers", icon: ICON.layers, label: "Layers", on: panel === "layers", onClick: () => setPanel(panel === "layers" ? null : "layers") },
          { sep: true },
          { key: "home", icon: ICON.home, label: "Return", tone: "warm", onClick: () => cmd({ kind: "return" }) },
        ]} />
        {panel === "obs" && <ObsPanel meta={meta} hint={atTarget ? "You reached a hypothesis target. Leave an observation here to close it out — otherwise the same target can come up again." : undefined} onSend={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "photo" && <CameraPanel onTraceOnly={() => { cmd({ kind: "photo" }); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "plan" && (
          <div className="panel">
            <h3>Replan <small>— Click stops on the map in the order you want to visit them.</small></h3>
            <p className="caution">This only sends the order. The rover works out the route and shows it as a “My plan” card next to the other cards. The plan changes only when you select that card.</p>
            {planStops.length === 0 && <p className="none">No stops yet. Click a dashed ring on the map.</p>}
            <ol className="planlist">
              {planStops.map((c, i) => (
                <li key={c.key}><b>{i + 1}</b><span>{c.label} <small>{c.stop.poi_id ?? `(${c.stop.xy[0]}, ${c.stop.xy[1]})`}</small></span>
                  <button type="button" onClick={() => togglePlan(c.key)}>Remove</button></li>
              ))}
            </ol>
            {s.link_mode === "LOCAL" && <p className="missing">The rover link is down. A plan can be compared only while the link is up.</p>}
            <div className="row">
              <button type="button" disabled={planStops.length === 0} onClick={() => { cmd({ kind: "plan", stops: planStops.map((c) => c.stop) }); setPanel(null); }}>Send to rover</button>
              <button type="button" disabled={planStops.length === 0} onClick={() => setPlanPicks([])}>Clear</button>
              <button type="button" onClick={() => setPanel(null)}>Close</button>
            </div>
          </div>
        )}
        {panel === "mark" && <MarkPanel meta={meta} onSend={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "hyp" && <HypothesisMenu meta={meta} draft={draft} onSubmit={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "layers" && <div className="panel"><h3>Layers</h3><LayerPanel meta={meta} on={layers} setOn={setLayers} shadowBin={snap.shadow_bin} /><div className="row"><button type="button" onClick={() => setPanel(null)}>Close</button></div></div>}
        {draft && panel !== "hyp" && <HypConfirmDialog draft={draft} onReply={(reply) => { cmd({ kind: "hyp_reply", reply }); if (reply === "edit") setPanel("hyp"); }} />}
      </main>

      {snap.dp
        ? <DecisionCards key={snap.dp.dp_id} dp={snap.dp} text={snap.dp_text} source={snap.dp_source} ageS={snap.dp_age_s} meta={meta}
            onChoose={(id, sort) => cmd({ kind: "choose", dp_id: snap.dp!.dp_id, option_id: id, sort_key: sort })} onPreview={setPreview} />
        : <section className="dp empty">{snap.options_paused ? <Loader label="Options paused — new cards arrive once the rover link is back. The return route and departure limit stay on screen." /> : "No decision point is open."}</section>}
      <SimBar />
    </div>
  );
}
