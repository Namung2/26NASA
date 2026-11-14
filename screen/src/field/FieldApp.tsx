// 현장 화면 (태블릿) — 기기 프로그램의 /ws/screen에 붙는다 (S3c §6.2).
//
// 이 화면에는 판단이 없다. 스냅샷(types.ts의 Snapshot)을 그리고, 누른 것을 명령(ScreenCmd)으로 보낼 뿐이다.
// 화면이 스스로 하는 일은 카드 정렬과 레이어·패널 켜고 끄기뿐이다.
// 구성: 위 = 다음 지점 게이지 · 출발 한계 · 링크 표시 / 가운데 = 지도 / 오른쪽 = 조작 단추 / 아래 = 결정 지점 카드
import { useState } from "react";
import { DecisionCards } from "../shared/DecisionCards";
import { BINDING, approx, clock } from "../shared/i18n";
import { DEFAULT_LAYERS, LayerPanel } from "../shared/LayerPanel";
import { MapView } from "../shared/MapView";
import { useMeta, type XY } from "../shared/meta";
import { SimBar } from "../shared/SimBar";
import { useSocket } from "../shared/socket";
import { SourceTip } from "../shared/SourceTip";
import type { ScreenCmd, Snapshot } from "../types";
import { HypConfirmDialog, HypothesisMenu } from "./Hypothesis";
import { MarkPanel, ObsPanel } from "./Panels";

type Cmd = ScreenCmd["cmd"];
type Panel = null | "obs" | "hyp" | "mark" | "layers";

export function FieldApp() {
  const meta = useMeta();
  const { snap, connected, send } = useSocket<Snapshot>("/ws/screen");
  const [layers, setLayers] = useState(DEFAULT_LAYERS);
  const [panel, setPanel] = useState<Panel>(null);
  const [pickedHyp, setPickedHyp] = useState<string | null>(null);
  const cmd = (c: Cmd) => send({ type: "command", cmd: c } satisfies ScreenCmd);

  if (!meta) return <div className="wait">번들 메타를 읽는 중…</div>;
  if (!snap) return <div className="wait">{connected ? "첫 스냅샷을 기다리는 중…" : "기기 프로그램에 붙는 중…"}<SimBar /></div>;
  const s = snap.state, g = snap.gauge, n = snap.nlt, uhf = snap.channels.uhf, wifi = snap.channels.wifi;
  const draft = snap.hyp_draft;

  return (
    <div className="app field">
      <header className="top">
        <div className="tile">
          <small>다음 지점</small>
          {g ? <b>{Math.round(g.bearing_deg)}° · {g.distance_m} m · 걸어서 {approx(g.time_min)}</b> : <b>계획된 지점 없음</b>}
        </div>
        <div className={`tile${snap.nlt_warn ? " warn" : ""}`}>
          <small>출발 한계 <SourceTip meta={meta} k="safety.nlt_force_min" /></small>
          {n ? <b>출발까지 {n.slack_min}분 <i>({BINDING[n.binding]})</i></b> : <b>귀환 지도 없음</b>}
          {n && <span>로버까지 {n.return_dist_m} m · 걸어서 {approx(n.return_time_min)}{n.degraded ? " · 가까운 길 기준" : ""}</span>}
        </div>
        <div className={`tile link ${s.link_mode === "LOCAL" ? "local" : "full"}`}>
          <small>링크</small>
          <b>{s.link_mode === "LOCAL" ? "로컬 모드 — 로버 응답 없음" : "연결됨"}</b>
          <span>UHF {uhf.state === "UP" ? "켜짐" : `끊김 ${Math.round(uhf.down_for_s ?? 0)}초`} · Wi-Fi {wifi.state === "UP" ? "켜짐" : "끊김"}
            {snap.options_paused ? ` · 선택지 정지 · 대기 ${snap.pending_events}건` : snap.pending_events > 0 ? ` · 대기 ${snap.pending_events}건` : ""}</span>
        </div>
        <div className="tile">
          <small>시각</small>
          <b>EVA {clock(s.t)}</b>
          <span>LMST {snap.lmst} · 먼지 τ {s.tau_dust} <SourceTip meta={meta} k="env.dust_tau_warn" /> · 누적 {s.dose_cum_uSv} µSv · 기록 {snap.log_count}건</span>
        </div>
      </header>

      {(snap.notices.length > 0 || !connected) && (
        <div className="banner">{!connected && <span>기기 프로그램과 끊김 — 마지막 화면입니다.</span>}{snap.notices.map((x, i) => <span key={i}>{x}</span>)}</div>
      )}

      <main className="mid">
        <MapView meta={meta} layersOn={layers} shadowBin={snap.shadow_bin} pos={s.pos as XY} sigma={snap.sigma_m} rover={s.rover_pos as XY | null}
          route={snap.route as XY[]} back={snap.return_rover as XY[]} plan={snap.plan} traces={snap.traces} obs={snap.obs} hyps={snap.hyps}
          options={snap.dp?.options} follow onPickHyp={setPickedHyp} />
        <aside className="actions">
          <button type="button" onClick={() => setPanel(panel === "obs" ? null : "obs")}>관측</button>
          <button type="button" onClick={() => setPanel(panel === "hyp" ? null : "hyp")}>가설</button>
          <button type="button" onClick={() => cmd({ kind: "photo" })}>촬영</button>
          <button type="button" onClick={() => setPanel(panel === "mark" ? null : "mark")}>새 지점 · 막힘</button>
          <button type="button" onClick={() => cmd({ kind: "return" })}>귀환</button>
          <button type="button" onClick={() => setPanel(panel === "layers" ? null : "layers")}>레이어</button>
          {snap.hyps.length > 0 && (
            <div className="hyplist">
              <small>넣어 둔 가설</small>
              {snap.hyps.map((h) => (
                <div key={h.hyp_id} className={pickedHyp === h.hyp_id ? "picked" : ""}>
                  <span>{h.hyp_id}<br /><i>처음: {h.conf_chosen_name} → 지금: {h.conf_now_name}</i></span>
                  <button type="button" onClick={() => cmd({ kind: "hyp_withdraw", hyp_id: h.hyp_id })}>철회</button>
                </div>
              ))}
            </div>
          )}
        </aside>
        {panel === "obs" && <ObsPanel meta={meta} onSend={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "mark" && <MarkPanel meta={meta} onSend={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "hyp" && <HypothesisMenu meta={meta} draft={draft} onSubmit={(c) => { cmd(c); setPanel(null); }} onClose={() => setPanel(null)} />}
        {panel === "layers" && <div className="panel"><h3>레이어</h3><LayerPanel meta={meta} on={layers} setOn={setLayers} shadowBin={snap.shadow_bin} /><div className="row"><button type="button" onClick={() => setPanel(null)}>닫기</button></div></div>}
        {draft && panel !== "hyp" && <HypConfirmDialog draft={draft} onReply={(reply) => { cmd({ kind: "hyp_reply", reply }); if (reply === "edit") setPanel("hyp"); }} />}
      </main>

      {snap.dp
        ? <DecisionCards key={snap.dp.dp_id} dp={snap.dp} text={snap.dp_text} source={snap.dp_source} ageS={snap.dp_age_s} meta={meta}
            onChoose={(id, sort) => cmd({ kind: "choose", dp_id: snap.dp!.dp_id, option_id: id, sort_key: sort })} />
        : <section className="dp empty">{snap.options_paused ? "선택지 정지 — 로버와 다시 이어지면 새 카드가 옵니다. 귀환 경로와 출발 한계는 계속 보입니다." : "떠 있는 결정 지점이 없습니다."}</section>}
      <SimBar />
    </div>
  );
}
