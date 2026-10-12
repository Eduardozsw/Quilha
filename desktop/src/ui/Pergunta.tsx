import { useEffect, useRef, useState } from "react";
import { ArrowUp, Sparkles } from "lucide-react";
import { useApp } from "./contexto";
import { prenderTab } from "./Folha";
import { NAVEGACAO } from "./telas";

const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const ATALHO = MAC ? "⌘K" : "Ctrl K";

type Props = {
  /** a pílula flutuante só aparece nas telas sem documento (Início); nas demais a pergunta abre pelo atalho */
  mostrarPilula: boolean;
  aoPerguntar: (texto: string) => void;
};

/** "Pergunte ao Quilha": pílula no rodapé e folha do Ctrl K (⌘K no macOS) que desce do topo sobre um véu. */
export default function Pergunta({ mostrarPilula, aoPerguntar }: Props) {
  const { abrir } = useApp();
  const [montada, setMontada] = useState(false);
  const [aberta, setAberta] = useState(false);
  const [texto, setTexto] = useState("");
  const campo = useRef<HTMLInputElement>(null);
  const antes = useRef<HTMLElement | null>(null);
  const folha = useRef<HTMLDivElement>(null);
  const saindo = useRef<ReturnType<typeof setTimeout> | null>(null);

  function abrirFolha() {
    // reaberta no meio da saída (< 200 ms): cancela a desmontagem, senão a folha some aberta
    if (saindo.current) {
      clearTimeout(saindo.current);
      saindo.current = null;
    } else {
      antes.current = document.activeElement as HTMLElement | null;
    }
    setMontada(true);
    requestAnimationFrame(() => requestAnimationFrame(() => setAberta(true)));
    setTimeout(() => campo.current?.focus(), 50);
  }

  function fecharFolha() {
    setAberta(false);
    saindo.current = setTimeout(() => {
      saindo.current = null;
      setMontada(false);
      setTexto("");
      antes.current?.focus?.();
    }, 200);
  }

  useEffect(() => {
    function atalho(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (montada && aberta) fecharFolha();
        else abrirFolha();
      } else if (e.key === "Escape" && montada && aberta) fecharFolha();
    }
    window.addEventListener("keydown", atalho);
    return () => window.removeEventListener("keydown", atalho);
  });

  function perguntar(t: string) {
    if (!t.trim()) return;
    fecharFolha();
    aoPerguntar(t.trim());
  }

  const busca = texto.trim().toLowerCase();
  const destinos = [...NAVEGACAO, { id: "configuracoes" as const, nome: "Configurações", icone: null }]
    .filter((t) => !busca || t.nome.toLowerCase().includes(busca));

  return (
    <>
      {mostrarPilula && (
        <button className="pilula" onClick={abrirFolha}>
          <Sparkles size={17} strokeWidth={1.5} aria-hidden />
          <span>Pergunte ao Quilha…</span>
          <span className="tecla">{ATALHO}</span>
          <span className="enviar" aria-hidden><ArrowUp size={16} strokeWidth={2} /></span>
        </button>
      )}
      {montada && (
        <>
          <div className={`veu${aberta ? " aberto" : ""}`} onClick={fecharFolha} />
          <div ref={folha} className={`folha${aberta ? " aberta" : ""}`} role="dialog" aria-modal="true" aria-label="Perguntar ao Quilha"
            onKeyDown={(e) => prenderTab(e, folha.current)}>
            <label htmlFor="pergunta-folha" className="so-leitor">Pergunta</label>
            <input
              id="pergunta-folha"
              ref={campo}
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  perguntar(texto);
                }
              }}
              placeholder="Pergunte ou vá para…"
              autoComplete="off"
            />
            <ul>
              {texto.trim() && (
                <li>
                  <button onClick={() => perguntar(texto)}>
                    <Sparkles size={16} strokeWidth={1.5} aria-hidden />
                    <span className="tx">{texto.trim()}</span>
                    <small>perguntar</small>
                  </button>
                </li>
              )}
              {destinos.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => {
                      fecharFolha();
                      abrir(d.id);
                    }}
                  >
                    {d.icone ? <d.icone size={16} strokeWidth={1.5} aria-hidden /> : <span style={{ width: 16 }} />}
                    <span className="tx">{d.nome}</span>
                    <small>ir para</small>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
