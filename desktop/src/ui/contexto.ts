import { createContext, useContext } from "react";
import type { IdTela } from "./telas";

/** O que qualquer peça da V3 precisa saber do app sem receber por props: navegar e se há LLM configurado. */
export type ContextoApp = {
  abrir: (tela: IdTela, secao?: string) => void;
  semLLM: boolean;
};

export const Contexto = createContext<ContextoApp>({ abrir: () => {}, semLLM: false });

export const useApp = () => useContext(Contexto);

/** Modelo local (Ollama, LM Studio) não precisa de chave; os demais precisam de modelo e chave. */
/** Modelo que roda na própria máquina (Ollama, LM Studio): não precisa de chave e não custa. */
export function modeloLocal(modelo: string | null | undefined): boolean {
  return !!modelo && /^(ollama|ollama_chat|lm_studio)\//.test(modelo);
}

export function faltaLLM(llm: { modelo: string | null; chave_definida: boolean } | undefined): boolean {
  if (!llm?.modelo) return true;
  return !llm.chave_definida && !modeloLocal(llm.modelo);
}
