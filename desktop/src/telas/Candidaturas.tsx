import { useState } from "react";
import { ArrowRight, Briefcase, Calendar, Plus, RefreshCw, Send } from "lucide-react";
import { ErroApi, api, eErroDeLLM } from "../api";
import { useCarregar } from "../comum";
import type { Candidatura, DetalheCandidatura, EstadoConfig, ListaEmails, PerfilCurriculo, ResultadoSync } from "../tipos";
import Botao from "../ui/Botao";
import Cabecalho from "../ui/Cabecalho";
import { avisar } from "../ui/Aviso";
import { useApp } from "../ui/contexto";
import UsaLLM from "../ui/UsaLLM";
import Vazio from "../ui/Vazio";
import { AvisoPingada, CartaoAEnviar, MenuCandidatura, Roteiro } from "./candidaturas/Acoes";
import Documento from "./candidaturas/Documento";
import { FolhaAdicionar, FolhaEditar, FolhaEntrevista } from "./candidaturas/Folhas";
import Lista from "./candidaturas/Lista";
import Triagem from "./candidaturas/Triagem";
import { ENCERRADAS, ePingada, haTempo, mensagem, nomeDa, ordenar, plural } from "./candidaturas/comum";

const ICONE = { size: 16, strokeWidth: 1.5, "aria-hidden": true } as const;

type Props = {
  inicial?: number;
  modo?: "lista" | "triagem";
  /** algo mudou que a Início mostra (etapas, e-mails a triar) */
  aoMudar: () => void;
};

/** IMAP com usuário e senha de app, ou o Gmail por OAuth com as credenciais na pasta. */
function emailConfigurado(cfg: EstadoConfig | null): boolean {
  if (!cfg) return true; // enquanto carrega, não pisca "Configurar e-mail"
  return cfg.email.origem === "imap" ? !!cfg.email.imap_usuario && cfg.email.imap_senha_definida : cfg.email.gmail_credenciais;
}

/** Candidaturas (spec §5.5): lista por etapa com a caixa "A triar", documento com a linha do tempo e as ações. */
export default function Candidaturas({ inicial, modo: modoInicial = "lista", aoMudar }: Props) {
  const { abrir, semLLM } = useApp();
  const lista = useCarregar(() => api.get<Candidatura[]>("/api/candidaturas"));
  const emails = useCarregar(() => api.get<ListaEmails>("/api/emails?visao=pendentes"));
  const perfis = useCarregar(() => api.get<PerfilCurriculo[]>("/api/curriculos/perfis").catch(() => []));
  const [escolhida, setEscolhida] = useState<number | null>(inicial ?? null);
  const [modo, setModo] = useState(modoInicial);
  const config = useCarregar(() => api.get<EstadoConfig>("/api/config"));
  const [buscando, setBuscando] = useState(false);
  const [adicionando, setAdicionando] = useState(false);
  const [entrevista, setEntrevista] = useState(false);
  const [editando, setEditando] = useState<"titulo" | "perfil" | null>(null);

  const todas = lista.dados ?? [];
  const ativas = todas.filter((c) => !ENCERRADAS.includes(c.status));
  const primeira = [...ativas].sort(ordenar)[0] ?? todas[0] ?? null;
  const selecionada = todas.find((c) => c.id === escolhida) ?? primeira;
  const id = selecionada?.id ?? null;
  const detalhe = useCarregar(
    () => (id === null ? Promise.resolve(null) : api.get<DetalheCandidatura>(`/api/candidaturas/${id}`)), [id]);

  const aTriar = emails.dados?.contagens.pendentes ?? 0;
  const ultimaBusca = emails.dados?.ultimo_sync ? `última busca ${haTempo(emails.dados.ultimo_sync)}` : null;

  function nomePerfil(slug: string | null): string | null {
    if (!slug || slug === "geral") return null;
    return perfis.dados?.find((p) => p.slug === slug)?.cargo?.pt ?? slug;
  }

  function recarregar() {
    lista.recarregar();
    detalhe.recarregar();
    emails.recarregar();
    aoMudar();
  }

  const nAtivas = todas.filter((c) => ["enviada", "em_processo", "entrevista"].includes(c.status)).length;
  const nAEnviar = todas.filter((c) => c.status === "a_enviar").length;
  const nEntrevista = todas.filter((c) => c.status === "entrevista").length;
  const status = todas.length === 0
    ? ["Nenhuma candidatura ainda", ultimaBusca?.replace("última busca", "última busca de e-mails")]
    : [
        plural(nAtivas, "ativa", "ativas"),
        nAEnviar > 0 && `${nAEnviar} a enviar`,
        nEntrevista > 0 && `${nEntrevista} em entrevista`,
        aTriar > 0 ? plural(aTriar, "e-mail a triar", "e-mails a triar") : "nada a triar",
        ultimaBusca,
      ];

  async function buscarEmails() {
    setBuscando(true);
    try {
      const r = await api.post<ResultadoSync>("/api/emails/sync", { dias: config.dados?.email.dias ?? 30 });
      avisar(`${plural(r.novos, "e-mail novo", "e-mails novos")} · ${r.pendentes} a triar`);
      recarregar();
    } catch (e) {
      if (eErroDeLLM(e)) avisar(mensagem(e), { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") });
      else if (e instanceof ErroApi && e.status === 422)
        avisar(mensagem(e), { rotulo: "Configurar e-mail →", onClick: () => abrir("configuracoes", "email") });
      else avisar(mensagem(e));
    } finally {
      setBuscando(false);
    }
  }

  // a triagem usa o LLM, ou o Jev quando `EMAIL_CLASSIFICADOR=jev`: com o Jev, falta de LLM não trava a busca
  const porJev = config.dados?.triagem.classificador === "jev";
  const semClassificador = porJev ? !config.dados?.triagem.jev_chave_definida : semLLM;

  const acoes = (
    <>
      {emailConfigurado(config.dados) ? (
        <>
          {porJev ? (
            !config.dados?.triagem.jev_chave_definida && (
              <span className="llm sem">Configure a chave do Jev · <button onClick={() => abrir("configuracoes", "llm")}>Configurar o Jev</button></span>
            )
          ) : <UsaLLM para="triar" />}
          <Botao icone={<RefreshCw {...ICONE} />} onClick={buscarEmails} ocupado={buscando} textoOcupado="Buscando…" disabled={semClassificador}>
            Buscar e-mails
          </Botao>
        </>
      ) : (
        <Botao onClick={() => abrir("configuracoes", "email")}>Configurar e-mail <ArrowRight {...ICONE} /></Botao>
      )}
      <Botao icone={<Plus {...ICONE} />} onClick={() => setAdicionando(true)}>Adicionar candidatura</Botao>
    </>
  );
  const cabecalho = <Cabecalho titulo="Candidaturas" status={lista.dados ? status : []} acoes={acoes} />;

  /** depois de uma folha gravar: a candidatura gravada fica selecionada */
  function gravada(id: number) {
    setEscolhida(id);
    recarregar();
  }

  const d = detalhe.dados && detalhe.dados.candidatura.id === id ? detalhe.dados : null;
  const c = d?.candidatura;
  const folhas = (
    <>
      <FolhaAdicionar aberta={adicionando} perfis={perfis.dados ?? []} aoFechar={() => setAdicionando(false)}
        aoCriar={(nova) => {
          setAdicionando(false);
          gravada(nova.candidatura.id);
          avisar(`Candidatura adicionada: ${nomeDa(nova.candidatura)}`);
        }} />
      <FolhaEntrevista aberta={entrevista} detalhe={d} aoFechar={() => setEntrevista(false)}
        aoGravar={(n) => { setEntrevista(false); gravada(n.candidatura.id); avisar("Entrevista marcada"); }} />
      <FolhaEditar modo={editando} detalhe={d} perfis={perfis.dados ?? []} aoFechar={() => setEditando(null)}
        aoGravar={(n) => { setEditando(null); gravada(n.candidatura.id); avisar(editando === "perfil" ? "Perfil trocado" : "Título salvo"); }} />
    </>
  );

  if (lista.erro) return <>{cabecalho}<p className="erro-tela">{lista.erro}</p>{folhas}</>;

  return (
    <>
      {cabecalho}
      <div className="mestre mestre-cand">
        {modo === "triagem" && lista.dados ? (
          <Triagem candidaturas={todas} ultimaBusca={ultimaBusca}
            aoVoltar={() => { setModo("lista"); recarregar(); }}
            aoMudar={() => { lista.recarregar(); emails.recarregar(); aoMudar(); }} />
        ) : !lista.dados ? (
          <div className="esqueleto-lista" aria-hidden>{Array.from({ length: 6 }, (_, i) => <span key={i} />)}</div>
        ) : todas.length === 0 ? (
          <div className="coluna-lista">
            <p className="lista-vazia"><b>Nenhuma candidatura</b><br />Quando houver, elas ficam aqui por etapa.</p>
          </div>
        ) : (
          <Lista candidaturas={todas} selecionada={id} aoSelecionar={setEscolhida} aTriar={aTriar} porJev={porJev} aoTriar={() => setModo("triagem")} />
        )}
        {modo === "triagem" && lista.dados ? null : lista.dados && todas.length === 0 ? (
          <article className="doc doc-vazio">
            <Vazio
              icone={<Send size={20} strokeWidth={1.5} />}
              titulo="Nenhuma candidatura ainda"
              texto="Gere o currículo de uma vaga e ela vira candidatura. Se você já se candidatou fora do Quilha, adicione aqui para os e-mails terem a que se ligar."
              acoes={
                <>
                  <Botao tipo="prim" icone={<Briefcase {...ICONE} />} onClick={() => abrir("vagas")}>Ir para Vagas</Botao>
                  <Botao icone={<Plus {...ICONE} />} onClick={() => setAdicionando(true)}>Adicionar candidatura</Botao>
                </>
              }
            />
          </article>
        ) : (
          <Documento
            key={id ?? "nada"}
            detalhe={d}
            erro={detalhe.erro}
            carregando={detalhe.carregando}
            nomePerfil={nomePerfil}
            aoMudar={recarregar}
            menu={d && <MenuCandidatura detalhe={d} aoMudar={recarregar} aoEditar={setEditando} aoEntrevista={() => setEntrevista(true)} aoVoltar={gravada} />}
            antes={d && c && (
              c.status === "a_enviar" ? <CartaoAEnviar detalhe={d} aoMudar={recarregar} />
              : ePingada(c) && c.status !== "cancelada" ? <AvisoPingada detalhe={d} aoMudar={recarregar} perfis={perfis.dados ?? []} aoJuntar={gravada} />
              : c.status === "em_processo" ? (
                <Botao className="marcar-entrevista" icone={<Calendar {...ICONE} />} onClick={() => setEntrevista(true)}>Marcar entrevista</Botao>
              ) : null
            )}
            depois={d && c && (c.status === "entrevista" || d.roteiro) ? <Roteiro detalhe={d} aoMudar={recarregar} /> : null}
          />
        )}
      </div>
      {folhas}
    </>
  );
}
