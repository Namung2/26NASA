// 로버 콘솔 (계획 화면) — 로버 프로그램의 /ws/console에 붙는다 (S3c §6.1).
//
// 로버에 탄 사람이 밖에 나간 사람을 지켜보고, 후보 옵션 전체를 견주고, 밖에서 온 메모를 읽고 가설을 넣는 화면이다.
// 현장 화면과 마찬가지로 판단이 없다: ConsoleSnapshot을 그리고 누른 것을 ConsoleCmd로 보낸다.
// 구성: 왼쪽 = 레이어 · 지점 · 바탕표 / 가운데 = 지도 / 오른쪽 = 우주인 상태 · 후보 비교 · 고도 단면 · 메모와 가설
import { useState } from "react";
import { BINDING, approx, clock } from "../shared/i18n";
import { DEFAULT_LAYERS, LayerPanel } from "../shared/LayerPanel";
import { MapView } from "../shared/MapView";
import { useMeta, type XY } from "../shared/meta";
import { SimBar } from "../shared/SimBar";
import { useSocket } from "../shared/socket";
import { SourceTip } from "../shared/SourceTip";
import type { ConsoleCmd, ConsoleSnapshot } from "../types";
import { ElevationProfile, OptionCompare } from "./OptionCompare";
import { HypForm, MemoList, PoiList, PriorPanel } from "./Lists";

export function ConsoleApp() {
  const meta = useMeta();
  const { snap, connected, send } = useSocket<ConsoleSnapshot>("/ws/console");
  const [layers, setLayers] = useState<Record<string, boolean>>({ ...DEFAULT_LAYERS, prior: true });
  const [shown, setShown] = useState<string | null>(null);        // 후보 표에서 고른 줄(지도에 그 경로를, 아래에 고도 단면을 보인다)
  const [anchor, setAnchor] = useState<string | null>(null);      // 가설의 기준으로 고른 관측
  const [tab, setTab] = useState<"layers" | "pois" | "prior">("layers");

  if (!meta) return <div className="wait">번들 메타를 읽는 중…</div>;
  if (!snap) return <div className="wait">{connected ? "첫 스냅샷을 기다리는 중…" : "로버 프로그램에 붙는 중…"}<SimBar /></div>;
  const c = snap.crew, st = c.state, n = c.nlt;
  const picked = snap.candidates.find((o) => o.digest === shown) ?? null;
  const onMap = picked ? [picked] : snap.candidates.filter((o) => snap.shown_ids.includes(o.digest));

  return (
    <div className="app console">
      <header className="top">
        <div className="tile"><small>로버 콘솔</small><b>EVA {clock(snap.t)} · LMST {snap.lmst}</b><span>번들 {meta.bundle_id}</span></div>
        <div className={`tile link ${snap.link_up ? "full" : "local"}`}>
          <small>밖에 나간 우주인 {c.node}</small>
          <b>{snap.link_up ? "수신 중" : `응답 없음 · 마지막 수신 ${Math.round(c.last_rx_s)}초 전`}</b>
          {st && <span>위치 ({st.pos[0]}, {st.pos[1]}) · 오차 {st.sigma} m · 기기 표시 {st.link_mode === "LOCAL" ? "로컬 모드" : "연결됨"}</span>}
        </div>
        <div className="tile">
          <small>출발 한계 <SourceTip meta={meta} k="safety.nlt_force_min" /></small>
          {n ? <b>출발까지 {n.slack_min}분 <i>({BINDING[n.binding]})</i></b> : <b>–</b>}
          {n && <span>로버까지 {n.return_dist_m} m · 걸어서 {approx(n.return_time_min)}</span>}
        </div>
        <div className="tile">
          <small>환경</small>
          {st ? <b>먼지 τ {st.tau_dust} <SourceTip meta={meta} k="env.dust_tau_warn" /> · {st.dose_rate} µSv/h{st.spe ? " · SPE" : ""}</b> : <b>–</b>}
          {st && <span>태양 고도 {st.sun_elev}° · 누적 {st.dose_cum_uSv} µSv{st.t_air_c !== null ? ` · 기온 ${st.t_air_c} °C` : ""}</span>}
        </div>
      </header>
      {(snap.alerts.length > 0 || !connected) && <div className="banner">{!connected && <span>로버 프로그램과 끊김 — 마지막 화면입니다.</span>}{snap.alerts.map((a, i) => <span key={i}>{a}</span>)}</div>}

      <main className="cols">
        <aside className="left">
          <nav className="tabs">
            <button type="button" className={tab === "layers" ? "on" : ""} onClick={() => setTab("layers")}>레이어</button>
            <button type="button" className={tab === "pois" ? "on" : ""} onClick={() => setTab("pois")}>지점</button>
            <button type="button" className={tab === "prior" ? "on" : ""} onClick={() => setTab("prior")}>바탕표</button>
          </nav>
          {tab === "layers" && <LayerPanel meta={meta} on={layers} setOn={setLayers} shadowBin={snap.shadow_bin} />}
          {tab === "pois" && <PoiList meta={meta} />}
          {tab === "prior" && <PriorPanel meta={meta} />}
        </aside>
        <MapView meta={meta} layersOn={layers} shadowBin={snap.shadow_bin} pos={(st?.pos as XY | undefined) ?? null} sigma={st?.sigma} rover={snap.rover_pos as XY | null}
          route={c.route as XY[]} plan={c.plan} traces={snap.traces} obs={snap.obs} hyps={snap.hyps} options={onMap} onPickObs={setAnchor} />
        <aside className="right">
          <h3>후보 옵션 <small>— 출발 한계를 통과한 전부. 줄을 누르면 지도와 고도 단면에 보입니다.</small></h3>
          <OptionCompare options={snap.candidates} shownIds={snap.shown_ids} picked={shown} onPick={setShown} />
          {picked && <ElevationProfile o={picked} />}
          <h3>메모와 가설 <small>— 관측을 골라 기준점으로 삼습니다.</small></h3>
          <MemoList obs={snap.obs} anchor={anchor} onPick={setAnchor} />
          <HypForm meta={meta} anchor={anchor} draft={snap.hyp_draft} hyps={snap.hyps} onSend={(m: ConsoleCmd) => send(m)} />
          <h3>최근 결정 지점</h3>
          <ul className="recent">{[...snap.recent_decisions].reverse().map((d) => <li key={d.dp_id}>{d.dp_id} · EVA {clock(d.ts)} · {d.trigger}/{d.cause} · 옵션 {d.options.map((o) => o.id).join(" ")}</li>)}</ul>
        </aside>
      </main>
      <SimBar />
    </div>
  );
}
