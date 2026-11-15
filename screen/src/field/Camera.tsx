// 촬영 창 — 기기의 카메라를 켜서 한 장 찍고, 기기 프로그램에 올린다 (S2 §사진: 파일은 기기에 둔다).
//
// 화면이 하는 일은 셋뿐이다: 카메라 그림을 보여 주기, 찍은 한 장을 JPEG로 보내기(POST /photo), 찍어 둔 사진 목록을 받아 보여 주기(GET /photos).
// 사진의 내용은 읽지 않는다. 어디서 언제 찍었는지(위치·시각·이벤트 번호)는 프로그램이 채운다.
//
// 카메라를 못 켜는 경우(허락하지 않음, 카메라 없음, https가 아닌 주소)에는 그 사정을 적고 "파일 고르기"를 남긴다 —
// 휴대 기기에서는 이것이 기본 카메라 앱을 연다. 사진 없이 흔적만 남기는 단추도 둔다(전에 "촬영"이 하던 일).
import { useCallback, useEffect, useRef, useState } from "react";
import { clock } from "../shared/i18n";
import { Loader } from "../shared/Loader";

type Shot = { event_id: string; url: string; t: number; xy: [number, number] };
type Cam = "starting" | "live" | "blocked";

// 그림(영상 한 장면이나 고른 파일)을 JPEG 한 장으로 만든다. 크기는 원본 그대로다
function toJpeg(src: CanvasImageSource, w: number, h: number): Promise<Blob | null> {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  c.getContext("2d")?.drawImage(src, 0, 0, w, h);
  return new Promise((done) => c.toBlob(done, "image/jpeg", 0.9));
}

export function CameraPanel({ onTraceOnly, onClose }: { onTraceOnly: () => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [cam, setCam] = useState<Cam>("starting");
  const [why, setWhy] = useState("");                 // 카메라를 못 켠 까닭(브라우저가 알려 준 이름)
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [shots, setShots] = useState<Shot[]>([]);
  const [open, setOpen] = useState<Shot | null>(null);  // 크게 보는 사진

  const reload = useCallback(() => {
    fetch("/photos").then((r) => (r.ok ? r.json() : [])).then((x: Shot[]) => setShots(x)).catch(() => undefined);
  }, []);
  useEffect(reload, [reload]);

  // 카메라 켜기. 창을 닫으면 반드시 끈다(카메라 표시등이 남지 않게)
  useEffect(() => {
    let stream: MediaStream | null = null, gone = false;
    if (!navigator.mediaDevices?.getUserMedia) { setCam("blocked"); setWhy("This address cannot use the camera (needs https or localhost)."); return undefined; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
      .then((s) => {
        if (gone) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        if (video.current) { video.current.srcObject = s; video.current.play().catch(() => undefined); }
        setCam("live");
      })
      .catch((e: DOMException) => { if (!gone) { setCam("blocked"); setWhy(e.name === "NotAllowedError" ? "Camera permission was not granted." : e.name === "NotFoundError" ? "No camera was found on this device." : `Camera could not start (${e.name}).`); } });
    return () => { gone = true; stream?.getTracks().forEach((t) => t.stop()); };
  }, []);

  const upload = async (blob: Blob | null) => {
    if (!blob) { setError("Could not make an image."); return; }
    setBusy(true); setError("");
    try {
      const r = await fetch("/photo", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob });
      if (!r.ok) setError(`Not saved (${r.status}). ${(await r.json().catch(() => ({})) as { detail?: string }).detail ?? ""}`);
      else reload();
    } catch { setError("Not saved — the device program did not answer."); }
    setBusy(false);
  };
  const shoot = () => { const v = video.current; if (v && v.videoWidth) void toJpeg(v, v.videoWidth, v.videoHeight).then(upload); };
  const pick = async (f: File | undefined) => {
    if (!f) return;
    try { const bmp = await createImageBitmap(f); await upload(await toJpeg(bmp, bmp.width, bmp.height)); bmp.close(); }
    catch { setError("That file is not an image this browser can read."); }
  };

  return (
    <div className="panel wide camera">
      <h3>Photo <small>— Saved on the device with this position and time. A trace is left on the map.</small></h3>
      <div className="viewfinder">
        <video ref={video} playsInline muted style={{ display: cam === "live" ? "block" : "none" }} />
        {cam === "starting" && <Loader label="Starting the camera" />}
        {cam === "blocked" && <p className="none">{why}</p>}
      </div>
      {error && <p className="missing">{error}</p>}
      <div className="row">
        <button type="button" disabled={cam !== "live" || busy} onClick={shoot}>Take photo</button>
        <label className="filepick">Choose file<input type="file" accept="image/*" capture="environment" disabled={busy} onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} /></label>
        <button type="button" disabled={busy} onClick={onTraceOnly}>Trace only</button>
        <button type="button" onClick={onClose}>Close</button>
        {busy && <Loader label="Saving" />}
      </div>
      <div className="shots">
        <small>PHOTOS THIS EVA · {shots.length}</small>
        {shots.length === 0 && <p className="none">No photos yet.</p>}
        <ul>
          {[...shots].reverse().map((s) => (
            <li key={s.url}>
              <button type="button" onClick={() => setOpen(s)} title={`${s.event_id} · (${s.xy[0]}, ${s.xy[1]})`}><img src={s.url} alt={`Photo ${s.event_id}`} /><span>EVA {clock(s.t)}</span></button>
            </li>
          ))}
        </ul>
      </div>
      {open && (
        <div className="lightbox" role="dialog" aria-label={`Photo ${open.event_id}`} onClick={() => setOpen(null)}>
          <img src={open.url} alt={`Photo ${open.event_id}`} />
          <p>{open.event_id} · EVA {clock(open.t)} · ({open.xy[0]}, {open.xy[1]}) <button type="button" onClick={() => setOpen(null)}>Close</button></p>
        </div>
      )}
    </div>
  );
}
