import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, Search } from "lucide-react";

export type ItemMenu = {
  rotulo: string;
  icone?: ReactNode;
  dica?: ReactNode;
  aoEscolher: () => void;
  desabilitado?: boolean;
  marcado?: boolean;
  perigo?: boolean;
  /** linha separadora antes deste item */
  separado?: boolean;
};

type Props = {
  rotulo: string;
  gatilho: ReactNode;
  classeGatilho?: string;
  itens: ItemMenu[];
  busca?: boolean;
  alinhamento?: "direita" | "esquerda";
};

/** Menu flutuante: ↑↓ andam, Enter escolhe, Esc e clique fora fecham; o foco volta ao gatilho. */
export default function Menu({ rotulo, gatilho, classeGatilho = "btn-icone", itens, busca = false, alinhamento = "direita" }: Props) {
  const [aberto, setAberto] = useState(false);
  const [filtro, setFiltro] = useState("");
  const [ativo, setAtivo] = useState(0);
  const [peloTeclado, setPeloTeclado] = useState(false);
  const [posicao, setPosicao] = useState<CSSProperties>({});
  const raiz = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const campo = useRef<HTMLInputElement>(null);
  const lista = useRef<HTMLDivElement>(null);
  const flutuante = useRef<HTMLDivElement>(null);
  const dentro = (alvo: EventTarget | null) =>
    alvo instanceof Node && (!!raiz.current?.contains(alvo) || !!flutuante.current?.contains(alvo));
  const id = useId();

  const visiveis = itens.filter((i) => !filtro.trim() || i.rotulo.toLowerCase().includes(filtro.trim().toLowerCase()));

  // fixo na janela: o documento rola e recorta o que flutua dentro dele
  useLayoutEffect(() => {
    if (!aberto || !botao.current) return;
    const r = botao.current.getBoundingClientRect();
    const altura = (busca ? 46 : 0) + Math.min(itens.length, 9) * 34 + 24;
    const cabeEmbaixo = r.bottom + 6 + altura < window.innerHeight - 8;
    setPosicao({
      position: "fixed",
      ...(cabeEmbaixo ? { top: r.bottom + 6, bottom: "auto" } : { top: "auto", bottom: window.innerHeight - r.top + 6 }),
      ...(alinhamento === "direita" ? { right: window.innerWidth - r.right, left: "auto" } : { left: r.left, right: "auto" }),
    });
    const aoMover = (e: Event) => {
      if (dentro(e.target)) return; // rolar a própria lista não fecha
      fechar(false);
    };
    window.addEventListener("resize", aoMover);
    window.addEventListener("scroll", aoMover, true);
    return () => {
      window.removeEventListener("resize", aoMover);
      window.removeEventListener("scroll", aoMover, true);
    };
  }, [aberto]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (!dentro(e.target)) fechar(false);
    };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    setAtivo(Math.max(0, visiveis.findIndex((i) => !i.desabilitado)));
    setTimeout(() => (busca ? campo.current : lista.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])'))?.focus({ preventScroll: true }), 0);
  }, [aberto]); // eslint-disable-line react-hooks/exhaustive-deps

  function fechar(devolverFoco = true) {
    setAberto(false);
    setFiltro("");
    if (devolverFoco) botao.current?.focus({ preventScroll: true });
  }

  function escolher(item: ItemMenu) {
    if (item.desabilitado) return;
    fechar();
    item.aoEscolher();
  }

  function teclado(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      fechar();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setPeloTeclado(true);
      if (!visiveis.length) return;
      const passo = e.key === "ArrowDown" ? 1 : -1;
      let i = ativo;
      for (let n = 0; n < visiveis.length; n++) {
        i = (i + passo + visiveis.length) % visiveis.length;
        if (!visiveis[i].desabilitado) break;
      }
      setAtivo(i);
      if (!busca) lista.current?.querySelectorAll<HTMLElement>('[role="menuitem"]')[i]?.focus({ preventScroll: true });
    } else if (e.key === "Enter" && visiveis[ativo]) {
      e.preventDefault();
      escolher(visiveis[ativo]);
    } else if (e.key === "Tab") {
      // o foco volta ao gatilho antes de o navegador andar: o Tab segue dali, não do fim da página
      fechar();
    }
  }

  return (
    <div className="menu-raiz" ref={raiz}>
      <button
        ref={botao}
        className={`${classeGatilho}${aberto ? " ativo" : ""}`}
        aria-label={rotulo}
        title={rotulo}
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? id : undefined}
        onClick={() => (aberto ? fechar() : setAberto(true))}
      >
        {gatilho}
      </button>
      {aberto && createPortal(
        <div ref={flutuante} className={`menu-v3 ${alinhamento}`} style={posicao} id={id} role="menu" aria-label={rotulo} onKeyDown={teclado}>
          {busca && (
            <label className="busca-menu">
              <Search size={16} strokeWidth={1.5} aria-hidden />
              <input ref={campo} value={filtro} onChange={(e) => { setFiltro(e.target.value); setAtivo(0); }}
                placeholder="Buscar" aria-label={`Buscar em ${rotulo}`}
                aria-controls={id} aria-activedescendant={visiveis[ativo] ? `${id}-${ativo}` : undefined} />
            </label>
          )}
          <div ref={lista}>
            {visiveis.map((item, i) => (
              <div key={`${i}-${item.rotulo}`}>
                {item.separado && <div className="sep-menu" role="separator" />}
                <button
                  role="menuitem"
                  id={`${id}-${i}`}
                  className={`item-menu${i === ativo ? " ativo" : ""}${i === ativo && peloTeclado ? " foco" : ""}${item.perigo ? " perigo" : ""}`}
                  disabled={item.desabilitado}
                  tabIndex={-1}
                  onMouseEnter={() => { setAtivo(i); setPeloTeclado(false); }}
                  onClick={() => escolher(item)}
                >
                  <span className={`ic-menu${item.marcado ? " marcado" : ""}`} aria-hidden>{item.marcado ? <Check size={16} strokeWidth={2} /> : item.icone}</span>
                  <span className="tx">{item.rotulo}</span>
                  {item.dica && <span className="dica">{item.dica}</span>}
                </button>
              </div>
            ))}
            {!visiveis.length && <div className="nada-menu">Nada com esse nome.</div>}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
