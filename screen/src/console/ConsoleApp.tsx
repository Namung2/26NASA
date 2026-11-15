// 로버 콘솔 (계획 화면) — 로버 프로그램의 /ws/console에 붙는다 (S3c §6.1).
//
// 로버에 탄 사람이 밖에 나간 사람을 지켜보고, 후보 옵션 전체를 견주고, 밖에서 온 메모를 읽고 가설을 넣는 화면이다.
// 현장 화면과 마찬가지로 판단이 없다: ConsoleSnapshot을 그리고 누른 것을 ConsoleCmd로 보낸다.
// 구성: 위 = 계기 넷(시각 · 밖에 나간 우주인 · 출발 한계 · 환경) / 왼쪽 = 레이어 · 지점 · 바탕표 / 가운데 = 지도 / 오른쪽 = 후보 비교 · 고도 단면 · 메모와 가설 · 최근 결정 지점
// 모양은 shared/style.css에 있다. 여기서는 받은 값을 어느 자리에 놓을지만 정한다.
import { lazy, Suspense, useState } from "react";
import { BINDING, approx, clock } from "../shared/i18n";
import { DEFAULT_LAYERS, LayerPanel } from "../shared/LayerPanel";
import { Loader } from "../shared/Loader";
import { MapLegend, MapView } from "../shared/MapView";
import { useMeta, type XY } from "../shared/meta";
import { SimBar } from "../shared/SimBar";
import { useSocket } from "../shared/socket";
import { SourceTip } from "../shared/SourceTip";
import type { ConsoleCmd, ConsoleSnapshot } from "../types";
import { ElevationProfile, OptionCompare } from "./OptionCompare";
import { HypForm, MemoList, PoiList, PriorPanel } from "./Lists";

// 3D 지형 보기는 3D를 켤 때만 불러온다(three.js가 크다 — 2D만 쓰는 동안에는 받지 않는다)
const Terrain3D = lazy(() => import("./Terrain3D"));

export function ConsoleApp() {
  const meta = useMeta();
  const { snap, connected, send } = useSocket<ConsoleSnapshot>("/ws/console");
  const [layers, setLayers] = useState<Record<string, boolean>>({ ...DEFAULT_LAYERS, prior: true });
  const [shown, setShown] = useState<string | null>(null);        // 후보 표에서 고른 줄(지도에 그 경로를, 아래에 고도 단면을 보인다)
  const [anchor, setAnchor] = useState<string | null>(null);      // 가설의 기준으로 고른 관측
  const [tab, setTab] = useState<"layers" | "pois" | "prior">("layers");
  const [view, setView] = useState<"2d" | "3d">("2d");            // 지도 칸의 보기. 바꿔도 고른 줄·기준 관측은 그대로다

  if (!meta) return <div className="wait"><Loader label="Reading bundle metadata" /></div>;
  if (!snap) return <div className="wait"><Loader label={connected ? "Waiting for the first snapshot" : "Connecting to the rover program"} /><SimBar /></div>;
  const c = snap.crew, st = c.state, n = c.nlt;
  const picked = snap.candidates.find((o) => o.digest === shown) ?? null;
  const onMap = picked ? [picked] : [];     // 표에서 고른 줄 하나의 경로만 지도에 그린다(여러 선이 한꺼번에 겹치지 않게)

  return (
    <div className="app console">
      <header className="top">
        <div className="brand"><a href="/" title="Back to map and scenario selection"><b>BINGOTIME</b></a><span>ROVER CONSOLE · {meta.bundle_id}</span></div>
        <div className="inst">
          <span className="inst-label">TIME</span>
          <div className="inst-read"><b className="num">{clock(snap.t)}</b><span className="chip plain">LMST {snap.lmst}</span></div>
          <span className="inst-sub">EVA elapsed time</span>
        </div>
        <div className={`inst ${snap.link_up ? "full" : "local"}`}>
          <span className="inst-label">CREW OUTSIDE · {c.node}</span>
          <b className="state">{snap.link_up ? "Receiving" : `No reply · last heard ${Math.round(c.last_rx_s)} s ago`}</b>
          {st && <span className="inst-sub">Position ({st.pos[0]}, {st.pos[1]}) · error {st.sigma} m<span className={`chip ${st.link_mode === "LOCAL" ? "down" : "up"}`}>device shows {st.link_mode === "LOCAL" ? "local mode" : "connected"}</span></span>}
        </div>
        <div className="inst">
          <span className="inst-label">DEPART LIMIT <SourceTip meta={meta} k="safety.nlt_force_min" /></span>
          {n ? <div className="inst-read"><b className="num">{n.slack_min}<u>min left</u></b><span className="chip plain">{BINDING[n.binding]}</span></div> : <b className="state">–</b>}
          {n && <span className="inst-sub"><b>{n.return_dist_m} m</b> to rover · {approx(n.return_time_min)}</span>}
        </div>
        <div className="inst">
          <span className="inst-label">ENVIRONMENT</span>
          {st ? <div className="inst-read"><b className="num">{st.tau_dust}<u>dust τ</u></b><SourceTip meta={meta} k="env.dust_tau_warn" /><span className="chip plain">{st.dose_rate} µSv/h</span>{st.spe && <span className="chip down">SPE</span>}</div> : <b className="state">–</b>}
          {st && <span className="inst-sub">Sun elevation {st.sun_elev}° · total {st.dose_cum_uSv} µSv{st.t_air_c !== null ? ` · air ${st.t_air_c} °C` : ""}</span>}
        </div>
      </header>
      {(snap.alerts.length > 0 || !connected) && <div className="banner">{!connected && <span className="plain"><Loader />Lost the rover program — this is the last screen. Reconnecting</span>}{snap.alerts.map((a, i) => <span key={i}>{a}</span>)}</div>}

      <main className="cols">
        <aside className="left">
          <nav className="tabs">
            <button type="button" className={tab === "layers" ? "on" : ""} onClick={() => setTab("layers")}>LAYERS</button>
            <button type="button" className={tab === "pois" ? "on" : ""} onClick={() => setTab("pois")}>SITES</button>
            <button type="button" className={tab === "prior" ? "on" : ""} onClick={() => setTab("prior")}>PRIOR</button>
          </nav>
          {tab === "layers" && <LayerPanel meta={meta} on={layers} setOn={setLayers} shadowBin={snap.shadow_bin} />}
          {tab === "pois" && <PoiList meta={meta} />}
          {tab === "prior" && <PriorPanel meta={meta} />}
        </aside>
        <div className="mapwrap">
          {view === "2d" ? (
            <>
            <MapView meta={meta} layersOn={layers} shadowBin={snap.shadow_bin} pos={(st?.pos as XY | undefined) ?? null} sigma={st?.sigma} rover={snap.rover_pos as XY | null}
              route={c.route as XY[]} plan={c.plan} traces={snap.traces} obs={snap.obs} hyps={snap.hyps} options={onMap} onPickObs={setAnchor} />
            <MapLegend back={false} />
            </>
          ) : (
            <Suspense fallback={<div className="wait"><Loader label="Loading the 3D view" /></div>}>
              <Terrain3D meta={meta} rev={snap.science_rev} layersOn={layers} shadowBin={snap.shadow_bin} pos={(st?.pos as XY | undefined) ?? null} rover={snap.rover_pos as XY | null}
                plan={c.plan} route={c.route as XY[]} option={picked} obs={snap.obs} />
            </Suspense>
          )}
          <div className="float viewswitch" role="group" aria-label="Map view">
            <button type="button" className={view === "2d" ? "on" : ""} onClick={() => setView("2d")}>2D</button>
            <button type="button" className={view === "3d" ? "on" : ""} onClick={() => setView("3d")}>3D</button>
          </div>
        </div>
        <aside className="right">
          <section className="sec">
            <h3>CANDIDATE OPTIONS <small>— Every one that passes the departure limit. Click a row to show it on the map and the elevation profile.</small></h3>
            <div className="tablewrap"><OptionCompare options={snap.candidates} shownIds={snap.shown_ids} picked={shown} onPick={setShown} /></div>
            {picked && <ElevationProfile o={picked} />}
          </section>
          <section className="sec">
            <h3>NOTES AND HYPOTHESES <small>— Pick an observation to use as the anchor.</small></h3>
            <MemoList obs={snap.obs} anchor={anchor} onPick={setAnchor} />
            <HypForm meta={meta} anchor={anchor} draft={snap.hyp_draft} hyps={snap.hyps} onSend={(m: ConsoleCmd) => send(m)} />
          </section>
          <section className="sec">
            <h3>RECENT DECISION POINTS</h3>
            {snap.recent_decisions.length === 0 && <p className="none">No decision point issued yet.</p>}
            <ul className="recent">{[...snap.recent_decisions].reverse().map((d) => <li key={d.dp_id}>{d.dp_id} · EVA {clock(d.ts)} · {d.trigger}/{d.cause} · options {d.options.map((o) => o.id).join(" ")}</li>)}</ul>
          </section>
        </aside>
      </main>
      <SimBar />
    </div>
  );
}
