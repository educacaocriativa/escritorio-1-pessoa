import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./app/App";
import "./styles/index.css";

// PWA: registra o service worker que recebe o POST do Web Share Target (Android).
// Ele não faz cache — ver public/sw.js. Falha silenciosa: navegador sem suporte
// (ou http sem TLS) apenas não vira destino de compartilhamento, o app segue normal.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
