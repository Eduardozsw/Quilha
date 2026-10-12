import { useEffect, useId, useRef, useState, type ReactNode } from "react";

type Props = {
  aberta: boolean;
  titulo: string;
  aoFechar: () => void;
  largura?: number;
  rodape?: ReactNode;
  children: ReactNode;
};

const FOCAVEIS = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Prende o Tab dentro de `raiz` (folhas modais): do último volta ao primeiro e vice-versa. */
export function prenderTab(e: React.KeyboardEvent, raiz: HTMLElement | null) {
  if (e.key !== "Tab" || !raiz) return;
  const itens = [...raiz.querySelectorAll<HTMLElement>(FOCAVEIS)];
  if (!itens.length) {
    e.preventDefault();
    return;
  }
  const [primeiro, ultimo] = [itens[0], itens[itens.length - 1]];
  const ativo = document.activeElement;
  if (e.shiftKey && (ativo === primeiro || !raiz.contains(ativo) || ativo === raiz)) {
    e.preventDefault();
    ultimo.focus();
  } else if (!e.shiftKey && (ativo === ultimo || !raiz.contains(ativo))) {
    e.preventDefault();
    primeiro.focus();
  }
}

/** Folha modal que desce do topo sobre um véu (mesmos tempos da folha do Ctrl K).
 *  Esc e clique no véu fecham; o foco entra no primeiro campo, fica preso na folha e volta ao gatilho. */
export default function Folha({ aberta, titulo, aoFechar, largura = 640, rodape, children }: Props) {
  const [montada, setMontada] = useState(aberta);
  const [visivel, setVisivel] = useState(false);
  const folha = useRef<HTMLDivElement>(null);
  const antes = useRef<HTMLElement | null>(null);
  const idTitulo = useId();

  useEffect(() => {
    if (aberta) {
      // reaberta vindo de outra folha (a ida e volta "Mudar nível" → "Ligar um fato" → "Mudar nível"): o foco
      // está num botão da folha que sai; o gatilho de verdade é o de antes, se ainda está na tela
      const ativo = document.activeElement as HTMLElement | null;
      // só a folha que está saindo (sem `.aberta`) conta: de dentro de um diálogo que continua aberto (o balão
      // de procedência, por exemplo), o gatilho é o próprio elemento
      const deOutraFolha = !!ativo?.closest(".folha-v3:not(.aberta)");
      if (!deOutraFolha || !antes.current?.isConnected) antes.current = ativo;
      setMontada(true);
      const q = requestAnimationFrame(() => requestAnimationFrame(() => setVisivel(true)));
      return () => cancelAnimationFrame(q);
    }
    setVisivel(false);
    const t = setTimeout(() => {
      // devolve o foco ao gatilho só se ele não foi para outra folha que abriu no lugar desta
      const ativo = document.activeElement;
      if (!ativo || ativo === document.body || folha.current?.contains(ativo)) antes.current?.focus?.();
      setMontada(false);
    }, 200);
    return () => clearTimeout(t);
  }, [aberta]);

  // depende de `aberta` também: reaberta antes de desmontar (< 200 ms), a folha refaz o foco inicial
  useEffect(() => {
    if (!montada || !aberta) return;
    const t = setTimeout(() => {
      const raiz = folha.current;
      const primeiro = raiz?.querySelector<HTMLElement>("textarea, input, select") ?? raiz?.querySelector<HTMLElement>(FOCAVEIS) ?? raiz;
      primeiro?.focus();
    }, 50);
    return () => clearTimeout(t);
  }, [montada, aberta]);

  // o foco pode cair no body (o botão clicado sumiu ao trocar o rodapé): o Esc ainda fecha a folha aberta
  useEffect(() => {
    if (!aberta) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) aoFechar();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [aberta, aoFechar]);

  function teclado(e: React.KeyboardEvent) {
    if (!aberta) return; // saindo: o Esc é da folha que entra no lugar desta
    if (e.key === "Escape") {
      e.stopPropagation();
      aoFechar();
      return;
    }
    prenderTab(e, folha.current);
  }

  if (!montada) return null;
  return (
    <>
      <div className={`veu${visivel ? " aberto" : ""}`} onClick={aoFechar} />
      <div
        ref={folha}
        className={`folha folha-v3${visivel ? " aberta" : ""}`}
        style={{ width: `min(${largura}px, calc(100% - 32px))` }}
        role="dialog"
        aria-modal="true"
        aria-labelledby={idTitulo}
        tabIndex={-1}
        onKeyDown={teclado}
      >
        <header>
          <h2 id={idTitulo}>{titulo}</h2>
          <button className="tecla" onClick={aoFechar} aria-label="Fechar">Esc</button>
        </header>
        <div className="corpo-folha">{children}</div>
        {rodape && <footer>{rodape}</footer>}
      </div>
    </>
  );
}
