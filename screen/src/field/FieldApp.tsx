// 현장 화면 (태블릿) — 기기 프로그램의 /ws/screen에 붙는다 (S3c §6.2).
//
// 이 화면에는 판단이 없다. 스냅샷(types.ts의 Snapshot)을 그리고, 누른 것을 명령(ScreenCmd)으로 보낼 뿐이다.
// 화면이 스스로 하는 일은 카드 정렬과 레이어·패널 켜고 끄기뿐이다.
// 구성: 위 = 계기 넷(다음 지점 · 출발 한계 · 링크 · 시각) / 가운데 = 지도(범례와 넣어 둔 가설이 얹힌다) / 오른쪽 = 조작 단추 / 아래 = 결정 지점 카드
// 모양은 shared/style.css에 있다. 여기서는 받은 값을 어느 자리에 놓을지만 정한다.
import { useEffect, useState } from "react";
import { DecisionCards } from "../shared/DecisionCards";
import { BINDING, approx, clock } from "../shared/i18n";
import { DEFAULT_LAYERS, LayerPanel } from "../shared/LayerPanel";
import { MapLegend, MapView } from "../shared/MapView";
import { useMeta, type XY } from "../shared/meta";
import { SimBar } from "../shared/SimBar";
import { useSocket } from "../shared/socket";
import { SourceTip } from "../shared/SourceTip";
import type { ScreenCmd, Snapshot } from "../types";
import { HypConfirmDialog, HypothesisMenu } from "./Hypothesis";
import { MarkPanel, ObsPanel } from "./Panels";

type Cmd = ScreenCmd["cmd"];
type Panel = null | "obs" | "hyp" | "mark" | "layers";

// 조작 단추의 그림. 뜻을 돕는 선 그림일 뿐이다
const ICON: Record<string, JSX.Element> = {
  obs: <svg viewBox="0 0 24 24"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>,
  hyp: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M15.5 8.5l-2 5-5 2 2-5z" /></svg>,
  photo: <svg viewBox="0 0 24 24"><path d="M4 8h3l1.5-2.5h7L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></svg>,
  mark: <svg viewBox="0 0 24 24"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0113 0c0 5-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" /></svg>,
  home: <svg viewBox="0 0 24 24"><path d="M9 14l-5-5 5-5" /><path d="M4 9h10a6 6 0 010 12h-3" /></svg>,
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
  const cmd = (c: Cmd) => send({ type: "command", cmd: c } satisfies ScreenCmd);

  if (!meta) return <div className="wait">번들 메타를 읽는 중…</div>;
  if (!snap) return <div className="wait">{connected ? "첫 스냅샷을 기다리는 중…" : "기기 프로그램에 붙는 중…"}<SimBar /></div>;
  const s = snap.state, g = snap.gauge, n = snap.nlt, uhf = snap.channels.uhf, wifi = snap.channels.wifi;
  const draft = snap.hyp_draft;

  return (
    <div className="app field">
      <header className="top">
        <div className="brand"><b>BINGOTIME</b><span>현장 화면 · {s.node}</span></div>
        <div className="inst">
          <span className="inst-label">다음 지점</span>
          {g ? (
            <div className="inst-main">
              <span className="compass" title={`방위 ${Math.round(g.bearing_deg)}° (위가 북쪽)`}><i style={{ transform: `rotate(${g.bearing_deg}deg)` }} /></span>
              <div>
                <div className="inst-read"><b className="num">{g.distance_m}<u>m</u></b></div>
                <span className="inst-sub">걸어서 {approx(g.time_min)} · 방위 {Math.round(g.bearing_deg)}°</span>
              </div>
            </div>
          ) : <b className="state">계획된 지점 없음</b>}
        </div>
        <div className={`inst${snap.nlt_warn ? " warn" : ""}`}>
          <span className="inst-label">출발 한계 <SourceTip meta={meta} k="safety.nlt_force_min" /></span>
          {n ? <div className="inst-read"><b className="num">{n.slack_min}<u>분 남음</u></b><span className="chip plain">{BINDING[n.binding]}</span></div> : <b className="state">귀환 지도 없음</b>}
          {n && <span className="inst-sub">로버까지 <b>{n.return_dist_m} m</b> · 걸어서 {approx(n.return_time_min)}{n.degraded ? " · 가까운 길 기준" : ""}</span>}
        </div>
        <div className={`inst ${s.link_mode === "LOCAL" ? "local" : "full"}`}>
          <span className="inst-label">링크</span>
          <b className="state">{s.link_mode === "LOCAL" ? "로컬 모드 — 로버 응답 없음" : "연결됨"}</b>
          <span className="inst-sub">
            <span className={`chip ${uhf.state === "UP" ? "up" : "down"}`}>UHF {uhf.state === "UP" ? "켜짐" : `끊김 ${Math.round(uhf.down_for_s ?? 0)}초`}</span>
            <span className={`chip ${wifi.state === "UP" ? "up" : ""}`}>Wi-Fi {wifi.state === "UP" ? "켜짐" : "끊김"}</span>
            {snap.options_paused && <span className="chip hold">선택지 정지</span>}
            {(snap.options_paused || snap.pending_events > 0) && <span className="chip plain">대기 {snap.pending_events}건</span>}
          </span>
        </div>
        <div className="inst">
          <span className="inst-label">시각</span>
          <div className="inst-read"><b className="num">{clock(s.t)}</b><span className="chip plain">LMST {snap.lmst}</span></div>
          <span className="inst-sub">먼지 τ <b>{s.tau_dust}</b><SourceTip meta={meta} k="env.dust_tau_warn" /> · 누적 <b>{s.dose_cum_uSv} µSv</b> · 기록 {snap.log_count}건</span>
        </div>
      </header>

      {(snap.notices.length > 0 || !connected) && (
        <div className="banner">{!connected && <span>기기 프로그램과 끊김 — 마지막 화면입니다.</span>}{snap.notices.map((x, i) => <span key={i}>{x}</span>)}</div>
      )}

      <main className="mid">
        <MapView meta={meta} layersOn={layers} shadowBin={snap.shadow_bin} pos={s.pos as XY} sigma={snap.sigma_m} rover={s.rover_pos as XY | null}
          route={snap.route as XY[]} back={snap.return_rover as XY[]} track={snap.track as XY[]} visited={snap.visited} plan={snap.plan} traces={snap.traces} obs={snap.obs} hyps={snap.hyps}
          options={snap.dp?.options.filter((o) => o.id === preview)} follow onPickHyp={togglePick} shownHyp={hoverHyp ?? pickedHyp} hideRoute={preview !== null} />
        <MapLegend track />
        {snap.hyps.length > 0 && (
          <div className="float hyplist">
            <small>넣어 둔 가설</small>
            {snap.hyps.map((h) => (
              <div key={h.hyp_id} className={pickedHyp === h.hyp_id ? "picked" : ""} title="올리면 지도에 방향과 범위가 보입니다. 누르면 계속 보입니다"
                onPointerEnter={() => setHoverHyp(h.hyp_id)} onPointerLeave={() => setHoverHyp(null)} onClick={() => togglePick(h.hyp_id)}>
                <span>{h.hyp_id}<br /><i>처음: {h.conf_chosen_name} → 지금: {h.conf_now_name}</i></span>
                <button type="button" onClick={(e) => { e.stopPropagation(); cmd({ kind: "hyp_withdraw", hyp_id: h.hyp_id }); }}>철회</button>
              </div>
            ))}
          </div>
        )}
        <aside className="actions">
          <button type="button" className={panel === "obs" ? "on" : ""} onClick={() => setPanel(panel === "obs" ? null : "obs")}>{ICON.obs}관측</button>
          <button type="button" className={panel === "hyp" ? "on" : ""} onClick={() => setPanel(panel === "hyp" ? null : "hyp")}>{ICON.hyp}가설</button>
          <button type="button" onClick={() => cmd({ kind: "photo" })}>{ICON.photo}촬영</button>
          <button type="button" className={panel === "mark" ? "on" : ""} onClick={() => setPanel(panel === "mark" ? null : "mark")}>{ICON.mark}새 지점 · 막힘</button>
          <button type="button" className={panel === "layers" ? "on" : ""} onClick={() => setPanel(panel === "layers" ? null : "layers")}>{ICON.layers}레이어</button>
          <span className="gap" />
          <button type="button" className="go-home" onClick={() => cmd({ kind: "return" })}>{ICON.home}귀환</button>
        </aside>
        {panel === "obs" && <ObsPanel meta={meta} onSend={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "mark" && <MarkPanel meta={meta} onSend={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "hyp" && <HypothesisMenu meta={meta} draft={draft} onSubmit={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "layers" && <div className="panel"><h3>레이어</h3><LayerPanel meta={meta} on={layers} setOn={setLayers} shadowBin={snap.shadow_bin} /><div className="row"><button type="button" onClick={() => setPanel(null)}>닫기</button></div></div>}
        {draft && panel !== "hyp" && <HypConfirmDialog draft={draft} onReply={(reply) => { cmd({ kind: "hyp_reply", reply }); if (reply === "edit") setPanel("hyp"); }} />}
      </main>

      {snap.dp
        ? <DecisionCards key={snap.dp.dp_id} dp={snap.dp} text={snap.dp_text} source={snap.dp_source} ageS={snap.dp_age_s} meta={meta}
            onChoose={(id, sort) => cmd({ kind: "choose", dp_id: snap.dp!.dp_id, option_id: id, sort_key: sort })} onPreview={setPreview} />
        : <section className="dp empty">{snap.options_paused ? "선택지 정지 — 로버와 다시 이어지면 새 카드가 옵니다. 귀환 경로와 출발 한계는 계속 보입니다." : "떠 있는 결정 지점이 없습니다."}</section>}
      <SimBar />
    </div>
  );
}
