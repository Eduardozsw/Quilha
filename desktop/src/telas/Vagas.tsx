import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Briefcase, Check, ChevronDown, ClipboardPaste, ExternalLink, FileText, MoreHorizontal, Plus, RotateCw, Sparkles, Trash2 } from "lucide-react";
import { api, eErroDeLLM } from "../api";
import { abrirExterno, useCarregar } from "../comum";
import type { Competencia, DetalheVaga, RequisitoAvaliado, StatusVaga, VagaAnunciada, VagaLista } from "../tipos";
import { avisar } from "../ui/Aviso";
import Botao from "../ui/Botao";
import Cabecalho from "../ui/Cabecalho";
import { useApp } from "../ui/contexto";
import Folha from "../ui/Folha";
import ListaSelecao, { DocCorpo } from "../ui/ListaSelecao";
import Menu from "../ui/Menu";
import Segmentado from "../ui/Segmentado";
import Selo from "../ui/Selo";
import UsaLLM from "../ui/UsaLLM";
import Vazio from "../ui/Vazio";

type Filtro = "abertas" | "novas" | "minhas";

const ICONE = { size: 16, strokeWidth: 1.5, "aria-hidden": true } as const;
const LIMITE_SOBRE = 900;

const FILTROS: Record<Filtro, (v: VagaLista) => boolean> = {
  abertas: (v) => v.status === "novo" || v.status === "analisado",
  novas: (v) => v.nova,
  minhas: (v) => v.status === "aplicado",
};

const VAZIO_FILTRO: Record<Filtro, string> = {
  abertas: "Nenhuma vaga aberta. Cole uma vaga para começar.",
  novas: "Nenhuma vaga nova. As que você ainda não abriu aparecem aqui.",
  minhas: "Nenhuma candidatura por aqui. Depois de gerar o currículo, marque a candidatura como enviada.",
};

function plural(n: number, um: string, varios: string) {
  return `${n} ${n === 1 ? um : varios}`;
}

function coletada(iso: string) {
  return `coletada em ${new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "short" })}`;
}

function mensagem(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

/** Vagas: lista por score ao vivo, documento com requisitos e a fonte de cada um no vault, e o caminho para o currículo. */
export default function Vagas({ inicial }: { inicial?: number } = {}) {
  const lista = useCarregar(() => api.get<VagaLista[]>("/api/vagas"));
  const [filtro, setFiltroBruto] = useState<Filtro>("abertas");
  const [escolhida, setEscolhida] = useState<number | null>(inicial ?? null);
  const [colando, setColando] = useState(false);
  // vagas dos alertas de e-mail (decisão 11 de Candidaturas): grupo no fim do filtro "Abertas"
  const anunciadas = useCarregar(() => api.get<VagaAnunciada[]>("/api/candidaturas/anunciadas").catch(() => []));
  const [anuncio, setAnuncio] = useState<string | null>(null);
  const [colarUrl, setColarUrl] = useState<string | undefined>();

  // mudanças locais ainda não confirmadas pela API ("vista", descartar): reaplicadas sobre toda lista que chega,
  // para uma recarga em voo não trazer de volta o selo de "nova" ou a vaga descartada
  const pendentes = useRef(new Map<number, Partial<VagaLista>>());
  const todas = useMemo(
    () => (lista.dados ?? []).map((v) => (pendentes.current.has(v.id) ? { ...v, ...pendentes.current.get(v.id) } : v)),
    [lista.dados],
  );
  // a vaga escolhida fica na lista até você escolher outra ou trocar de filtro, mesmo que deixe de
  // combinar com ele (abriu uma "nova", gerou o currículo): a tela nunca pula sozinha para outra vaga
  const visiveis = useMemo(
    () => todas
      .filter((v) => FILTROS[filtro](v) || (v.id === escolhida && v.status !== "descartado"))
      // sem nota (requisitos não extraídos) vai para o fim
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || b.coletado_em.localeCompare(a.coletado_em)),
    [todas, filtro, escolhida],
  );
  const selecionada = visiveis.find((v) => v.id === escolhida) ?? visiveis[0] ?? null;

  function setFiltro(f: Filtro) {
    setFiltroBruto(f);
    setEscolhida(null);
    setAnuncio(null);
  }

  // o cardápio não oferece de novo o que já foi enviado
  const doAlerta = filtro === "abertas" ? (anunciadas.dados ?? []).filter((a) => !a.ja_candidatou) : [];
  const anuncioSel = doAlerta.find((a) => a.id === anuncio) ?? null;

  const abertas = todas.filter(FILTROS.abertas).length;
  const novas = todas.filter(FILTROS.novas).length;
  const minhas = todas.filter(FILTROS.minhas).length;

  function atualizar(id: number, mudanca: Partial<VagaLista>) {
    lista.setDados((vs) => vs?.map((v) => (v.id === id ? { ...v, ...mudanca } : v)) ?? vs);
  }

  /** Mudança local que vale até a API confirmar (ou falhar): `confirmar` resolve ou desfaz. */
  async function otimista(id: number, mudanca: Partial<VagaLista>, chamada: Promise<unknown>) {
    pendentes.current.set(id, { ...pendentes.current.get(id), ...mudanca });
    atualizar(id, mudanca);
    try {
      await chamada;
    } finally {
      pendentes.current.delete(id);
    }
  }

  /** Escolher a vaga (clique) tira o selo de "nova" sem recarregar a lista inteira. A que aparece
   *  sozinha, sem clique, continua nova: só o gesto conta como "li". */
  function selecionar(id: number, v = todas.find((x) => x.id === id)) {
    setEscolhida(id);
    setAnuncio(null);
    if (v?.nova) {
      const vista = { nova: false, status: "analisado" as const };
      otimista(id, vista, api.post(`/api/vagas/${id}/vista`)).then(() => atualizar(id, vista), () => lista.recarregar());
    }
  }

  async function descartar(v: VagaLista) {
    try {
      const pedido = api.put<{ anterior: StatusVaga }>(`/api/vagas/${v.id}/status`, { status: "descartado" });
      await otimista(v.id, { status: "descartado", nova: false }, pedido);
      const r = await pedido;
      atualizar(v.id, { status: "descartado", nova: false });
      avisar("Vaga descartada", {
        rotulo: "Desfazer",
        onClick: async () => {
          try {
            await api.put(`/api/vagas/${v.id}/status`, { status: r.anterior });
            setEscolhida(v.id);
          } catch (e) {
            avisar(`Não deu para desfazer: ${mensagem(e)}`);
          }
          lista.recarregar();
        },
      });
    } catch (e) {
      lista.recarregar(); // o descarte não valeu: a lista volta ao que o banco diz
      avisar(mensagem(e));
    }
  }

  /** Depois de colar: mostra a vaga no filtro em que ela está (repetida pode já estar candidatada). */
  async function gravada(r: { job_id: number; duplicada?: boolean }) {
    setColando(false);
    let vagas = await api.get<VagaLista[]>("/api/vagas");
    const v = vagas.find((x) => x.id === r.job_id);
    if (v?.status === "descartado") {
      // colar de novo uma vaga descartada é querer ela de volta
      await api.put(`/api/vagas/${v.id}/status`, { status: "analisado" });
      vagas = vagas.map((x) => (x.id === v.id ? { ...x, status: "analisado" as const, nova: false } : x));
    }
    lista.setDados(vagas);
    setFiltroBruto(v?.status === "aplicado" ? "minhas" : "abertas");
    selecionar(r.job_id, vagas.find((x) => x.id === r.job_id));
    avisar(r.duplicada ? "Essa vaga já estava gravada" : "Vaga avaliada");
  }

  const cabecalho = (
    <Cabecalho
      titulo="Vagas"
      status={lista.dados ? [plural(abertas, "aberta", "abertas"), novas > 0 && plural(novas, "nova", "novas"), "ordenadas por score"] : []}
      acoes={todas.length > 0 && <Botao icone={<Plus {...ICONE} />} onClick={() => setColando(true)}>Colar uma vaga</Botao>}
    />
  );
  const folha = <ColarVaga aberta={colando} inicial={colarUrl} aoFechar={() => { setColando(false); setColarUrl(undefined); }}
    aoGravar={(r) => { setColarUrl(undefined); gravada(r); }} />;

  if (lista.erro) return <>{cabecalho}<p className="erro-tela">{lista.erro}</p></>;
  if (lista.dados && todas.length === 0)
    return (
      <>
        {cabecalho}
        <div className="vazio-tela">
          <Vazio
            icone={<Briefcase size={20} strokeWidth={1.5} />}
            titulo="Nenhuma vaga ainda"
            texto="Cole o link ou o texto de uma vaga e o Quilha compara com o seu vault."
            acoes={<Botao tipo="prim" icone={<Plus {...ICONE} />} onClick={() => setColando(true)}>Colar uma vaga</Botao>}
          />
        </div>
        {folha}
      </>
    );

  return (
    <>
      {cabecalho}
      <div className="mestre mestre-vagas">
        <div className="coluna-lista">
          <Segmentado
            rotulo="Filtrar vagas"
            valor={filtro}
            aoMudar={setFiltro}
            opcoes={[
              { id: "abertas", nome: "Abertas", contagem: abertas },
              { id: "novas", nome: "Novas", contagem: novas },
              { id: "minhas", nome: "Já me candidatei", contagem: minhas },
            ]}
          />
          {!lista.dados ? (
            <div className="esqueleto-lista" aria-hidden>{Array.from({ length: 6 }, (_, i) => <span key={i} />)}</div>
          ) : visiveis.length === 0 && doAlerta.length === 0 ? (
            <p className="lista-vazia">{VAZIO_FILTRO[filtro]}</p>
          ) : (
            <ListaSelecao
              rotulo="Vagas"
              itens={visiveis}
              chave={(v) => String(v.id)}
              selecionado={selecionada && !anuncioSel ? String(selecionada.id) : null}
              aoSelecionar={(k) => selecionar(Number(k))}
              render={(v) => (
                <>
                  <span className="tx">
                    <b className="titulo-linha">{v.titulo}{v.nova && <Selo tom="ok">nova</Selo>}</b>
                    <span className="meta">{[v.empresa, v.local].filter(Boolean).join(" · ")}</span>
                  </span>
                  <span className={`valor${v.n_requisitos ? "" : " sem-nota"}`}>{v.n_requisitos ? v.score : "—"}</span>
                </>
              )}
            />
          )}
          {lista.dados && doAlerta.length > 0 && (
            <ListaSelecao
              rotulo="Vagas dos alertas de e-mail"
              itens={doAlerta}
              chave={(a) => a.id}
              grupo={() => "Dos alertas de e-mail"}
              selecionado={anuncioSel?.id ?? null}
              aoSelecionar={setAnuncio}
              render={(a) => (
                <span className="tx">
                  <b>{a.titulo}</b>
                  <span className="meta">{[a.empresa, a.local, `do alerta de ${dataAlerta(a.anunciada_em)}`].filter(Boolean).join(" · ")}</span>
                </span>
              )}
            />
          )}
        </div>
        {anuncioSel ? (
          <DocAnuncio key={anuncioSel.id} anuncio={anuncioSel} aoColar={() => { setColarUrl(anuncioSel.url); setColando(true); }} />
        ) : selecionada ? (
          <Documento
            key={selecionada.id}
            vaga={selecionada}
            aoMudar={lista.recarregar}
            aoDescartar={() => descartar(selecionada)}
          />
        ) : <div />}
      </div>
      {folha}
    </>
  );
}

function dataAlerta(iso: string) {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "short" });
}

/** Vaga de um alerta de e-mail: ainda não foi gravada nem comparada com o vault. */
function DocAnuncio({ anuncio: a, aoColar }: { anuncio: VagaAnunciada; aoColar: () => void }) {
  return (
    <article className="doc">
      <DocCorpo chave={a.id}>
        <div className="meta">{[a.empresa, a.local, `${a.fonte} · alerta de ${dataAlerta(a.anunciada_em)}`].filter(Boolean).join(" · ")}</div>
        <h3 style={{ marginTop: 4, marginBottom: 18 }}>{a.titulo}</h3>
        <p className="leitura">Vaga de um alerta de e-mail. Cole o link em "Colar uma vaga" para o Quilha comparar com o seu vault.</p>
        {a.alerta && <p className="meta" style={{ marginTop: 8 }}>Alerta: {a.alerta}</p>}
      </DocCorpo>
      <div className="doc-rodape">
        <span className="meta dica-rodape">sem custo até você colar</span>
        <Botao tipo="fant" icone={<ExternalLink {...ICONE} />} onClick={() => abrirExterno(a.url)}>Abrir anúncio</Botao>
        <Botao tipo="prim" icone={<ClipboardPaste {...ICONE} />} onClick={aoColar}>Colar esta vaga</Botao>
      </div>
    </article>
  );
}

type PropsDoc = { vaga: VagaLista; aoMudar: () => void; aoDescartar: () => void };

function Documento({ vaga, aoMudar, aoDescartar }: PropsDoc) {
  const { semLLM, abrir } = useApp();
  const detalhe = useCarregar(() => api.get<DetalheVaga>(`/api/vagas/${vaga.id}`), [vaga.id]);
  const comps = useCarregar(() => api.get<Competencia[]>("/api/competencias"));
  const [tudo, setTudo] = useState(false);
  const [ocupado, setOcupado] = useState<null | "cv" | "extrair" | "analisar">(null);
  const [falhaExtracao, setFalhaExtracao] = useState<{ mensagem: string; llm: boolean } | null>(null);
  const d = detalhe.dados;
  const a = d?.avaliacao;
  const sobre = d?.sobre ?? "";
  const longo = sobre.length > LIMITE_SOBRE;
  const semRequisitos = !!a && a.total === 0;


  const comentarios = new Map((d?.match?.lacunas ?? []).filter((l) => l.comentario).map((l) => [l.requisito_id, l.comentario!]));
  const riscos = d?.match?.riscos ?? [];

  async function gerarCV() {
    setOcupado("cv");
    try {
      await api.post("/api/curriculos", { job_id: vaga.id });
      avisar("Currículo gerado · a candidatura fica em “A enviar”", { rotulo: "Abrir", onClick: () => abrir("curriculos") });
      aoMudar();
    } catch (e) {
      avisar(mensagem(e), eErroDeLLM(e)
        ? { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") }
        : { rotulo: "Tentar de novo", onClick: gerarCV });
    } finally {
      setOcupado(null);
    }
  }

  async function extrair() {
    setOcupado("extrair");
    setFalhaExtracao(null);
    try {
      await api.post(`/api/vagas/${vaga.id}/extrair`);
      detalhe.recarregar();
      aoMudar();
    } catch (e) {
      setFalhaExtracao({ mensagem: mensagem(e), llm: eErroDeLLM(e) });
    } finally {
      setOcupado(null);
    }
  }

  async function analisar() {
    setOcupado("analisar");
    try {
      await api.post(`/api/vagas/${vaga.id}/match`, { redigir: true });
      await detalhe.recarregar();
      avisar("Análise pronta: lacunas e riscos abaixo dos requisitos");
    } catch (e) {
      avisar(mensagem(e), eErroDeLLM(e) ? { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") } : undefined);
    } finally {
      setOcupado(null);
    }
  }

  async function trocar(r: RequisitoAvaliado, slug: string | null) {
    try {
      await api.put(`/api/requisitos/${r.id}`, { slug });
      await detalhe.recarregar();
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    }
  }


  return (
    <article className="doc" aria-busy={detalhe.carregando || undefined}>
      <DocCorpo chave={vaga.id}>
        <div className="vaga-topo">
          <div>
            <div className="meta">{[vaga.empresa, vaga.senioridade, vaga.local, coletada(vaga.coletado_em)].filter(Boolean).join(" · ")}</div>
            <h3>{vaga.titulo}</h3>
          </div>
          <div className="acoes-vaga">
            <Menu
              rotulo="Mais ações"
              gatilho={<MoreHorizontal size={16} strokeWidth={2} aria-hidden />}
              itens={[
                semLLM
                  ? { rotulo: "Analisar lacunas e riscos", icone: <Sparkles {...ICONE} />, dica: "configure o LLM",
                      desabilitado: semRequisitos, aoEscolher: () => abrir("configuracoes", "llm") }
                  : { rotulo: ocupado === "analisar" ? "Analisando…" : "Analisar lacunas e riscos", icone: <Sparkles {...ICONE} />,
                      dica: "usa seu LLM", desabilitado: semRequisitos || ocupado !== null, aoEscolher: analisar },
                { rotulo: "Descartar vaga", icone: <Trash2 {...ICONE} />, perigo: true, separado: true, aoEscolher: aoDescartar },
              ]}
            />
            <div className="nota-vaga">
              {a && a.total > 0 ? (
                <>
                  <b className="tabular">{a.score}<small>/100</small></b>
                  <span>cobre {a.cobertos} de {a.total} requisitos</span>
                </>
              ) : a ? (
                <>
                  <b className="sem-nota">—</b>
                  <span>sem requisitos ainda</span>
                </>
              ) : null}
            </div>
          </div>
        </div>

        {detalhe.erro && <p className="erro-tela">{detalhe.erro}</p>}

        {a && (
          <section className="secao-doc">
            <h2>Requisitos</h2>
            {semRequisitos ? (
              falhaExtracao ? (
                <div className="caixa-falha" role="alert">
                  <AlertCircle size={16} strokeWidth={1.8} aria-hidden />
                  <div>
                    <b>Não deu para extrair os requisitos</b>
                    <p>{falhaExtracao.mensagem}</p>
                  </div>
                  {falhaExtracao.llm ? (
                    <Botao onClick={() => abrir("configuracoes", "llm")}>Configurar LLM</Botao>
                  ) : (
                    <Botao icone={<RotateCw {...ICONE} />} onClick={extrair} disabled={semLLM}>Tentar de novo</Botao>
                  )}
                </div>
              ) : (
                <div className="caixa-sem-req">
                  <b>Requisitos ainda não extraídos</b>
                  <p>O Quilha lê a vaga e separa o que ela pede, para comparar com o seu vault.</p>
                  <div className="linha-acao">
                    <Botao tipo="prim" onClick={extrair} ocupado={ocupado === "extrair"} textoOcupado="Extraindo…" disabled={semLLM}>
                      Extrair requisitos
                    </Botao>
                    <UsaLLM para="extrair os requisitos" />
                  </div>
                </div>
              )
            ) : (
              <ul className="requisitos">
                {a.requisitos.map((r) => (
                  <li key={r.id} className={`${r.coberto ? "ok" : ""}${!r.competencia ? " sem-comp" : ""}`}>
                    <span className="marca" aria-hidden>{r.coberto && <Check size={12} strokeWidth={2.4} />}</span>
                    <span className="texto-req">
                      {r.texto}
                      {comentarios.get(r.id) && <small className="comentario-req">{comentarios.get(r.id)}</small>}
                    </span>
                    <span className="trocar-req">
                      <Menu
                        rotulo={`Trocar competência de "${r.texto}"`}
                        busca
                        gatilho={<ChevronDown size={16} strokeWidth={2} aria-hidden />}
                        itens={[
                          ...(comps.dados ?? []).map((c) => ({
                            rotulo: c.nome, marcado: c.slug === r.competencia,
                            aoEscolher: () => trocar(r, c.slug),
                          })),
                          { rotulo: "Sem competência", separado: true, marcado: !r.competencia, aoEscolher: () => trocar(r, null) },
                        ]}
                      />
                    </span>
                    {r.fonte === "falta declarar o nível" ? (
                      <button className="fonte-req link-req" onClick={() => abrir("competencias")}>{r.fonte}</button>
                    ) : (
                      <span className="fonte-req">{r.fonte}</span>
                    )}
                    <span className="so-leitor">{r.coberto ? "coberto pelo vault" : "lacuna"}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {riscos.length > 0 && (
          <section className="secao-doc cresce">
            <h2>Riscos em entrevista</h2>
            <ul className="riscos">{riscos.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </section>
        )}

        {sobre && (
          <section className="secao-doc">
            <h2>Sobre a vaga</h2>
            <p className="leitura sobre-vaga">{longo && !tudo ? `${sobre.slice(0, LIMITE_SOBRE).trimEnd()}…` : sobre}</p>
            {longo && !tudo && <Botao tipo="fant" onClick={() => setTudo(true)}>Ler tudo</Botao>}
          </section>
        )}
      </DocCorpo>
      <div className="doc-rodape">
        {semRequisitos ? <span className="meta dica-rodape">extraia os requisitos primeiro</span> : <UsaLLM />}
        {vaga.url && <Botao tipo="fant" icone={<ExternalLink {...ICONE} />} onClick={() => abrirExterno(vaga.url!)}>Abrir anúncio</Botao>}
        <Botao
          tipo={semRequisitos ? "sec" : "prim"}
          icone={<FileText {...ICONE} />}
          onClick={gerarCV}
          ocupado={ocupado === "cv"}
          textoOcupado="Gerando…"
          disabled={semLLM || semRequisitos || (ocupado !== null && ocupado !== "cv")}
        >
          Gerar currículo sob medida
        </Botao>
      </div>
    </article>
  );
}

type PropsColar = { aberta: boolean; inicial?: string; aoFechar: () => void; aoGravar: (r: { job_id: number; duplicada?: boolean }) => void };

/** Folha "Colar uma vaga": um campo só. Uma linha começando com http vai como link; o resto, como texto da vaga. */
function ColarVaga({ aberta, inicial, aoFechar, aoGravar }: PropsColar) {
  const { semLLM, abrir } = useApp();
  const [texto, setTexto] = useState("");
  // "Colar esta vaga" (vaga de alerta) abre a folha já com o link
  useEffect(() => {
    if (aberta && inicial) setTexto(inicial);
  }, [aberta, inicial]);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<{ mensagem: string; llm: boolean } | null>(null);
  const limpo = texto.trim();
  const eLink = /^https?:\/\/\S+$/i.test(limpo);

  async function avaliar() {
    setOcupado(true);
    setErro(null);
    try {
      const r = await api.post<{ job_id: number; duplicada?: boolean }>("/api/vagas", eLink ? { url: limpo } : { texto: limpo });
      setTexto("");
      aoGravar(r);
    } catch (e) {
      setErro({ mensagem: mensagem(e), llm: eErroDeLLM(e) });
    } finally {
      setOcupado(false);
    }
  }

  function fechar() {
    if (ocupado) return;
    setErro(null);
    aoFechar();
  }

  return (
    <Folha
      aberta={aberta}
      titulo="Colar uma vaga"
      aoFechar={fechar}
      rodape={
        <>
          <UsaLLM para="extrair os requisitos" />
          <Botao tipo="fant" onClick={fechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={avaliar} ocupado={ocupado} textoOcupado="Extraindo requisitos…" disabled={!limpo || semLLM}>
            Avaliar vaga
          </Botao>
        </>
      }
    >
      <p>Cole o link do anúncio ou o texto inteiro da vaga. O Quilha extrai os requisitos e compara com o seu vault.</p>
      <label className="so-leitor" htmlFor="colar-vaga">Link ou texto da vaga</label>
      <textarea
        id="colar-vaga"
        className="campo"
        rows={6}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && limpo && !semLLM && !ocupado) avaliar();
        }}
        placeholder="https://… ou o texto da vaga"
      />
      {erro && (
        <div className="erro-folha" role="alert">
          {erro.mensagem}
          {erro.llm && <Botao onClick={() => { fechar(); abrir("configuracoes", "llm"); }}>Configurar LLM</Botao>}
        </div>
      )}
    </Folha>
  );
}
