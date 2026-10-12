import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";

const CHAVE = "quilha.tour.visto";
const EVENTO = "quilha:tour";
const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function tourVisto(): boolean {
  try {
    return localStorage.getItem(CHAVE) === "1";
  } catch {
    return false;
  }
}

export function marcarTourVisto(): void {
  try {
    localStorage.setItem(CHAVE, "1");
  } catch {
    /* sem armazenamento: o tour pode voltar na próxima abertura */
  }
}

/** Para Configurações → Ajuda/Sobre ("Ver tour de novo"). A casca escuta e abre o tour na Início. */
export function reabrirTour(): void {
  window.dispatchEvent(new Event(EVENTO));
}

export function useEventoTour(aoPedir: () => void) {
  useEffect(() => {
    window.addEventListener(EVENTO, aoPedir);
    return () => window.removeEventListener(EVENTO, aoPedir);
  }, [aoPedir]);
}

type Lado = "direita" | "esquerda" | "acima";
type Passo = { alvo: string; lado: Lado; titulo: string; corpo: () => ReactNode; largura?: number };

const TELAS: [string, string][] = [
  ["Início", "o que pede sua atenção hoje"],
  ["Conversa", "perguntar qualquer coisa ao Quilha"],
  ["Vagas", "avaliar vagas contra seu vault"],
  ["Candidaturas", "acompanhar respostas e etapas"],
  ["Currículos", "sob medida, com a fonte de cada linha"],
  ["Competências", "provar e fechar lacunas"],
  ["Configurações", "vault, LLM e e-mail"],
];

const NUMERO = ["", "um", "dois", "três", "quatro"];

function passosFaltando(): string {
  const faltam = [...document.querySelectorAll<HTMLElement>(".checklist-inicio li:not(.feito) .passo-inicio span:last-child")]
    .map((s) => { const t = s.textContent?.trim() ?? ""; return t.charAt(0).toLowerCase() + t.slice(1); });
  if (!faltam.length) return "Os primeiros passos mostram o que falta configurar.";
  const lista = faltam.length === 1 ? faltam[0] : `${faltam.slice(0, -1).join(", ")} e ${faltam[faltam.length - 1]}`;
  return `${faltam.length === 1 ? "Falta um passo" : `Faltam ${NUMERO[faltam.length] ?? faltam.length} passos`}: ${lista}.`;
}

const PASSOS: Passo[] = [
  {
    alvo: ".lateral .nav", lado: "direita", titulo: "Tudo o que o Quilha faz", largura: 400,
    corpo: () => <dl className="telas-tour">{TELAS.map(([t, d]) => <div key={t}><dt>{t}</dt><dd>{d}</dd></div>)}</dl>,
  },
  {
    alvo: ".pilula", lado: "acima", titulo: "Pergunte de qualquer tela",
    corpo: () => <p>Escreva aqui ou aperte {MAC ? "⌘K" : "Ctrl K"}. O Quilha responde com base no seu vault e nas suas vagas.</p>,
  },
  {
    alvo: "[data-tela=vagas]", lado: "direita", titulo: "Daqui sai o currículo sob medida",
    corpo: () => <p>Cole uma vaga e o Quilha mostra o que o seu vault cobre. Com um clique, sai o currículo para ela.</p>,
  },
  // o checklist recolhendo não conta: em instantes ele some da tela
  { alvo: ".checklist-inicio:not(.recolhendo)", lado: "esquerda", titulo: "Comece por aqui", corpo: () => <p>{passosFaltando()}</p> },
];

const FOCAVEIS = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

/** Tour de 4 passos depois da primeira abertura: recorta o alvo (o resto escurece, sem blur) e explica. */
export default function Tour({ aberto, aoFechar }: { aberto: boolean; aoFechar: () => void }) {
  // a lista de passos é decidida ao abrir e não muda mais: a contagem "N de M" fica estável
  const [passos, setPassos] = useState<Passo[]>([]);
  const [i, setI] = useState(0);
  const [caixa, setCaixa] = useState<DOMRect | null>(null);
  const balao = useRef<HTMLDivElement>(null);
  const passo = passos[i];

  useEffect(() => {
    if (!aberto) {
      setPassos([]);
      return;
    }
    setI(0);
    // espera os alvos aparecerem (a Início pode estar carregando), até 2 s
    const inicio = Date.now();
    const t = window.setInterval(() => {
      const presentes = PASSOS.filter((p) => document.querySelector(p.alvo));
      if (presentes.length === PASSOS.length || Date.now() - inicio > 2000) {
        window.clearInterval(t);
        setPassos(presentes);
      }
    }, 100);
    return () => window.clearInterval(t);
  }, [aberto]);

  useLayoutEffect(() => {
    if (!aberto || !passo) return;
    const medir = () => {
      const alvo = document.querySelector(passo.alvo);
      if (!alvo) {
        // o alvo sumiu (o checklist recolheu): segue para o próximo, ou termina
        if (i < passos.length - 1) setI(i + 1);
        else fechar();
        return;
      }
      setCaixa(alvo.getBoundingClientRect());
    };
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, [aberto, passo]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (aberto && passo) setTimeout(() => balao.current?.querySelector<HTMLElement>(".btn.prim")?.focus(), 60);
  }, [aberto, passo]);

  // teclado na janela inteira enquanto o tour está aberto: Esc e Tab valem mesmo depois de um clique no véu,
  // e o Ctrl K não abre a folha de pergunta por baixo do tour
  useEffect(() => {
    if (!aberto) return;
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        fechar();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        e.stopImmediatePropagation();
      } else if (e.key === "Tab" && balao.current) {
        const itens = [...balao.current.querySelectorAll<HTMLElement>(FOCAVEIS)];
        if (!itens.length) return;
        const [primeiro, ultimo] = [itens[0], itens[itens.length - 1]];
        const dentro = balao.current.contains(document.activeElement);
        if (!dentro || (e.shiftKey && document.activeElement === primeiro)) { e.preventDefault(); (e.shiftKey ? ultimo : primeiro).focus(); }
        else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primeiro.focus(); }
      }
    };
    window.addEventListener("keydown", tecla, true);
    return () => window.removeEventListener("keydown", tecla, true);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  function fechar() {
    marcarTourVisto();
    aoFechar();
  }

  function proximo() {
    if (i >= passos.length - 1) fechar();
    else setI(i + 1);
  }

  if (!aberto || !passo || !caixa) return null;
  const folga = 8;
  const recorte: CSSProperties = {
    transform: `translate(${caixa.left - folga}px, ${caixa.top - folga}px)`,
    width: caixa.width + folga * 2, height: caixa.height + folga * 2,
  };
  const L = passo.largura ?? 340;
  // o lado pedido, ou o outro quando não cabe (o checklist pode estar na coluna esquerda ou na direita)
  const cabeEsquerda = caixa.left - L - 24 >= 16;
  const cabeDireita = caixa.right + 24 + L <= window.innerWidth - 16;
  const lado: Lado = passo.lado === "esquerda" && !cabeEsquerda ? (cabeDireita ? "direita" : "acima")
    : passo.lado === "direita" && !cabeDireita ? (cabeEsquerda ? "esquerda" : "acima") : passo.lado;
  const topo = Math.max(16, Math.min(caixa.top - 8, window.innerHeight - 380));
  const pos: CSSProperties =
    lado === "direita" ? { left: caixa.right + 24, top: topo }
    : lado === "esquerda" ? { left: caixa.left - L - 24, top: topo }
    : { left: Math.max(16, Math.min(caixa.left + caixa.width / 2 - L / 2, window.innerWidth - L - 16)), bottom: window.innerHeight - caixa.top + 24 };

  return createPortal(
    <div className="tour">
      <div className="tour-bloqueio" onClick={(e) => { e.stopPropagation(); balao.current?.querySelector<HTMLElement>(".btn.prim")?.focus(); }} />
      <div className="tour-recorte" style={recorte} aria-hidden />
      <div key={i} ref={balao} className="tour-balao" style={{ ...pos, width: L }} role="dialog" aria-modal="true" aria-labelledby="tour-titulo">
        <h2 id="tour-titulo">{passo.titulo}</h2>
        <div className="corpo-tour">{passo.corpo()}</div>
        <div className="rodape-tour">
          <span className="meta tabular">{i + 1} de {passos.length}</span>
          <button className="btn fant" onClick={fechar}>Pular</button>
          <button className="btn prim" onClick={proximo}>{i >= passos.length - 1 ? "Começar" : "Próximo"}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
