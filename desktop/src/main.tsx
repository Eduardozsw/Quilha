import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import Vitrine from "./ui/Vitrine";
import { aplicarMovimento, lerMovimento } from "./ui/movimento";
import { aplicarTema, lerTema } from "./ui/tema";
import "./estilo.css";
import "./casca.css";
import "./movimento.css";

aplicarTema(lerTema());
aplicarMovimento(lerMovimento());

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {import.meta.env.DEV && new URLSearchParams(location.search).has("vitrine") ? <Vitrine /> : <App />}
  </React.StrictMode>,
);
