import { MessageSquare } from "lucide-react";
import Botao from "../../ui/Botao";
import { useApp } from "../../ui/contexto";
import { SUGESTOES } from "./comum";

/** Conversa vazia: o que a Conversa faz e três sugestões que vão para o campo (sem enviar). Sem LLM, o convite. */
export default function Vazio({ aoSugerir }: { aoSugerir: (texto: string) => void }) {
  const { semLLM, abrir } = useApp();
  return (
    <div className="conversa-vazia">
      <span className="ic-vazio"><MessageSquare size={18} strokeWidth={1.5} aria-hidden /></span>
      <h2>Pergunte ao Quilha</h2>
      {semLLM ? (
        <>
          <p>Configure seu LLM para conversar. O Quilha usa a sua chave: você escolhe o provedor e vê o custo de cada resposta.</p>
          <Botao tipo="prim" onClick={() => abrir("configuracoes", "llm")}>Abrir configurações</Botao>
        </>
      ) : (
        <>
          <p>Ele responde com o que está no seu vault, nas vagas e nas candidaturas. Cada resposta usa o seu LLM.</p>
          <div className="sugestoes">
            {SUGESTOES.map((s) => <button key={s} onClick={() => aoSugerir(s)}>{s}</button>)}
          </div>
        </>
      )}
    </div>
  );
}
