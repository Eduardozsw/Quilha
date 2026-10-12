import { useCallback, useEffect, useRef, useState } from "react";
import { api, esperarHermes, marcarVisita, marcarVisitaAoFechar } from "./api";
import { useCarregar } from "./comum";
import { Logo } from "./marca";
import type { EstadoConfig, Painel, Sessao } from "./tipos";
import Aviso, { avisar } from "./ui/Aviso";
import { Contexto, faltaLLM } from "./ui/contexto";
import Lateral from "./ui/Lateral";
import Pergunta from "./ui/Pergunta";
import Tour, { tourVisto, useEventoTour } from "./ui/Tour";
import { TELAS, type IdTela } from "./ui/telas";
import Candidaturas from "./telas/Candidaturas";
import Competencias from "./telas/Competencias";
import Conversa from "./telas/Conversa";
import Curriculos from "./telas/Curriculos";
import BoasVindas from "./telas/BoasVindas";
import Inicio from "./telas/Inicio";
import Configuracoes from "./telas/Configuracoes";
import { SECOES, type IdSecao } from "./telas/config/pecas";
import Vagas from "./telas/Vagas";

const ESTREITA = "(max-width: 900px)";

function lembrada(): IdTela {
  try {
    const salva = localStorage.getItem("quilha.tela");
    if (TELAS.includes(salva as IdTela)) return salva as IdTela;
  } catch {
    /* sem armazenamento: começa no início */
  }
  return "inicio";
}

function secaoLembrada(): IdSecao {
  try {
    const salva = localStorage.getItem("quilha.config.secao");
    if (SECOES.includes(salva as IdSecao)) return salva as IdSecao;
  } catch {
    /* sem armazenamento: começa no vault */
  }
  return "vault";
}

function estreita() {
  return typeof matchMedia === "function" && matchMedia(ESTREITA).matches;
}

/** Abaixo de 900 px a lateral começa recolhida; ao cruzar a largura, ela acompanha. */
function useRecolhida() {
  const [recolhida, setRecolhida] = useState(estreita);
  useEffect(() => {
    const mq = matchMedia(ESTREITA);
    const mudou = (e: MediaQueryListEvent) => setRecolhida(e.matches);
    mq.addEventListener("change", mudou);
    return () => mq.removeEventListener("change", mudou);
  }, []);
  return [recolhida, () => setRecolhida((r) => !r)] as const;
}

export default function App() {
  const [pronto, setPronto] = useState(false);
  const [falha, setFalha] = useState<string | null>(null);
  const [recolhida, alternar] = useRecolhida();

  const [config, setConfig] = useState<EstadoConfig | null>(null);
  const [comTour, setComTour] = useState(false);

  useEffect(() => {
    esperarHermes()
      .then(() => api.get<EstadoConfig>("/api/config"))
      .then((c) => { setConfig(c); setPronto(true); }, (e) => setFalha(e instanceof Error ? e.message : String(e)));
  }, []);

  // primeira abertura: sem vault escolhido, as boas-vindas vêm antes de tudo
  if (pronto && config && !config.configurado)
    return <BoasVindas config={config} aoConcluir={() => { setConfig({ ...config, configurado: true }); setComTour(true); }}
      aoRecarregar={() => api.get<EstadoConfig>("/api/config").then(setConfig, () => undefined)} />;
  if (pronto) return <Casca recolhida={recolhida} alternar={alternar} comTour={comTour} />;
  // o backend congelado leva alguns segundos para subir: a janela já mostra a lateral, sem tela branca
  return (
    <div className={`app${recolhida ? " recolhida" : ""}`}>
      <Lateral tela="inicio" abrir={() => {}} novaConversa={() => {}} recentes={[]} abrirRecente={() => {}}
        usuario={{ nome: " " }} recolhida={recolhida} alternar={alternar} />
      <main className="principal">
        <div className="abrindo" role="status">
          <div>
            <Logo tamanho={40} />
            {falha ? <p className="falha">{falha}</p> : <p>Abrindo o Quilha…</p>}
          </div>
        </div>
      </main>
    </div>
  );
}

/** O app depois que a API respondeu: lateral e a tela aberta, que entra com fade e sobe 6 px. */
function Casca({ recolhida, alternar, comTour }: { recolhida: boolean; alternar: () => void; comTour: boolean }) {
  // o tour abre depois das boas-vindas, ou na primeira abertura de quem nunca o viu; sempre na Início
  const [tela, setTela] = useState<IdTela>(() => (comTour || !tourVisto() ? "inicio" : lembrada()));
  const [tour, setTour] = useState(false);
  useEffect(() => {
    if (!comTour && tourVisto()) return;
    const t = setTimeout(() => setTour(true), 700); // deixa a Início montar: os alvos precisam existir
    return () => clearTimeout(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // pelo `abrir` (lido no momento do pedido): recarrega o painel e lembra a tela, como qualquer navegação
  const abrirAgora = useRef<(id: IdTela) => void>(() => {});
  const pedirTour = useCallback(() => {
    abrirAgora.current("inicio");
    setTimeout(() => setTour(true), 400);
  }, []);
  useEventoTour(pedirTour);
  const [vez, setVez] = useState(0);
  const [pergunta, setPergunta] = useState<{ texto: string; enviar: boolean } | undefined>();
  const [sessao, setSessao] = useState<number | undefined>();
  const [candidatura, setCandidatura] = useState<number | undefined>();
  // Competências: o slug que abre selecionado, ou "plano" para a folha do plano da semana (Estudos não é mais tela)
  const [alvoComp, setAlvoComp] = useState<string | undefined>();
  const [modoCand, setModoCand] = useState<"lista" | "triagem">("lista");
  // "Abrir a vaga" e "Abrir o currículo" da candidatura: o id do item que a tela abre selecionado
  const [alvo, setAlvo] = useState<number | undefined>();
  const painel = useCarregar(() => api.get<Painel>("/api/inicio"));
  const perfil = useCarregar(() => api.get<{ nome?: string }>("/api/perfil"));
  const sessoes = useCarregar(() => api.get<Sessao[]>("/api/chat/sessoes"));
  const config = useCarregar(() => api.get<EstadoConfig>("/api/config"));
  const [secaoConfig, setSecaoConfig] = useState<IdSecao>(secaoLembrada);
  const semLLM = config.dados ? faltaLLM(config.dados.llm) : false;

  const nome = perfil.dados?.nome?.trim() || null;
  const indice = painel.dados?.indice;
  const recentes = (sessoes.dados ?? [])
    .filter((s) => s.n_mensagens > 0)
    .slice(0, 6)
    .map((s) => ({ id: s.id, titulo: s.titulo ?? `Conversa ${s.id}` }));

  // a visita é marcada ao sair da Início (e ao fechar o app nela), nunca ao abrir: quem abre e fecha rápido
  // não perde as novidades que ainda não leu
  const telaAtual = useRef(tela);
  telaAtual.current = tela;
  // o horário do resumo que a Início mostrou; sem resumo carregado, nada foi visto e nada é marcado
  const resumoVisto = useRef<string | null>(null);
  resumoVisto.current = painel.dados?.agora ?? null;
  useEffect(() => {
    const visto = () => (telaAtual.current === "inicio" ? resumoVisto.current : null);
    // navegador: `pagehide` com keepalive
    const aoFechar = () => {
      const quando = visto();
      if (quando) marcarVisitaAoFechar(quando);
    };
    window.addEventListener("pagehide", aoFechar);
    // app: o Tauri não dispara `pagehide` ao fechar a janela; o pedido de fechar espera a marca terminar
    let soltar: (() => void) | undefined;
    if ("__TAURI_INTERNALS__" in window) {
      import("@tauri-apps/api/window").then(({ getCurrentWindow }) =>
        getCurrentWindow().onCloseRequested(async () => {
          const quando = visto();
          if (quando) await marcarVisita(quando);
        })).then((f) => { soltar = f; }, () => undefined);
    }
    return () => {
      window.removeEventListener("pagehide", aoFechar);
      soltar?.();
    };
  }, []);

  function trocarSecao(s: IdSecao) {
    setSecaoConfig(s);
    try {
      localStorage.setItem("quilha.config.secao", s);
    } catch {
      /* ignora */
    }
  }

  abrirAgora.current = (id) => abrir(id);
  function abrir(id: IdTela, secao?: string) {
    if (tela === "inicio" && id !== "inicio" && painel.dados) marcarVisita(painel.dados.agora);
    setTela(id);
    setVez((v) => v + 1);
    if (id === "inicio") painel.recarregar();
    // entrar em Configurações recarrega o que ela mostra; sair recarrega o `semLLM` das outras telas
    if (id === "configuracoes" || tela === "configuracoes") config.recarregar();
    if (id === "configuracoes" && secao && SECOES.includes(secao as IdSecao)) trocarSecao(secao as IdSecao);
    setAlvo(id === "vagas" || id === "curriculos" ? Number(secao) || undefined : undefined);
    setAlvoComp(id === "competencias" ? secao : undefined);
    if (id === "candidaturas") {
      setModoCand(secao === "triagem" ? "triagem" : "lista");
      // pela lateral (ou na triagem) não volta na última candidatura aberta por um atalho; `abrirCandidatura`
      // escolhe a dela depois desta linha
      setCandidatura(undefined);
    }
    try {
      localStorage.setItem("quilha.tela", id);
    } catch {
      /* ignora */
    }
  }

  /** A pílula e o Ctrl K mandam a pergunta e ela já sai (decisão do PM); "Nova conversa" abre vazia. */
  function novaConversa(texto?: string, enviar = true) {
    setSessao(undefined);
    setPergunta(texto ? { texto, enviar } : undefined);
    abrir("conversa");
  }

  // a conversa que está na tela agora (a Conversa avisa, inclusive a recém-criada)
  const conversaNaTela = useRef<number | null>(null);

  async function renomearRecente(id: number, titulo: string) {
    try {
      await api.put(`/api/chat/sessoes/${id}/titulo`, { titulo });
      sessoes.recarregar();
    } catch (e) {
      avisar(e instanceof Error ? e.message : String(e));
    }
  }

  async function apagarRecente(id: number) {
    try {
      await api.del(`/api/chat/sessoes/${id}`);
      avisar("Conversa apagada");
      if (tela === "conversa" && conversaNaTela.current === id) novaConversa();
      sessoes.recarregar();
    } catch (e) {
      avisar(e instanceof Error ? e.message : String(e));
    }
  }

  function abrirRecente(id: number) {
    setPergunta(undefined);
    setSessao(id);
    abrir("conversa");
  }

  function abrirCandidatura(id?: number) {
    abrir("candidaturas");
    setCandidatura(id);
  }

  let conteudo;
  let cheia = false;
  if (tela === "inicio")
    conteudo = <Inicio painel={painel.dados} erro={painel.erro} abrirCandidatura={abrirCandidatura}
      aoTriar={() => abrir("candidaturas", "triagem")} aoPerguntar={() => novaConversa()} aoMudar={painel.recarregar} />;
  else if (tela === "conversa") {
    cheia = true;
    conteudo = <Conversa key={`${sessao}-${vez}`} inicial={pergunta} sessao={sessao} aoMudar={sessoes.recarregar} aoSessao={(s) => { conversaNaTela.current = s; }}
      abrirCandidatura={abrirCandidatura} />;
  } else if (tela === "vagas") conteudo = <Vagas inicial={alvo} />;
  else if (tela === "curriculos") conteudo = <Curriculos inicial={alvo} />;
  else if (tela === "configuracoes")
    conteudo = <Configuracoes secao={secaoConfig} aoTrocarSecao={trocarSecao} config={config.dados}
      recarregarConfig={config.recarregar} />;
  else if (tela === "candidaturas")
    conteudo = <Candidaturas key={`${candidatura}-${vez}`} inicial={candidatura} modo={modoCand} aoMudar={painel.recarregar} />;
  else conteudo = <Competencias key={`${alvoComp}-${vez}`} inicial={alvoComp} aoMudar={painel.recarregar} />;

  return (
    <Contexto.Provider value={{ abrir, semLLM }}>
      <div className={`app${recolhida ? " recolhida" : ""}`}>
        <Lateral
          tela={tela}
          abrir={abrir}
          novaConversa={() => novaConversa()}
          recentes={recentes}
          recenteAtiva={sessao}
          abrirRecente={abrirRecente}
          renomearRecente={renomearRecente}
          apagarRecente={apagarRecente}
          usuario={{ nome: nome ?? "Perfil sem nome", detalhe: indice ? `${indice.notas} notas no vault` : undefined }}
          recolhida={recolhida}
          alternar={alternar}
        />
        <main className="principal">
          <section key={`${tela}-${vez}`} className={`tela entrando${cheia ? " cheia" : ""}`}>
            {conteudo}
          </section>
          <Pergunta mostrarPilula={tela === "inicio"} aoPerguntar={(t) => novaConversa(t)} />
        <Tour aberto={tour} aoFechar={() => setTour(false)} />
        </main>
      </div>
      <Aviso />
    </Contexto.Provider>
  );
}
