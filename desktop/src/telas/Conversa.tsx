import { useEffect, useRef, useState } from "react";
import { api, ErroApi, turno } from "../api";
import type { Mensagem, Sessao } from "../tipos";
import { useApp } from "../ui/contexto";
import Cartoes from "./conversa/Cartoes";
import { itensDoHistorico, novaChave, type Item, type TipoErro } from "./conversa/comum";
import Compositor, { type CompositorRef } from "./conversa/Compositor";
import Confirmacao from "./conversa/Confirmacao";
import Fio from "./conversa/Fio";
import Vazio from "./conversa/Vazio";

type Props = {
  sessao?: number;
  /** da pílula ou do Ctrl K: `enviar` manda a pergunta assim que a tela abre */
  inicial?: { texto: string; enviar: boolean };
  aoMudar?: () => void;
  abrirCandidatura?: (id: number) => void;
  /** a conversa que está na tela (aberta ou recém-criada): apagar ela pelas Recentes volta para uma nova */
  aoSessao?: (id: number | null) => void;
};

const TIPOS_ERRO: TipoErro[] = ["llm", "chave", "teto", "outro"];
const PLANO_B_MS = 8000;

/** Os trechos que estavam chegando viram texto final (Markdown) quando o turno termina, para ou falha. */
/** Tira a caixa de erro e os trechos de texto colados antes dela (o que o stream que caiu chegou a escrever). */
function semParcialDoErro(xs: Item[]): Item[] {
  const i = xs.map((x) => x.tipo).lastIndexOf("erro");
  if (i < 0) return xs;
  let j = i;
  while (j > 0 && xs[j - 1].tipo === "texto") j--;
  return [...xs.slice(0, j), ...xs.slice(i + 1)];
}

const fecharTextos = (xs: Item[]): Item[] => xs.map((x) => (x.tipo === "texto" && !x.final ? { ...x, final: true } : x));

/** Conversa da V3: título editável, fio de 720 px com a resposta em streaming e o compositor flutuante. */
export default function Conversa({ sessao, inicial, aoMudar, abrirCandidatura, aoSessao }: Props) {
  const { abrir, semLLM } = useApp();
  const [id, setId] = useState<number | null>(sessao ?? null);
  const [titulo, setTitulo] = useState<string | null>(null);
  const [itens, setItens] = useState<Item[]>([]);
  const [texto, setTexto] = useState(inicial && !inicial.enviar ? inicial.texto : "");
  const [rodando, setRodando] = useState(false);
  const [falhaAbrir, setFalhaAbrir] = useState<string | null>(null);
  useEffect(() => { aoSessao?.(sessao ?? null); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const compositor = useRef<CompositorRef>(null);
  const rolagem = useRef<HTMLDivElement>(null);
  const abortar = useRef<AbortController | null>(null);
  const idAtual = useRef<number | null>(id);
  idAtual.current = id;
  const enviouInicial = useRef(false);

  // aberta pelos "Recentes" da lateral
  useEffect(() => {
    if (sessao === undefined) return;
    Promise.all([api.get<Mensagem[]>(`/api/chat/sessoes/${sessao}/mensagens`), api.get<Sessao[]>("/api/chat/sessoes")])
      .then(([mensagens, sessoes]) => {
        setItens(itensDoHistorico(mensagens));
        setTitulo(sessoes.find((s) => s.id === sessao)?.titulo ?? null);
      }, (e) => setFalhaAbrir(e instanceof Error ? e.message : String(e)));
  }, [sessao]);

  // a pílula e o Ctrl K enviam direto (o StrictMode monta duas vezes: a ref segura o segundo envio)
  useEffect(() => {
    if (inicial?.enviar && inicial.texto.trim() && !enviouInicial.current && !semLLM) {
      enviouInicial.current = true;
      enviar(inicial.texto);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // o fio acompanha o que chega
  useEffect(() => {
    const el = rolagem.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [itens]);

  // sair da tela no meio de uma resposta para o turno no backend (senão ele segue, talvez esperando uma
  // confirmação que ninguém vê). O StrictMode desmonta e remonta na hora: só para se continuar desmontada.
  const montada = useRef(true);
  useEffect(() => {
    montada.current = true;
    return () => {
      montada.current = false;
      setTimeout(() => {
        if (montada.current || !abortar.current) return;
        const sid = idAtual.current;
        if (sid !== null) api.post(`/api/chat/sessoes/${sid}/parar`).catch(() => undefined);
        abortar.current.abort();
      }, 0);
    };
  }, []);

  function aoEvento(tipo: string, dados: any) {
    setItens((xs) => {
      const ultimo = xs[xs.length - 1];
      switch (tipo) {
        case "trecho":
          if (ultimo?.tipo === "texto" && !ultimo.final)
            return [...xs.slice(0, -1), { ...ultimo, trechos: [...ultimo.trechos, dados.texto] }];
          return [...xs, { tipo: "texto", chave: novaChave("texto"), trechos: [dados.texto], final: false }];
        case "tool": {
          const chamada = { nome: dados.nome, rotulo: dados.rotulo ?? null, estado: "rodando" as const };
          if (ultimo?.tipo === "ferramentas") return [...xs.slice(0, -1), { ...ultimo, chamadas: [...ultimo.chamadas, chamada] }];
          return [...fecharTextos(xs), { tipo: "ferramentas", chave: novaChave("ferr"), chamadas: [chamada] }];
        }
        case "tool_resultado":
          return marcarChamada(xs, dados.nome, dados.cancelada ? "cancelada" : dados.ok ? "feito" : "falhou");
        case "confirmar":
          // a linha da ferramenta dá lugar ao cartão de confirmação
          return [...marcarChamada(xs, dados.tool, "cancelada"), {
            tipo: "confirmar", chave: novaChave("conf"), id: dados.id, titulo: dados.titulo ?? "Gravar?",
            campos: dados.campos ?? [], linhas: dados.linhas ?? null, ferramenta: dados.tool,
          }];
        case "confirmacao_resolvida":
          return xs.map((x) => (x.tipo === "confirmar" && x.id === dados.id
            ? { ...x, resultado: dados.resultado, linha: dados.linha, enviando: false } : x));
        case "fim": {
          const fim: Item[] = fecharTextos(xs);
          if (dados.cartoes?.length) fim.push({ tipo: "cartoes", chave: novaChave("cartoes"), cartoes: dados.cartoes });
          fim.push({ tipo: "rodape", chave: novaChave("rodape"), custo: dados.custo?.custo_usd ?? null, parado: dados.parou_por === "parado" });
          return fim;
        }
        case "erro":
          return [...fecharTextos(xs), {
            tipo: "erro", chave: novaChave("erro"), erro: TIPOS_ERRO.includes(dados.tipo) ? dados.tipo : "outro",
            mensagem: dados.mensagem ?? dados.erro ?? "", pergunta: perguntaAtual.current,
            gasto: dados.gasto_usd, teto: dados.teto_usd,
          }];
        default:
          return xs;
      }
    });
    if (tipo === "fim" && dados.titulo) setTitulo(dados.titulo);
  }

  const perguntaAtual = useRef("");

  async function enviar(pergunta: string, repetir = false) {
    const limpa = pergunta.trim();
    if (!limpa || rodando) return;
    perguntaAtual.current = limpa;
    setTexto("");
    setRodando(true);
    // "Tentar de novo" reenvia a mesma pergunta: o balão fica, as ferramentas e confirmações que aconteceram
    // ficam (estão no banco); saem a caixa de erro e o texto parcial logo antes dela, como no histórico gravado
    setItens((xs) => (repetir
      ? semParcialDoErro(xs)
      : [...xs, { tipo: "voce", chave: novaChave("voce"), texto: limpa, voa: true }]));
    const controle = new AbortController();
    abortar.current = controle;
    try {
      let sid = idAtual.current;
      if (sid === null) {
        sid = (await api.post<{ id: number }>("/api/chat/sessoes")).id;
        setId(sid);
        idAtual.current = sid;
        aoSessao?.(sid);
      }
      await turno(sid, limpa, aoEvento, controle.signal);
    } catch (e) {
      if (controle.signal.aborted) {
        // plano B do "Parar" (o backend não terminou a tempo): o texto parcial fica, marcado "Parado", e a
        // confirmação que estava aberta conta como recusada, que é o que o backend grava
        setItens((xs) => [
          ...fecharTextos(xs).map((x) => (x.tipo === "confirmar" && !x.resultado
            ? { ...x, resultado: "recusado" as const, enviando: false, linha: x.linhas?.recusado ?? "Não gravado" } : x)),
          { tipo: "rodape", chave: novaChave("rodape"), custo: null, parado: true },
        ]);
      } else if (e instanceof ErroApi) {
        // pedido recusado pela API (ex.: 409, a resposta anterior ainda terminando): não é o provedor
        aoEvento("erro", { tipo: "outro", mensagem: `${e.message.charAt(0).toUpperCase()}${e.message.slice(1)}.` });
      } else {
        aoEvento("erro", { tipo: "llm", mensagem: e instanceof Error ? e.message : String(e) });
      }
    } finally {
      clearTimeout(planoB.current);
      abortar.current = null;
      setRodando(false);
      aoMudar?.();
      compositor.current?.focar();
    }
  }

  /** "Parar": o backend para no próximo trecho ou entre ferramentas e termina com `fim` (parado, custo, título);
   *  a tela continua lendo até lá, para não aceitar outra pergunta com o turno ainda rodando. Se o backend
   *  não terminar em 8 s (esperando o provedor), o plano B aborta a leitura. */
  const planoB = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  async function parar() {
    const controle = abortar.current;
    if (!controle) return;
    const sid = idAtual.current;
    let pediu = false;
    if (sid !== null) pediu = await api.post(`/api/chat/sessoes/${sid}/parar`).then(() => true, () => false);
    if (!pediu) controle.abort();
    else planoB.current = setTimeout(() => controle.abort(), PLANO_B_MS);
  }

  /** Clique no cartão de confirmação. O resultado chega pelo SSE (`confirmacao_resolvida`); 404 = o pedido
   *  já expirou (5 min) e a linha "Expirou · … não gravada" aparece sem deixar clicar de novo. */
  async function responder(pedido: string, aprovar: boolean) {
    const mudar = (f: (x: Item & { tipo: "confirmar" }) => Item) =>
      setItens((xs) => xs.map((x) => (x.tipo === "confirmar" && x.id === pedido ? f(x) : x)));
    mudar((x) => ({ ...x, enviando: true }));
    try {
      await api.post(`/api/chat/confirmacoes/${pedido}`, { aprovar });
    } catch (e) {
      if (e instanceof ErroApi && e.status === 404)
        mudar((x) => (x.resultado ? x : { ...x, enviando: false, resultado: "expirou",
          linha: x.linhas?.expirou ?? "Expirou · não gravado" }));
      else mudar((x) => ({ ...x, enviando: false }));
    }
  }

  async function renomear(novo: string) {
    if (id === null) return;
    try {
      const s = await api.put<Sessao>(`/api/chat/sessoes/${id}/titulo`, { titulo: novo });
      setTitulo(s.titulo);
      aoMudar?.();
    } catch {
      /* o título antigo continua */
    }
  }

  const vazia = itens.length === 0 && !falhaAbrir;
  return (
    <div className="conversa">
      <header className="conversa-topo">
        <TituloEditavel titulo={titulo ?? "Nova conversa"} editavel={id !== null && titulo !== null} aoSalvar={renomear} />
      </header>
      <div className="conversa-rolagem" ref={rolagem}>
        {vazia ? (
          <Vazio aoSugerir={(s) => { setTexto(s); compositor.current?.focar(); }} />
        ) : (
          <Fio
            itens={itens}
            rodando={rodando}
            origemVoo={() => compositor.current?.retangulo() ?? null}
            tentarDeNovo={(p) => enviar(p, true)}
            abrirConfiguracoes={() => abrir("configuracoes", "llm")}
            extras={(item) => {
              if (item.tipo === "confirmar") return <Confirmacao item={item} responder={responder} />;
              if (item.tipo === "cartoes")
                return <Cartoes cartoes={item.cartoes} abrirCandidatura={(c) => (abrirCandidatura ? abrirCandidatura(c) : abrir("candidaturas"))} />;
              return null;
            }}
          />
        )}
        {falhaAbrir && <p className="falha-abrir">Não deu para abrir esta conversa: {falhaAbrir}</p>}
      </div>
      <Compositor ref={compositor} texto={texto} aoMudar={setTexto} aoEnviar={() => enviar(texto)} aoParar={parar} rodando={rodando} />
    </div>
  );
}

/** Muda a última chamada rodando com esse nome. A que deu lugar a um cartão de confirmação já está
 *  `cancelada` e fica assim: a linha da confirmação conta o que aconteceu. */
function marcarChamada(xs: Item[], nome: string, estado: "feito" | "falhou" | "cancelada"): Item[] {
  for (let i = xs.length - 1; i >= 0; i--) {
    const x = xs[i];
    if (x.tipo !== "ferramentas") continue;
    const j = x.chamadas.map((c) => c.nome === nome && c.estado === "rodando").lastIndexOf(true);
    if (j < 0) continue;
    const chamadas = x.chamadas.map((c, k) => (k === j ? { ...c, estado } : c));
    return xs.map((y, k) => (k === i ? { ...x, chamadas } : y));
  }
  return xs;
}

/** O título no topo: clique edita no lugar; Enter grava, Esc cancela; vazio volta ao automático (a primeira pergunta). */
function TituloEditavel({ titulo, editavel, aoSalvar }: { titulo: string; editavel: boolean; aoSalvar: (t: string) => void }) {
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(titulo);
  const campo = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editando) campo.current?.select();
  }, [editando]);

  if (!editando)
    return editavel ? (
      <button className="titulo-conversa" onClick={() => { setValor(titulo); setEditando(true); }} title="Renomear a conversa">
        {titulo}
      </button>
    ) : (
      <span className="titulo-conversa">{titulo}</span>
    );
  return (
    <input
      ref={campo}
      className="titulo-conversa editando"
      aria-label="Título da conversa"
      value={valor}
      onChange={(e) => setValor(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          setEditando(false);
          if (valor.trim() !== titulo) aoSalvar(valor);
        } else if (e.key === "Escape") {
          setEditando(false);
        }
      }}
      onBlur={() => setEditando(false)}
    />
  );
}
