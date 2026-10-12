import { Fragment, useLayoutEffect, useRef, useState, type ReactNode } from "react";

type Props<T> = {
  itens: T[];
  chave: (item: T) => string;
  selecionado: string | null;
  aoSelecionar: (chave: string) => void;
  render: (item: T) => ReactNode;
  /** rótulo do grupo do item; itens seguidos com o mesmo rótulo ficam juntos, com a contagem ao lado */
  grupo?: (item: T) => string;
  /** segunda linha do cabeçalho do grupo (ex.: a nota do recorte em Currículos) */
  detalheGrupo?: (grupo: string) => ReactNode;
  rotulo: string;
};

/** Lista do mestre-detalhe: sem borda entre itens; a seleção é uma pílula `--sel` que desliza (posição e altura). */
export default function ListaSelecao<T>({ itens, chave, selecionado, aoSelecionar, render, grupo, detalheGrupo, rotulo }: Props<T>) {
  const lista = useRef<HTMLDivElement>(null);
  const [pilula, setPilula] = useState<{ y: number; h: number } | null>(null);

  useLayoutEffect(() => {
    function medir() {
      const alvo = selecionado === null ? null
        : lista.current?.querySelector<HTMLElement>(`[data-chave="${CSS.escape(selecionado)}"]`);
      setPilula(alvo ? { y: alvo.offsetTop, h: alvo.offsetHeight } : null);
    }
    medir();
    // a altura de um item muda sem a janela mudar (fonte carregando, texto que quebra): o observador mede de novo
    const observador = new ResizeObserver(medir);
    if (lista.current) {
      observador.observe(lista.current);
      lista.current.querySelectorAll<HTMLElement>(".linha-sel").forEach((l) => observador.observe(l));
    }
    return () => observador.disconnect();
  }, [selecionado, itens]);

  /** ↑↓ andam pela lista selecionando (como o mestre-detalhe do sistema), Home e End vão às pontas. */
  function teclado(e: React.KeyboardEvent) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) || !lista.current) return;
    const opcoes = [...lista.current.querySelectorAll<HTMLElement>('[role="option"]')];
    if (!opcoes.length) return;
    e.preventDefault();
    const atual = opcoes.findIndex((o) => o === document.activeElement || o.dataset.chave === selecionado);
    const alvo = e.key === "Home" ? 0 : e.key === "End" ? opcoes.length - 1
      : Math.min(opcoes.length - 1, Math.max(0, atual + (e.key === "ArrowDown" ? 1 : -1)));
    const o = opcoes[alvo];
    o.focus();
    if (o.dataset.chave !== selecionado) aoSelecionar(o.dataset.chave!);
  }

  const contagem = new Map<string, number>();
  if (grupo) for (const item of itens) contagem.set(grupo(item), (contagem.get(grupo(item)) ?? 0) + 1);

  return (
    <div className="lista-sel" ref={lista} role="listbox" aria-label={rotulo} onKeyDown={teclado}>
      <div className="pilula-lista" style={pilula ? { transform: `translateY(${pilula.y}px)`, height: pilula.h } : { opacity: 0 }} />
      {itens.map((item, i) => {
        const k = chave(item);
        const g = grupo?.(item);
        const novoGrupo = g !== undefined && (i === 0 || grupo!(itens[i - 1]) !== g);
        return (
          <Fragment key={k}>
            {novoGrupo && (
              <div className="grupo" role="presentation">
                <span>{g}</span><span className="tabular">{contagem.get(g!)}</span>
                {detalheGrupo?.(g!) && <small className="detalhe-grupo">{detalheGrupo(g!)}</small>}
              </div>
            )}
            <button
              className="linha-sel"
              data-chave={k}
              role="option"
              aria-selected={k === selecionado}
              onClick={() => aoSelecionar(k)}
            >
              {render(item)}
            </button>
          </Fragment>
        );
      })}
    </div>
  );
}

/** Corpo do documento do mestre-detalhe: troca com fade de 140 ms quando a seleção muda. */
export function DocCorpo({ chave, children }: { chave: string | number | null; children: ReactNode }) {
  return <div key={chave ?? "vazio"} className="doc-corpo troca">{children}</div>;
}
