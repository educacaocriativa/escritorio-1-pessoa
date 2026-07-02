import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Escuta em TODAS as interfaces (IPv4 0.0.0.0 + IPv6). Sem isto o Vite fica só em ::1
    // (IPv6) e o navegador, que resolve localhost como 127.0.0.1 (IPv4), não conecta → tela
    // em branco / "não aparece".
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
