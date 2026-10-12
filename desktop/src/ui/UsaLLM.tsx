import { Sparkles } from "lucide-react";
import { useApp } from "./contexto";

/** Indicador "usa seu LLM" ao lado de toda ação que chama o modelo do usuário.
 *  Sem LLM configurado, vira o caminho para Configurações → LLM (a ação ao lado fica desabilitada por quem a usa). */
export default function UsaLLM({ para, detalhe }: { para?: string; detalhe?: string }) {
  const { semLLM, abrir } = useApp();
  if (semLLM)
    return (
      <span className="llm sem">
        <Sparkles size={13} strokeWidth={1.5} aria-hidden />
        Configure um LLM{para ? ` para ${para}` : ""} ·{" "}
        <button onClick={() => abrir("configuracoes", "llm")}>Configurar LLM</button>
      </span>
    );
  return (
    <span className="llm">
      <Sparkles size={13} strokeWidth={1.5} aria-hidden />
      usa seu LLM{detalhe ? ` · ${detalhe}` : ""}
    </span>
  );
}
