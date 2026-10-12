import { useEffect, useState } from "react";
import { Briefcase, Check, Clock, FileText, Gauge, Mail, Plus, Send } from "lucide-react";
import { api, eErroDeLLM } from "../api";
import { useCarregar } from "../comum";
import { horas } from "../formato";
import type { CartaoInicio, EstadoConfig, MudancaInicio, Painel } from "../tipos";
import { avisar } from "../ui/Aviso";
import Cabecalho from "../ui/Cabecalho";
import CartaoAcao from "../ui/CartaoAcao";
import { faltaLLM, useApp } from "../ui/contexto";
import Vazio from "../ui/Vazio";

type Props = {
  painel: Painel | null;
  erro: string | null;
  abrirCandidatura: (id?: number) => void;
  aoTriar: () => void;
  aoPerguntar: () => void;
  aoMudar: () => void;
};

const ICONE = { size: 17, strokeWidth: 1.5, "aria-hidden": true } as const;
const POR_EXTENSO = ["", "Uma", "Duas", "Três", "Quatro", "Cinco", "Seis", "Sete", "Oito", "Nove", "Dez"];

/** "Duas coisas", "Dez coisas", "11 coisas" (por extenso até dez). */
function contagem(n: number) {
  return POR_EXTENSO[n] ?? String(n);
}

function lembrar(chave: string): boolean {
  try {
    return localStorage.getItem(chave) === "1";
  } catch {
    return false;
  }
}

function guardar(chave: string) {
  try {
    localStorage.setItem(chave, "1");
  } catch {
    /* sem armazenamento: vale só nesta sessão */
  }
}

function inicioDoDia(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "hoje", "ontem", "seg" (nesta semana) ou "12 de set." */
function relativo(iso: string, agora = new Date()) {
  const d = new Date(iso);
  const dias = Math.round((inicioDoDia(agora) - inicioDoDia(d)) / 86_400_000);
  if (dias <= 0) return "hoje";
  if (dias === 1) return "ontem";
  if (dias < 7) return d.toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "");
  return d.toLocaleDateString("pt-BR", { day: "numeric", month: "short" });
}

/** "desde hoje, 9h30", "desde ontem", "desde segunda", "desde 12 de set." */
function desde(iso: string, agora = new Date()) {
  const d = new Date(iso);
  const dias = Math.round((inicioDoDia(agora) - inicioDoDia(d)) / 86_400_000);
  if (dias <= 0) return `desde hoje, ${d.getHours()}h${d.getMinutes() ? String(d.getMinutes()).padStart(2, "0") : ""}`;
  if (dias === 1) return "desde ontem";
  if (dias < 7) return `desde ${d.toLocaleDateString("pt-BR", { weekday: "long" }).replace("-feira", "")}`;
  return `desde ${d.toLocaleDateString("pt-BR", { day: "numeric", month: "short" })}`;
}

/** "amanhã, 14h", "hoje, 9h30", "sex, 10h" */
function quandoEntrevista(iso: string, agora = new Date()) {
  const d = new Date(iso);
  const dias = Math.round((inicioDoDia(d) - inicioDoDia(agora)) / 86_400_000);
  const dia = dias === 0 ? "hoje" : dias === 1 ? "amanhã" : d.toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "");
  const h = d.getHours(), min = d.getMinutes();
  return `${dia}, ${h}h${min ? String(min).padStart(2, "0") : ""}`;
}

type Passo = { id: "vault" | "llm" | "email" | "vaga"; texto: string; feito: boolean; podePular?: boolean };

function passos(cfg: EstadoConfig | null, painel: Painel | null, emailPulado: boolean): Passo[] {
  const email = cfg ? (cfg.email.origem === "imap" ? !!cfg.email.imap_usuario && cfg.email.imap_senha_definida : cfg.email.gmail_credenciais) : false;
  return [
    { id: "vault", texto: "Escolher a pasta do vault", feito: !!cfg?.pronto },
    { id: "llm", texto: "Conectar seu LLM", feito: !!cfg && !faltaLLM(cfg.llm) },
    { id: "email", texto: "Ligar o e-mail", feito: email || emailPulado, podePular: !email && !emailPulado },
    { id: "vaga", texto: "Avaliar a primeira vaga", feito: (painel?.numeros.vagas_com_requisitos ?? 0) > 0 },
  ];
}

/** Início: o que pede sua atenção hoje, o que mudou desde a última visita, primeiros passos e candidaturas. */
export default function Inicio({ painel, erro, abrirCandidatura, aoTriar, aoPerguntar, aoMudar }: Props) {
  const { abrir } = useApp();
  const config = useCarregar(() => api.get<EstadoConfig>("/api/config"));
  const [emailPulado, setEmailPulado] = useState(() => lembrar("quilha.passos.email-pulado"));
  const [recolhido, setRecolhido] = useState(() => lembrar("quilha.passos.recolhido"));
  const [recolhendo, setRecolhendo] = useState(false);

  const lista = passos(config.dados, painel, emailPulado);
  const feitos = lista.filter((p) => p.feito).length;
  const pendentes = lista.length - feitos;
  const mostrarPassos = !recolhido && !!config.dados;

  // com tudo feito, o cartão recolhe (animação do protótipo) e não volta
  useEffect(() => {
    if (!config.dados || recolhido || pendentes > 0) return;
    const t1 = setTimeout(() => setRecolhendo(true), 500);
    const t2 = setTimeout(() => {
      guardar("quilha.passos.recolhido");
      setRecolhido(true);
    }, 900);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [config.dados, recolhido, pendentes]);

  const cartoes = painel?.pede_acao ?? [];
  const n = painel?.numeros;
  const passosPendentes = mostrarPassos && pendentes > 0;
  // o checklist só vira o conteúdo principal quando nada mais pede ação (quadro "primeiros passos pendentes")
  const passosNoTopo = passosPendentes && !!painel && cartoes.length === 0;
  const titulo = !painel ? "Início"
    : passosPendentes && cartoes.length === 0 ? (pendentes === 1 ? "Falta 1 primeiro passo" : `Faltam ${pendentes} primeiros passos`)
    : cartoes.length === 0 ? "Tudo em dia"
    : cartoes.length === 1 ? "Uma coisa pede sua atenção"
    : `${contagem(cartoes.length)} coisas pedem sua atenção`;
  const status = n ? [
    n.vagas_abertas > 0 && `${n.vagas_abertas} ${n.vagas_abertas === 1 ? "vaga aberta" : "vagas abertas"}`,
    n.candidaturas_ativas > 0 && `${n.candidaturas_ativas} ${n.candidaturas_ativas === 1 ? "candidatura ativa" : "candidaturas ativas"}`,
    n.estudo_minutos > 0 && (
      <button className="link-cab" onClick={() => abrir("competencias", "plano")}>{horas(n.estudo_minutos)} de estudo nesta semana</button>
    ),
  ] : [];
  const hoje = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });

  function pularEmail() {
    guardar("quilha.passos.email-pulado");
    setEmailPulado(true);
  }

  function irPara(p: Passo) {
    if (p.id === "vaga") abrir("vagas");
    else abrir("configuracoes", p.id);
  }

  const cartaoPassos = mostrarPassos && (
    <section className={`passos-inicio checklist-inicio${recolhendo ? " recolhendo" : ""}`} aria-label="Primeiros passos">
      <div className="passos-topo">
        <h2>Primeiros passos</h2>
        <span className="meta tabular">{feitos} de {lista.length}</span>
      </div>
      <div className="barra-passos" aria-hidden><i style={{ transform: `scaleX(${feitos / lista.length})` }} /></div>
      <ul>
        {lista.map((p) => (
          <li key={p.id} className={p.feito ? "feito" : undefined}>
            <button className="passo-inicio" onClick={() => !p.feito && irPara(p)} disabled={p.feito} aria-label={`${p.texto}${p.feito ? " (feito)" : ""}`}>
              <span className="marca" aria-hidden><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg></span>
              <span>{p.texto}</span>
            </button>
            {p.podePular && <button className="btn fant pular" onClick={pularEmail}>Pular</button>}
          </li>
        ))}
      </ul>
    </section>
  );

  return (
    <>
      <Cabecalho contexto={hoje.charAt(0).toUpperCase() + hoje.slice(1)} titulo={titulo} status={status} />
      {erro && <p className="erro-tela">{erro}</p>}
      <div className="inicio">
        <div className="coluna-inicio">
          {passosNoTopo && cartaoPassos}
          <section aria-label="Pede ação">
            <h2>Pede ação</h2>
            {!painel ? (
              <div className="esqueleto-lista" aria-hidden>{[0, 1].map((i) => <span key={i} />)}</div>
            ) : cartoes.length > 0 ? (
              <div className="pilha-acoes">
                {cartoes.map((c, i) => <Cartao key={`${c.tipo}-${i}`} cartao={c} primario={i === 0} abrirCandidatura={abrirCandidatura} aoTriar={aoTriar} aoMudar={aoMudar} />)}
              </div>
            ) : passosPendentes ? (
              <p className="meta">Nada pedindo ação agora. Quando chegar uma vaga boa ou um e-mail de processo, ele aparece aqui.</p>
            ) : (
              <Vazio
                icone={<Check size={20} strokeWidth={1.5} />}
                titulo="Nada pedindo ação agora"
                texto="Quando chegar uma vaga boa ou um e-mail de processo, ele aparece aqui."
                acoes={<>
                  <button className="btn prim" onClick={() => abrir("vagas")}><Plus size={16} strokeWidth={1.5} aria-hidden />Adicionar vaga</button>
                  <button className="btn" onClick={aoPerguntar}>Perguntar ao Quilha</button>
                </>}
              />
            )}
          </section>
          <section aria-label="Desde a sua última visita">
            <h2>Desde a sua última visita</h2>
            {painel && (painel.mudancas.length > 0 ? (
              <ul className="mudancas">
                {painel.mudancas.map((m, i) => <Mudanca key={i} m={m} />)}
              </ul>
            ) : (
              <p className="meta">Nada novo {desde(painel.desde_visita.desde)}</p>
            ))}
          </section>
        </div>
        <div className="coluna-inicio estreita">
          {!passosNoTopo && cartaoPassos}
          {painel && <Etapas etapas={painel.etapas} abrirCandidatura={abrirCandidatura} verTodas={() => abrirCandidatura()} />}
        </div>
      </div>
    </>
  );
}

function Cartao({ cartao: c, primario, abrirCandidatura, aoTriar, aoMudar }: {
  cartao: CartaoInicio; primario: boolean; abrirCandidatura: (id?: number) => void; aoTriar: () => void; aoMudar: () => void;
}) {
  const { semLLM, abrir } = useApp();
  const [ocupado, setOcupado] = useState(false);
  const tipo = primario ? "prim" : "sec";

  if (c.tipo === "entrevista")
    return (
      <CartaoAcao icone={<Clock {...ICONE} />} titulo={`Entrevista ${quandoEntrevista(c.entrevista_em)}`}
        meta={[c.titulo, c.empresa].filter(Boolean).join(" · ")}
        acao={{ rotulo: "Ver candidatura", tipo, onClick: () => abrirCandidatura(c.candidatura_id) }} />
    );
  if (c.tipo === "a_enviar") {
    const id = c.candidatura_id;
    async function marcar() {
      setOcupado(true);
      try {
        await api.post(`/api/candidaturas/${id}/enviada`, {});
        avisar("Candidatura marcada como enviada", { rotulo: "Abrir", onClick: () => abrirCandidatura(id) });
        aoMudar();
      } catch (e) {
        avisar(e instanceof Error ? e.message : String(e));
      } finally {
        setOcupado(false);
      }
    }
    return (
      <CartaoAcao icone={<Send {...ICONE} />} titulo={`${c.empresa ?? "Vaga"}: currículo pronto`}
        meta={[c.titulo, `gerado ${relativo(c.gerado_em)}`, c.outras > 0 && `+${c.outras} ${c.outras === 1 ? "outro" : "outros"} a enviar`].filter(Boolean).join(" · ")}
        acao={{ rotulo: "Marquei como enviada", tipo, onClick: marcar, ocupado }} />
    );
  }
  if (c.tipo === "vaga") {
    async function gerar() {
      setOcupado(true);
      try {
        await api.post("/api/curriculos", { job_id: (c as { job_id: number }).job_id });
        avisar("Currículo gerado · a candidatura fica em “A enviar”", { rotulo: "Abrir", onClick: () => abrir("curriculos") });
        aoMudar();
      } catch (e) {
        avisar(e instanceof Error ? e.message : String(e),
          eErroDeLLM(e) ? { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") } : undefined);
      } finally {
        setOcupado(false);
      }
    }
    return (
      <CartaoAcao icone={<Briefcase {...ICONE} />} titulo={`Vaga nova com score ${c.score}`}
        meta={[c.titulo, c.empresa, `coletada ${relativo(c.coletado_em)}`, c.outras > 0 && `+${c.outras} ${c.outras === 1 ? "outra" : "outras"}`].filter(Boolean).join(" · ")}
        acao={semLLM
          // sem LLM, o botão diz o que falta e leva até lá (desabilitado, não dizia o motivo)
          ? { rotulo: "Configurar o LLM para gerar", tipo, onClick: () => abrir("configuracoes", "llm") }
          : { rotulo: "Gerar currículo", tipo, onClick: gerar, ocupado }} />
    );
  }
  const p = c.primeiro;
  return (
    <CartaoAcao icone={<Mail {...ICONE} />}
      titulo={c.quantos > 1 ? `${c.quantos} e-mails pedem decisão` : `E-mail${p.empresa ? ` da ${p.empresa}` : ""} sem dono`}
      meta={c.quantos > 1 ? `o mais recente: “${p.assunto}”` : `“${p.assunto}” · ${relativo(p.recebido_em)}`}
      acao={{ rotulo: "Triar", tipo, onClick: aoTriar }} />
  );
}

function Mudanca({ m }: { m: MudancaInicio }) {
  let icone, texto;
  switch (m.tipo) {
    case "vagas_boas":
      icone = <Briefcase {...ICONE} />;
      texto = m.quantas === 1 ? "1 vaga nova passou do corte de score" : `${m.quantas} vagas novas passaram do corte de score`;
      break;
    case "avanco":
    case "reprovado":
      icone = <Send {...ICONE} />;
      texto = `${m.empresa ?? "Candidatura"}: ${m.tipo === "avanco" ? "e-mail de avanço" : "reprovação"}`;
      break;
    case "curriculo":
      icone = <FileText {...ICONE} />;
      texto = m.empresa ? `Currículo gerado para ${m.empresa}, ${m.fatos} fatos do vault` : `Currículo base gerado, ${m.fatos} fatos do vault`;
      break;
    case "nivel":
      icone = <Gauge {...ICONE} />;
      texto = `${m.competencia} subiu para nível ${m.nivel}`;
      break;
    case "niveis":
      icone = <Gauge {...ICONE} />;
      texto = `Você declarou ${m.quantos} níveis de competência`;
      break;
  }
  return (
    <li>
      <span className="ic-mudanca">{icone}</span>
      <span className="tx-mudanca">{texto}</span>
      <time className="meta" dateTime={m.quando}>{relativo(m.quando)}</time>
    </li>
  );
}

const NOMES_ETAPA = { a_enviar: "A enviar", entrevista: "Entrevista", em_processo: "Em análise", enviada: "Aguardando resposta" } as const;

function Etapas({ etapas, abrirCandidatura, verTodas }: { etapas: Painel["etapas"]; abrirCandidatura: (id?: number) => void; verTodas: () => void }) {
  const total = Object.values(etapas).reduce((s, e) => s + e.total, 0);
  return (
    <section className="etapas-inicio" aria-label="Candidaturas">
      <div className="passos-topo">
        <h2>Candidaturas</h2>
        {total > 0 && <button className="btn fant" onClick={verTodas}>Ver todas</button>}
      </div>
      {total === 0 ? (
        <p className="meta">Nenhuma candidatura ativa. Gerar o currículo de uma vaga já registra o envio.</p>
      ) : (
        (Object.keys(NOMES_ETAPA) as (keyof typeof NOMES_ETAPA)[]).filter((k) => etapas[k].total > 0).map((k) => (
          <div key={k} className="etapa-inicio">
            <small className="meta">{NOMES_ETAPA[k]} <span className="tabular">{etapas[k].total}</span></small>
            {etapas[k].itens.map((c) => (
              <button key={c.id} className="linha-etapa" onClick={() => abrirCandidatura(c.id)}>
                {[c.empresa, c.titulo].filter(Boolean).join(" · ") || "Candidatura"}
              </button>
            ))}
          </div>
        ))
      )}
    </section>
  );
}

