/// <reference types="vite/client" />

interface ImportMetaEnv {
  // só no navegador, em desenvolvimento; no app o Tauri informa porta e token
  readonly VITE_HERMES_PORTA?: string;
  readonly VITE_HERMES_TOKEN?: string;
}
