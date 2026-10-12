import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import { ArrowUp, Sparkles, Square } from "lucide-react";
import { useApp } from "../../ui/contexto";

export type CompositorRef = { focar: () => void; retangulo: () => DOMRect | null };

type Props = {
  texto: string;
  aoMudar: (t: string) => void;
  aoEnviar: () => void;
  aoParar: () => void;
  rodando: boolean;
};

/** Compositor flutuante da Conversa: textarea (Enter envia, Shift+Enter quebra), "usa seu LLM" e enviar circular.
 *  Enquanto o Quilha responde, "Parar" fica no lugar do enviar. Sem LLM, só "Configurar LLM" em âmbar. */
const Compositor = forwardRef<CompositorRef, Props>(function Compositor({ texto, aoMudar, aoEnviar, aoParar, rodando }, ref) {
  const { semLLM, abrir } = useApp();
  const campo = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({
    focar: () => campo.current?.focus(),
    retangulo: () => campo.current?.getBoundingClientRect() ?? null,
  }));

  // cresce com o texto até ~6 linhas
  useLayoutEffect(() => {
    const el = campo.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [texto]);

  const podeEnviar = !rodando && !semLLM && texto.trim().length > 0;
  return (
    <div className="compositor">
      <label htmlFor="compositor-campo" className="so-leitor">Mensagem</label>
      <textarea
        id="compositor-campo"
        ref={campo}
        rows={1}
        value={texto}
        placeholder="Pergunte ao Quilha sobre vagas, currículos ou candidaturas…"
        onChange={(e) => aoMudar(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (podeEnviar) aoEnviar();
          }
        }}
      />
      <div className="barra">
        {semLLM ? (
          <button className="llm sem configurar" onClick={() => abrir("configuracoes", "llm")}>
            <Sparkles size={13} strokeWidth={1.5} aria-hidden />Configurar LLM
          </button>
        ) : (
          <span className="llm"><Sparkles size={13} strokeWidth={1.5} aria-hidden />usa seu LLM</span>
        )}
        {rodando ? (
          <button className="enviar parar" onClick={aoParar} aria-label="Parar" title="Parar">
            <Square size={12} strokeWidth={0} fill="currentColor" aria-hidden />
          </button>
        ) : (
          <button className="enviar" onClick={aoEnviar} disabled={!podeEnviar} aria-label="Enviar" title="Enviar">
            <ArrowUp size={16} strokeWidth={2} aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
});

export default Compositor;
