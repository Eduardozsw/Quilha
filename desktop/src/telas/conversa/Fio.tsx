import { useLayoutEffect, useRef } from "react";
import { Check, Search } from "lucide-react";
import { Markdown } from "../../comum";
import Botao from "../../ui/Botao";
import { formatarCusto, frasesFerramentas, semMovimento, type Item, type TipoErro } from "./comum";

type Props = {
  itens: Item[];
  rodando: boolean;
  /** de onde o balão novo sai voando: o campo do compositor */
  origemVoo: () => DOMRect | null;
  tentarDeNovo: (pergunta: string) => void;
  abrirConfiguracoes: () => void;
  extras?: (item: Item) => React.ReactNode;
};

/** O fio da conversa: coluna de 720 px com perguntas em balão e respostas em texto corrido. */
export default function Fio({ itens, rodando, origemVoo, tentarDeNovo, abrirConfiguracoes, extras }: Props) {
  const ultimo = itens[itens.length - 1];
  // enquanto nada chegou depois da pergunta, três pontos dizem que o Quilha está trabalhando
  const esperando = rodando && (ultimo?.tipo === "voce" || (ultimo?.tipo === "ferramentas" && !frasesFerramentas(ultimo.chamadas).rodando));
  return (
    <div className="fio" aria-live="polite">
      {itens.map((item) => {
        switch (item.tipo) {
          case "voce":
            return <Balao key={item.chave} texto={item.texto} voa={!!item.voa} origem={origemVoo} />;
          case "ferramentas":
            return <LinhaFerramenta key={item.chave} item={item} />;
          case "texto":
            return item.final ? (
              <div key={item.chave} className="resposta"><Markdown texto={item.trechos.join("")} /></div>
            ) : (
              <p key={item.chave} className="resposta corrente">
                {item.trechos.map((t, i) => <span key={i} className="frase">{t}</span>)}
              </p>
            );
          case "resolvida":
            return <LinhaConfirmacao key={item.chave} gravado={item.resultado === "gravado"} linha={item.linha} />;
          case "rodape": {
            const custo = formatarCusto(item.custo);
            if (!custo && !item.parado) return null;
            return <p key={item.chave} className="custo-resposta">{[item.parado ? "Parado" : null, custo].filter(Boolean).join(" · ")}</p>;
          }
          case "erro":
            return <CaixaErro key={item.chave} item={item} tentarDeNovo={tentarDeNovo} abrirConfiguracoes={abrirConfiguracoes} />;
          default:
            return extras ? <div key={item.chave} style={{ display: "contents" }}>{extras(item)}</div> : null;
        }
      })}
      {esperando && <p className="pensando" role="status" aria-label="O Quilha está respondendo"><i /><i /><i /></p>}
    </div>
  );
}

/** O balão do usuário. Ao enviar, voa do campo até o lugar no fio (240 ms). */
function Balao({ texto, voa, origem }: { texto: string; voa: boolean; origem: () => DOMRect | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    const de = voa ? origem() : null;
    if (!el || !de || semMovimento() || typeof el.animate !== "function") return;
    const para = el.getBoundingClientRect();
    const dx = de.left + 16 - para.left;
    const dy = de.top + 12 - para.top;
    el.animate(
      [{ transform: `translate(${dx}px, ${dy}px)`, opacity: 0.4 }, { transform: "none", opacity: 1 }],
      { duration: 240, easing: "cubic-bezier(.2,.8,.2,1)" },
    );
    // só na montagem: o voo é a chegada do balão
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <div ref={ref} className="balao">{texto}</div>;
}

function LinhaFerramenta({ item }: { item: Item & { tipo: "ferramentas" } }) {
  const { rodando, feito, falhou } = frasesFerramentas(item.chamadas);
  if (!rodando && !feito && !falhou) return null;
  return (
    <div className="linha-ferramenta">
      {rodando ? (
        <p><Search size={14} strokeWidth={1.5} aria-hidden />{rodando}</p>
      ) : feito ? (
        <p><Search size={14} strokeWidth={1.5} aria-hidden />{feito}</p>
      ) : null}
      {falhou && <p className="falhou"><Search size={14} strokeWidth={1.5} aria-hidden />{falhou}</p>}
    </div>
  );
}

export function LinhaConfirmacao({ gravado, linha }: { gravado: boolean; linha: string }) {
  return (
    <p className={`linha-confirmacao${gravado ? " gravado" : ""}`}>
      {gravado && <Check size={14} strokeWidth={2} aria-hidden />}
      {linha}
    </p>
  );
}

const ERROS: Record<TipoErro, { titulo: string; acao: "repetir" | "config" }> = {
  llm: { titulo: "O provedor do LLM não respondeu", acao: "repetir" },
  chave: { titulo: "O provedor recusou a sua chave", acao: "config" },
  teto: { titulo: "Parei antes de passar do teto de custo", acao: "config" },
  outro: { titulo: "Algo deu errado nesta resposta", acao: "repetir" },
};

const dolar = (v: number) => {
  const casas = v < 0.1 ? 3 : 2;
  return `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}`;
};

function textoDoErro(item: Item & { tipo: "erro" }): string {
  if (item.erro === "llm") return "Sem conexão ou o serviço está fora do ar. A sua pergunta continua aqui.";
  if (item.erro === "chave") return "Confira a chave em Configurações → LLM. A sua pergunta continua aqui.";
  if (item.erro === "teto")
    return (item.teto != null && item.gasto != null
      ? `O teto é de ${dolar(item.teto)} por pergunta, e esta já gastou ${dolar(item.gasto)}. `
      : "") + "A resposta parou aqui. Aumente o teto em Configurações ou faça uma pergunta mais curta.";
  return `${item.mensagem} A sua pergunta continua aqui.`;
}

/** Erro dentro do fio: só o título em cor de erro, o parágrafo em `--texto-2`; o balão da pergunta fica. */
function CaixaErro({ item, tentarDeNovo, abrirConfiguracoes }: {
  item: Item & { tipo: "erro" }; tentarDeNovo: (p: string) => void; abrirConfiguracoes: () => void;
}) {
  const { titulo, acao } = ERROS[item.erro];
  return (
    <div className="caixa-erro cresce" role="alert">
      <strong>{titulo}</strong>
      <p>{textoDoErro(item)}</p>
      <div>
        {acao === "repetir"
          ? <Botao onClick={() => tentarDeNovo(item.pergunta)}>Tentar de novo</Botao>
          : <Botao onClick={abrirConfiguracoes}>Abrir configurações</Botao>}
      </div>
    </div>
  );
}
