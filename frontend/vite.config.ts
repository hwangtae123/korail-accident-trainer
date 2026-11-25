import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중 /api 요청은 FastAPI(8000)로 넘긴다. 그래서 프론트 코드는 항상 상대경로 "/api/..."만 쓴다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
