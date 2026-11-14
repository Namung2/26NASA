// 화면 빌드 설정. 페이지가 둘이다: field.html(현장 화면, 기기 프로그램에 붙는다), console.html(로버 콘솔, 로버 프로그램에 붙는다).
// 개발 서버(npm run dev)로 띄울 때는 소켓·번들·시뮬 조작을 파이썬 서버(sim.live, 8000번)로 넘긴다.
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    rollupOptions: { input: { index: resolve(__dirname, "index.html"), field: resolve(__dirname, "field.html"), console: resolve(__dirname, "console.html") } },
  },
  server: {
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      "/bundle": "http://127.0.0.1:8000",
      "/sim": "http://127.0.0.1:8000",
    },
  },
});
