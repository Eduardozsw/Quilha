import { useEffect, useState } from "react";
import {
  AlertCircle, BookOpen, Briefcase, Calendar, CalendarX, ChevronDown, Copy, FileText, MoreHorizontal, Pencil, RotateCcw,
  RotateCw, Send, Tag, XCircle,
} from "lucide-react";
import { api, eErroDeLLM } from "../../api";
import { useCarregar } from "../../comum";
import type { Competencia, DetalheCandidatura, DetalheVaga, PerfilCurriculo, VagaLista } from "../../tipos";
import { avisar } from "../../ui/Aviso";
import Botao from "../../ui/Botao";
import { useApp } from "../../ui/contexto";
import Menu, { type ItemMenu } from "../../ui/Menu";
import UsaLLM from "../../ui/UsaLLM";
import { SeletorPerfil } from "./Folhas";
import { mensagem, nomeDa, quandoMarco } from "./comum";

const ICONE = { size: 16, strokeWidth: 1.5, "aria-hidden": true } as const;

type Base = { detalhe: DetalheCandidatura; aoMudar: () => void };

type PropsMenu = Base & {
  aoEditar: (modo: "titulo" | "perfil") => void;
  aoEntrevista: () => void;
  /** depois do "Desfazer" do "Não vou enviar": a candidatura que voltou fica selecionada */
  aoVoltar: (id: number) => void;
};

/** Menu "⋯" ao lado do selo (decisão 4): editar, trocar perfil, abrir a vaga e o currículo; cancelar em tijolo, com Desfazer. */
export function MenuCandidatura({ detalhe, aoMudar, aoEditar, aoEntrevista, aoVoltar }: PropsMenu) {
  const { abrir } = useApp();
  const c = detalhe.candidatura;

  async function cancelar() {
    const anterior = c.status;
    try {
      await api.post(`/api/candidaturas/${c.id}/cancelar`);
      aoMudar();
      avisar("Candidatura cancelada", {
        rotulo: "Desfazer",
        onClick: async () => {
          try {
            await api.post(`/api/candidaturas/${c.id}/reabrir`, { anterior });
            aoMudar();
          } catch (e) {
            avisar(mensagem(e));
          }
        },
      });
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  /** "Não vou enviar" (PM): o rascunho sai da lista; o Desfazer devolve a mesma candidatura. */
  async function naoVouEnviar() {
    try {
      const r = await api.del<{ rascunho: unknown }>(`/api/candidaturas/${c.id}`);
      aoMudar();
      avisar("Candidatura removida", {
        rotulo: "Desfazer",
        onClick: async () => {
          try {
            await api.post("/api/candidaturas/rascunho", { rascunho: r.rascunho });
            aoVoltar(c.id);
          } catch (e) {
            avisar(mensagem(e));
          }
        },
      });
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  async function reabrir() {
    try {
      await api.post(`/api/candidaturas/${c.id}/reabrir`, {});
      aoMudar();
      avisar("Candidatura reaberta");
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  async function desmarcar() {
    try {
      await api.put(`/api/candidaturas/${c.id}/entrevista`, { quando: null });
      aoMudar();
      avisar("Entrevista desmarcada");
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  const itens: ItemMenu[] = [
    { rotulo: "Editar título", icone: <Pencil {...ICONE} />, aoEscolher: () => aoEditar("titulo") },
    { rotulo: "Trocar perfil", icone: <Tag {...ICONE} />, aoEscolher: () => aoEditar("perfil") },
  ];
  if (c.entrevista_em)
    itens.push(
      { rotulo: "Remarcar entrevista", icone: <Calendar {...ICONE} />, aoEscolher: aoEntrevista },
      { rotulo: "Desmarcar entrevista", icone: <CalendarX {...ICONE} />, aoEscolher: desmarcar },
    );
  itens.push(
    { rotulo: "Abrir a vaga", icone: <Briefcase {...ICONE} />, desabilitado: !c.job_id,
      dica: c.job_id ? undefined : "sem vaga gravada", aoEscolher: () => abrir("vagas", String(c.job_id)) },
    { rotulo: "Abrir o currículo", icone: <FileText {...ICONE} />, desabilitado: !detalhe.cv,
      dica: detalhe.cv ? undefined : "sem currículo", aoEscolher: () => abrir("curriculos", String(detalhe.cv!.id)) },
  );
  itens.push(c.status === "cancelada"
    ? { rotulo: "Reabrir candidatura", icone: <RotateCcw {...ICONE} />, separado: true, aoEscolher: reabrir }
    : c.status === "a_enviar"
      ? { rotulo: "Não vou enviar", icone: <XCircle {...ICONE} />, perigo: true, separado: true, aoEscolher: naoVouEnviar }
      : { rotulo: "Cancelar candidatura", icone: <XCircle {...ICONE} />, perigo: true, separado: true, aoEscolher: cancelar });

  return <Menu rotulo="Mais ações" gatilho={<MoreHorizontal size={16} strokeWidth={2} aria-hidden />} itens={itens} />;
}

/** "Já mandou o currículo?" (decisão 8): só depois de marcar ela conta como candidatura. */
export function CartaoAEnviar({ detalhe, aoMudar }: Base) {
  const { abrir } = useApp();
  const [ocupado, setOcupado] = useState(false);
  const c = detalhe.candidatura;

  async function marcar() {
    setOcupado(true);
    try {
      await api.post(`/api/candidaturas/${c.id}/enviada`, {});
      aoMudar();
      avisar("Candidatura marcada como enviada");
    } catch (e) {
      avisar(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="cartao-acao cartao-cand">
      <span className="ic" aria-hidden><Send size={16} strokeWidth={1.5} /></span>
      <div className="tx">
        <b>Já mandou o currículo?</b>
        <span>Ela só conta como candidatura depois que você marcar. Os e-mails da empresa já se ligam a ela.</span>
      </div>
      <div className="botoes">
        {detalhe.cv && <Botao tipo="fant" onClick={() => abrir("curriculos", String(detalhe.cv!.id))}>Abrir o currículo</Botao>}
        <Botao tipo="prim" onClick={marcar} ocupado={ocupado}>Marquei como enviada</Botao>
      </div>
    </div>
  );
}

type PropsPingada = Base & { perfis: PerfilCurriculo[]; aoJuntar: (destino: number) => void };

/** Pingada (decisão 5): primeiro "É a candidatura X? · Juntar", depois "Complete esta candidatura" em uma linha. */
export function AvisoPingada({ detalhe, aoMudar, perfis, aoJuntar }: PropsPingada) {
  const c = detalhe.candidatura;
  const parecida = detalhe.parecidas[0];
  const [cargo, setCargo] = useState("");
  const [perfil, setPerfil] = useState("");
  const [ocupado, setOcupado] = useState<null | "juntar" | "salvar">(null);

  async function juntar() {
    if (!parecida) return;
    setOcupado("juntar");
    try {
      await api.post(`/api/candidaturas/${c.id}/juntar`, { destino: parecida.id });
      aoJuntar(parecida.id);
      avisar(`Juntada com ${nomeDa({ ...parecida, origem: "manual" })}`);
    } catch (e) {
      avisar(mensagem(e));
      setOcupado(null);
    }
  }

  async function salvar() {
    setOcupado("salvar");
    try {
      if (cargo.trim()) await api.put(`/api/candidaturas/${c.id}/titulo`, { titulo: cargo.trim() });
      if (perfil) await api.put(`/api/candidaturas/${c.id}/perfil`, { perfil });
      aoMudar();
      avisar("Candidatura completada");
    } catch (e) {
      avisar(mensagem(e));
    } finally {
      setOcupado(null);
    }
  }

  const nomeParecida = parecida ? nomeDa({ ...parecida, origem: "manual" }) : "";
  return (
    <section className="aviso-pingada" aria-label="Candidatura nascida de um e-mail">
      {parecida && (
        <>
          <b>É a candidatura {nomeParecida}?</b>
          <p>Este e-mail é {c.empresa ? `de ${c.empresa}` : "da mesma empresa"}, e você já tem uma candidatura ativa lá. Juntar evita uma cópia.</p>
          <Botao onClick={juntar} ocupado={ocupado === "juntar"} disabled={ocupado !== null}>Juntar com {nomeParecida}</Botao>
          <hr />
        </>
      )}
      <b className={parecida ? "sub-pingada" : undefined}>{parecida ? "Não é a mesma? Complete esta candidatura:" : "Complete esta candidatura"}</b>
      <form className="linha-pingada" onSubmit={(e) => { e.preventDefault(); if (cargo.trim() || perfil) salvar(); }}>
        <label className="rotulo-campo" htmlFor="pg-cargo">Cargo
          <input id="pg-cargo" className="campo" value={cargo} onChange={(e) => setCargo(e.target.value)} autoComplete="off" />
        </label>
        <label className="rotulo-campo" htmlFor="pg-perfil">Perfil do currículo
          <SeletorPerfil id="pg-perfil" valor={perfil} perfis={perfis} aoMudar={setPerfil} vazio="Escolha um recorte" />
        </label>
        <Botao submit ocupado={ocupado === "salvar"} disabled={ocupado !== null || (!cargo.trim() && !perfil)}>Salvar</Botao>
      </form>
    </section>
  );
}

/** Lacunas da vaga pelo nome da competência ("Playwright e GraphQL"), para o cartão de preparo. */
function useLacunas(jobId: number | null): string | null {
  const vaga = useCarregar(() => (jobId ? api.get<DetalheVaga>(`/api/vagas/${jobId}`) : Promise.resolve(null)), [jobId]);
  const comps = useCarregar(() => api.get<Competencia[]>("/api/competencias").catch(() => []));
  const req = vaga.dados?.avaliacao.requisitos.filter((r) => !r.coberto) ?? [];
  if (!vaga.dados) return null;
  const nomes = [...new Set(req.map((r) => comps.dados?.find((c) => c.slug === r.competencia)?.nome ?? r.texto))];
  if (!nomes.length) return "a vaga não tem lacunas: o vault cobre todos os requisitos";
  const mostra = nomes.slice(0, 3);
  const resto = nomes.length - mostra.length;
  const lista = mostra.length > 1 ? `${mostra.slice(0, -1).join(", ")} e ${mostra[mostra.length - 1]}` : mostra[0];
  return `Roteiro com as lacunas da vaga: ${lista}${resto > 0 ? ` e mais ${resto}` : ""}`;
}

/** Candidatura sem vaga gravada: escolher uma das vagas (com busca) ou ir colar uma nova. Sem custo. */
function LigarVaga({ candidaturaId, aoMudar }: { candidaturaId: number; aoMudar: () => void }) {
  const { abrir } = useApp();
  const vagas = useCarregar(() => api.get<VagaLista[]>("/api/vagas"));
  async function ligar(job: number) {
    try {
      await api.put(`/api/candidaturas/${candidaturaId}/vaga`, { job_id: job });
      avisar("Vaga ligada à candidatura");
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    }
  }
  const itens: ItemMenu[] = [
    // a vaga já aplicada está em outra candidatura (uma vaga, uma candidatura): aparece, mas não dá para escolher
    ...(vagas.dados ?? []).filter((v) => v.status !== "descartado")
      .map((v) => ({ rotulo: [v.titulo, v.empresa].filter(Boolean).join(" — "), aoEscolher: () => ligar(v.id),
        desabilitado: v.status === "aplicado", dica: v.status === "aplicado" ? "já em outra candidatura" : undefined })),
    { rotulo: "Colar uma vaga nova", separado: true, aoEscolher: () => abrir("vagas") },
  ];
  return <Menu rotulo="Ligar a uma vaga" busca alinhamento="esquerda" classeGatilho="btn" gatilho={<>Ligar a uma vaga</>} itens={itens} />;
}

/** Sem roteiro: o cartão "Preparar para a entrevista". Com roteiro: a seção salva, recolhível (decisão 6). */
export function Roteiro({ detalhe, aoMudar }: Base) {
  const { semLLM, abrir } = useApp();
  const c = detalhe.candidatura;
  const roteiro = detalhe.roteiro;
  const lacunas = useLacunas(roteiro ? null : c.job_id);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<{ texto: string; llm: boolean } | null>(null);
  const [aberto, setAberto] = useState(true);

  useEffect(() => setErro(null), [c.id]);

  async function preparar() {
    setOcupado(true);
    setErro(null);
    try {
      await api.post(`/api/candidaturas/${c.id}/preparar`);
      setAberto(true);
      aoMudar();
    } catch (e) {
      setErro({ texto: mensagem(e), llm: eErroDeLLM(e) });
    } finally {
      setOcupado(false);
    }
  }

  async function copiar() {
    if (!roteiro) return;
    const blocos = roteiro.itens.map((i) => [i.tema, i.o_que_revisar && `Revisar: ${i.o_que_revisar}`,
      i.pergunta_provavel && `Pergunta provável: ${i.pergunta_provavel}`].filter(Boolean).join("\n"));
    const texto = [`Roteiro da entrevista — ${nomeDa(c)}${c.empresa ? ` · ${c.empresa}` : ""}`, ...blocos].join("\n\n");
    try {
      await navigator.clipboard.writeText(texto);
      avisar("Roteiro copiado");
    } catch {
      avisar("Não deu para copiar: a área de transferência recusou");
    }
  }

  const falha = erro && (
    <div className="caixa-falha" role="alert">
      <AlertCircle size={16} strokeWidth={1.8} aria-hidden />
      <div><b>Não deu para montar o roteiro</b><p>{erro.texto}</p></div>
      {erro.llm && <Botao onClick={() => abrir("configuracoes", "llm")}>Abrir configurações</Botao>}
    </div>
  );

  if (!roteiro)
    return (
      <div className="preparo">
        <div className="cartao-acao cartao-cand">
          <span className="ic" aria-hidden><BookOpen size={16} strokeWidth={1.5} /></span>
          <div className="tx">
            <b>Preparar para a entrevista</b>
            <span>{c.job_id ? lacunas ?? "Roteiro com as lacunas da vaga" : "Ligue a candidatura a uma vaga gravada para montar o roteiro"}</span>
          </div>
          <div className="botoes">
            {c.job_id ? (
              <>
                <UsaLLM para="preparar" />
                <Botao tipo="prim" onClick={preparar} ocupado={ocupado} textoOcupado="Preparando…" disabled={semLLM}>Preparar</Botao>
              </>
            ) : <LigarVaga candidaturaId={c.id} aoMudar={aoMudar} />}
          </div>
        </div>
        {falha}
      </div>
    );

  return (
    <section className="roteiro cresce" aria-label="Roteiro da entrevista">
      <header className="cab-roteiro">
        <BookOpen size={16} strokeWidth={1.6} aria-hidden />
        <b>Roteiro da entrevista</b>
        <span className="meta">gerado {quandoMarco(roteiro.gerado_em)}</span>
        <span className="acoes-roteiro">
          <Botao tipo="fant" icone={<Copy size={14} strokeWidth={1.6} aria-hidden />} onClick={copiar}>Copiar</Botao>
          <UsaLLM para="gerar de novo" />
          <Botao icone={<RotateCw size={14} strokeWidth={1.6} aria-hidden />} onClick={preparar} ocupado={ocupado}
            textoOcupado="Gerando…" disabled={semLLM}>Gerar de novo</Botao>
          <button className="btn-icone" aria-expanded={aberto} aria-label={aberto ? "Recolher o roteiro" : "Abrir o roteiro"}
            onClick={() => setAberto((a) => !a)}>
            <ChevronDown size={16} strokeWidth={2} aria-hidden className="seta-roteiro" />
          </button>
        </span>
      </header>
      {falha}
      {aberto && (
        <ul className="itens-roteiro troca">
          {roteiro.itens.map((i, n) => (
            <li key={n}>
              <b>{i.tema}</b>
              {i.o_que_revisar && <p><span className="meta">Revisar:</span> {i.o_que_revisar}</p>}
              {i.pergunta_provavel && <p><span className="meta">Pergunta provável:</span> {i.pergunta_provavel}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
