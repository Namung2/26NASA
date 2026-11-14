// 프로그램과의 소켓 (S3c §8). 화면은 스냅샷을 받아 그리고, 조작을 명령으로 보낼 뿐이다.
// 명령을 보낸 뒤 답을 기다리지 않는다 — 결과는 다음 스냅샷에 나타난다.
import { useCallback, useEffect, useRef, useState } from "react";

export function useSocket<T>(path: string): { snap: T | null; connected: boolean; send: (msg: unknown) => void } {
  const [snap, setSnap] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const ref = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let timer: number | undefined;
    let latest: T | null = null;
    let frame = 0;
    const open = () => {
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`);
      ref.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        latest = JSON.parse(e.data) as T;
        // 스냅샷은 초당 여러 번 온다. 화면은 0.1초에 한 번, 가장 새것 하나만 그린다
        // (그리기 박자(requestAnimationFrame)에 맞추지 않는다 — 화면이 가려져 있으면 그 박자가 멈춰 스냅샷이 쌓이기만 한다)
        if (!frame) frame = window.setTimeout(() => { frame = 0; setSnap(latest); }, 100);
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(open, 1000);     // 프로그램이 다시 뜨면 붙는다
      };
    };
    open();
    return () => { closed = true; window.clearTimeout(timer); window.clearTimeout(frame); ref.current?.close(); };
  }, [path]);

  const send = useCallback((msg: unknown) => {
    if (ref.current?.readyState === WebSocket.OPEN) ref.current.send(JSON.stringify(msg));
  }, []);
  return { snap, connected, send };
}
