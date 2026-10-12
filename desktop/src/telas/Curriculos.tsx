import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Check, Download, FileText, Globe, Plus } from "lucide-react";
import { api, eErroDeLLM } from "../api";
import { baixarPdf as salvarPdf, Markdown, mostrarNaPasta, useCarregar } from "../comum";
import type { Competencia, DetalheVersao, EstruturaCV, FatoPrevia, FonteLinha, GrupoCV, NotasPerfil, PreviaCV, VersaoCV } from "../tipos";
import { avisar } from "../ui/Aviso";
import Botao from "../ui/Botao";
import Folha from "../ui/Folha";
import Cabecalho from "../ui/Cabecalho";
import { useApp } from "../ui/contexto";
import ListaSelecao, { DocCorpo } from "../ui/ListaSelecao";
import Procedencia from "../ui/Procedencia";
import Segmentado from "../ui/Segmentado";
import UsaLLM from "../ui/UsaLLM";
import Vazio from "../ui/Vazio";

type Idioma = "pt" | "en";

/** Uma geração: PT e EN da mesma vez afirmam os mesmos fatos (é isso que junta o par). */
type Geracao = {
  tipo: "geracao";
  chave: string;
  grupo: string;
  perfil: string | null;
  job_id: number | null;
  vaga: string | null;
  criado_em: string;
  fatos: number;
  pt?: VersaoCV;
  en?: VersaoCV;
};
type RecorteVazio = { tipo: "vazio"; chave: string; grupo: string; perfil: string | null; cargo: { pt: string; en: string } | null };
type Linha = Geracao | RecorteVazio;

const ICONE = { size: 16, strokeWidth: 1.5, "aria-hidden": true } as const;

function rotuloGrupo(g: GrupoCV) {
  return g.cargo?.pt ?? g.titulo;
}

/** Cabeçalho do recorte (decisão 11): "8 candidaturas · 3 avançaram · nota 4" ou "… · faltam 7 envios".
 *  O currículo geral (sem recorte) conta as candidaturas de perfil `geral`. */
function notaDoRecorte(notas: NotasPerfil | null, perfil: string | null): string | null {
  const n = notas?.perfis.find((x) => x.perfil === (perfil ?? "geral"));
  if (!n) return null;
  const base = `${n.enviados} ${n.enviados === 1 ? "candidatura" : "candidaturas"} · ${n.avancos} ${n.avancos === 1 ? "avançou" : "avançaram"}`;
  if (n.nota !== null) return `${base} · nota ${n.nota}`;
  const falta = n.falta.split(";")[0].replace(" maturados", "");
  return falta ? `${base} · ${falta}` : base;
}

function dataCurta(iso: string) {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

// PT e EN da mesma geração saem juntos; uma redação posterior da mesma seleção ("Redigir de novo") é outra
// geração e continua na lista, porque pode ser a que já foi enviada
const MESMA_GERACAO_MS = 30 * 60 * 1000;

function linhas(galeria: GrupoCV[]): Linha[] {
  const saida: Linha[] = [];
  for (const g of galeria) {
    const grupo = rotuloGrupo(g);
    const geracoes: (Geracao & { base: string })[] = [];
    for (const v of g.versoes) {
      const base = `${g.perfil ?? ""}|${v.job_id ?? ""}|${v.fatos.join(",")}`;
      const quando = Date.parse(v.criado_em);
      let atual = geracoes.find((x) => x.base === base && !x[v.idioma] && Math.abs(Date.parse(x.criado_em) - quando) <= MESMA_GERACAO_MS);
      if (!atual) {
        atual = {
          tipo: "geracao" as const, base, chave: `${base}|${v.id}`, grupo, perfil: g.perfil, job_id: v.job_id,
          vaga: v.vaga_empresa ? `${v.vaga_empresa} · ${v.vaga_titulo}` : null,
          criado_em: v.criado_em, fatos: v.fatos.length,
        };
        geracoes.push(atual);
      }
      atual[v.idioma] = v;
    }
    if (geracoes.length) saida.push(...geracoes);
    else saida.push({ tipo: "vazio", chave: `vazio:${g.perfil ?? ""}`, grupo, perfil: g.perfil, cargo: g.cargo });
  }
  return saida;
}

type PedidoGerar = { perfil: string | null; job_id?: number | null; idiomas: Idioma[]; forcar?: boolean };

/** Gera (ou redige de novo) e devolve se deu certo. O aviso diz o que houve; erro de LLM leva a Configurar. */
async function gerar(pedido: PedidoGerar, abrir: (t: "configuracoes", secao?: string) => void): Promise<boolean> {
  try {
    await api.post("/api/curriculos", { perfil: pedido.perfil, job_id: pedido.job_id ?? null, idiomas: pedido.idiomas, forcar: !!pedido.forcar });
    avisar(pedido.forcar ? "Currículo redigido de novo" : "Currículo redigido");
    return true;
  } catch (e) {
    avisar(e instanceof Error ? e.message : String(e),
      eErroDeLLM(e) ? { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") } : undefined);
    return false;
  }
}

function urlPrevia(perfil: string | null) {
  return perfil ? `/api/curriculos/previa?perfil=${encodeURIComponent(perfil)}` : "/api/curriculos/previa";
}

/** Currículos: versões por recorte, a página do currículo sobre a mesa e a fonte de cada linha no vault. */
export default function Curriculos({ inicial }: { inicial?: number } = {}) {
  const galeria = useCarregar(() => api.get<GrupoCV[]>("/api/curriculos/galeria"));
  const notas = useCarregar(() => api.get<NotasPerfil>("/api/candidaturas/notas").catch(() => null));
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [criando, setCriando] = useState(false);
  const [previas, setPrevias] = useState<Record<string, number>>({});
  const [aSelecionar, setASelecionar] = useState<{ perfil: string | null; job_id?: number | null; antes: string | null } | null>(null);
  // a linha escolhida agora (lida pelos pedidos que voltam depois): trocar de linha no meio de uma geração vence
  const escolhidaAgora = useRef<string | null>(null);
  escolhidaAgora.current = escolhida;
  // prévias "N fatos entrariam": cada rodada tem um número; resposta de rodada velha é descartada
  const rodadaPrevias = useRef(0);
  const pedidas = useRef(new Set<string>());

  const todas = useMemo(() => linhas(galeria.dados ?? []), [galeria.dados]);
  // aberta pela candidatura ("Abrir o currículo"): a geração que contém essa versão fica selecionada
  useEffect(() => {
    if (inicial === undefined || escolhida !== null) return;
    const alvo = todas.find((l) => l.tipo === "geracao" && (l.pt?.id === inicial || l.en?.id === inicial));
    if (alvo) setEscolhida(alvo.chave);
  }, [todas]); // eslint-disable-line react-hooks/exhaustive-deps
  const selecionada = todas.find((l) => l.chave === escolhida) ?? todas[0] ?? null;
  const geracoes = todas.filter((l) => l.tipo === "geracao").length;

  // depois de gerar: a geração que acabou de nascer fica selecionada (a mais recente do recorte)
  useEffect(() => {
    if (!aSelecionar || !galeria.dados) return;
    const doRecorte = todas.filter((l): l is Geracao => l.tipo === "geracao" && l.perfil === aSelecionar.perfil);
    const alvo = doRecorte.find((l) => aSelecionar.job_id === undefined || l.job_id === aSelecionar.job_id) ?? doRecorte[0];
    if (alvo && escolhidaAgora.current === aSelecionar.antes) setEscolhida(alvo.chave);
    setASelecionar(null);
  }, [todas]); // eslint-disable-line react-hooks/exhaustive-deps

  async function aoGerar(perfil: string | null, job_id?: number | null) {
    setASelecionar({ perfil, job_id, antes: escolhidaAgora.current });
    zerarPrevias();
    await galeria.recarregar();
  }

  function zerarPrevias() {
    rodadaPrevias.current += 1;
    pedidas.current.clear();
    setPrevias({});
  }

  // recorte sem versão: a linha diz quantos fatos entrariam (prévia sem LLM)
  useEffect(() => {
    const rodada = rodadaPrevias.current;
    for (const l of todas) {
      if (l.tipo !== "vazio" || l.chave in previas || pedidas.current.has(l.chave)) continue;
      pedidas.current.add(l.chave); // um pedido em voo por recorte
      const guardar = (n: number) => { if (rodada === rodadaPrevias.current) setPrevias((p) => ({ ...p, [l.chave]: n })); };
      api.get<FatoPrevia[]>(urlPrevia(l.perfil)).then((fatos) => guardar(fatos.length), () => guardar(-1));
    }
  }, [todas]); // eslint-disable-line react-hooks/exhaustive-deps

  const cabecalho = (
    <Cabecalho
      titulo="Currículos"
      status={galeria.dados ? [
        `${galeria.dados.length} ${galeria.dados.length === 1 ? "recorte" : "recortes"} do mesmo vault`,
        `${geracoes} ${geracoes === 1 ? "versão gerada" : "versões geradas"}`,
      ] : []}
      acoes={<Botao icone={<Plus {...ICONE} />} onClick={() => setCriando(true)}>Novo recorte</Botao>}
    />
  );
  const folha = (
    <NovoRecorte
      aberta={criando}
      aoFechar={() => setCriando(false)}
      aoCriar={async (slug) => {
        setCriando(false);
        zerarPrevias();
        await galeria.recarregar();
        setEscolhida(`vazio:${slug}`);
        avisar("Recorte criado");
      }}
    />
  );

  if (galeria.erro) return <>{cabecalho}<p className="erro-tela">{galeria.erro}</p>{folha}</>;

  return (
    <>
      {cabecalho}
      <div className="mestre mestre-cv">
        <div className="coluna-lista">
          {!galeria.dados ? (
            <div className="esqueleto-lista" aria-hidden>{Array.from({ length: 4 }, (_, i) => <span key={i} />)}</div>
          ) : (
            <ListaSelecao
              rotulo="Versões do currículo"
              itens={todas}
              chave={(l) => l.chave}
              grupo={(l) => l.grupo}
              detalheGrupo={(g) => notaDoRecorte(notas.dados, todas.find((l) => l.grupo === g)?.perfil ?? null)}
              selecionado={selecionada?.chave ?? null}
              aoSelecionar={setEscolhida}
              render={(l) =>
                l.tipo === "geracao" ? (
                  <span className="tx">
                    <b>{l.vaga ?? "Sem vaga"}</b>
                    <span className="meta">
                      {dataCurta(l.criado_em)} · {l.fatos} fatos · {[l.pt && "PT", l.en && "EN"].filter(Boolean).join(" e ")}
                    </span>
                  </span>
                ) : (
                  <span className="tx">
                    <b>Nenhuma versão ainda</b>
                    <span className="meta">
                      {previas[l.chave] === undefined ? "…" : previas[l.chave] > 0 ? `${previas[l.chave]} fatos entrariam`
                        : previas[l.chave] < 0 ? "não deu para calcular a prévia" : "nenhum fato sustenta ainda"}
                    </span>
                  </span>
                )
              }
            />
          )}
        </div>
        {selecionada?.tipo === "geracao" ? (
          <AreaGeracao key={selecionada.chave} geracao={selecionada} aoGerar={aoGerar} />
        ) : selecionada?.tipo === "vazio" ? (
          <RecorteSemVersao key={selecionada.chave} recorte={selecionada} aoGerar={aoGerar} />
        ) : galeria.dados ? (
          <div className="vazio-tela">
            <VazioCurriculos />
          </div>
        ) : <div />}
      </div>
      {folha}
    </>
  );
}

type PropsNovo = { aberta: boolean; aoFechar: () => void; aoCriar: (slug: string) => void };

/** Folha "Novo recorte": grava no curriculos.yaml (acrescenta no fim, sem reescrever o arquivo). Sem custo. */
function NovoRecorte({ aberta, aoFechar, aoCriar }: PropsNovo) {
  const comps = useCarregar(() => api.get<Competencia[]>("/api/competencias"));
  const [cargoPt, setCargoPt] = useState("");
  const [cargoEn, setCargoEn] = useState("");
  const [foco, setFoco] = useState("");
  const [pesos, setPesos] = useState<Record<string, 1 | 2 | 3>>({});
  const [limite, setLimite] = useState(12);
  const [paginas, setPaginas] = useState<"1" | "2">("1");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  // peso só muda alguma coisa onde há fato: a folha mostra as competências que sustentam currículo
  const prontas = (comps.dados ?? []).filter((c) => c.pronta_para_cv);
  const pode = cargoPt.trim() && cargoEn.trim() && Object.keys(pesos).length > 0 && limite >= 3 && limite <= 30;

  function alternar(slug: string) {
    setPesos((p) => {
      const n = { ...p };
      if (n[slug]) delete n[slug];
      else n[slug] = 2;
      return n;
    });
  }

  async function criar() {
    setOcupado(true);
    setErro(null);
    try {
      const r = await api.post<{ slug: string }>("/api/curriculos/perfis", {
        cargo_pt: cargoPt, cargo_en: cargoEn, foco, competencias: pesos, limite_fatos: limite, paginas: Number(paginas),
      });
      setCargoPt(""); setCargoEn(""); setFoco(""); setPesos({}); setLimite(12); setPaginas("1");
      aoCriar(r.slug);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
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
      titulo="Novo recorte"
      largura={640}
      aoFechar={fechar}
      rodape={
        <>
          <span className="meta dica-folha">sem custo: não chama o modelo</span>
          <Botao tipo="fant" onClick={fechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={criar} ocupado={ocupado} textoOcupado="Criando…" disabled={!pode}>Criar recorte</Botao>
        </>
      }
    >
      <p>O recorte só muda o que aparece primeiro. Só entra o que o seu vault sustenta.</p>
      <div className="campos-2">
        <label className="rotulo-campo">
          <span>Cargo (português) <small className="meta">também é o nome do recorte</small></span>
          <input className="campo" value={cargoPt} onChange={(e) => setCargoPt(e.target.value)} placeholder="Desenvolvedor Front-end" />
        </label>
        <label className="rotulo-campo">
          <span>Cargo em inglês</span>
          <input className="campo" value={cargoEn} onChange={(e) => setCargoEn(e.target.value)} placeholder="Front-end Developer" />
        </label>
      </div>
      <label className="rotulo-campo">
        <span>Foco (opcional)</span>
        <input className="campo" value={foco} onChange={(e) => setFoco(e.target.value)} placeholder="Interfaces acessíveis em React, com testes de ponta a ponta" />
      </label>
      <fieldset className="rotulo-campo grupo-chips">
        <legend>Competências que pesam mais <small className="meta">só as que sustentam currículo</small></legend>
        {comps.dados && prontas.length === 0 && (
          <p className="meta">Nenhuma competência sustenta currículo ainda. Declare nível 2 ou mais com evidência em Competências.</p>
        )}
        <div className="chips">
          {prontas.map((c) => {
            const peso = pesos[c.slug];
            return (
              <span key={c.slug} className={`chip${peso ? " ligado" : ""}`}>
                <button aria-pressed={!!peso} onClick={() => alternar(c.slug)}>
                  {peso && <Check size={15} strokeWidth={2.2} aria-hidden />}
                  {c.nome}
                </button>
                {peso && (
                  <span className="peso" role="group" aria-label={`Peso de ${c.nome}`}>
                    {([1, 2, 3] as const).map((n) => (
                      <button key={n} aria-pressed={peso === n} aria-label={`peso ${n}`} onClick={() => setPesos((p) => ({ ...p, [c.slug]: n }))}>{n}</button>
                    ))}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </fieldset>
      <div className="campos-linha">
        <label className="rotulo-campo">
          <span>Limite de fatos</span>
          <input className="campo" type="number" min={3} max={30} value={limite} onChange={(e) => setLimite(Number(e.target.value))} style={{ width: 120 }} />
        </label>
        <div className="rotulo-campo">
          <span id="rotulo-paginas">Páginas</span>
          <Segmentado rotulo="Páginas" valor={paginas} aoMudar={setPaginas} opcoes={[{ id: "1", nome: "1" }, { id: "2", nome: "2" }]} />
        </div>
      </div>
      {erro && <p className="erro-folha" role="alert">{erro}</p>}
    </Folha>
  );
}

function VazioCurriculos() {
  const { abrir } = useApp();
  return (
    <Vazio
      icone={<FileText size={20} strokeWidth={1.5} />}
      titulo="Nenhum currículo gerado"
      texto="Escolha uma vaga e gere uma versão sob medida, com a fonte de cada linha no seu vault."
      acoes={<Botao tipo="prim" onClick={() => abrir("vagas")}>Escolher uma vaga</Botao>}
    />
  );
}

type AoGerar = (perfil: string | null, job_id?: number | null) => Promise<void>;

function AreaGeracao({ geracao, aoGerar }: { geracao: Geracao; aoGerar: AoGerar }) {
  const { abrir, semLLM } = useApp();
  const [idioma, setIdioma] = useState<Idioma>(geracao.pt ? "pt" : "en");
  const [ocupado, setOcupadoEstado] = useState<null | "pdf" | "redigir" | "idioma">(null);
  // guarda síncrona: duplo clique ou um segundo ponto de entrada não disparam duas gerações pagas
  const emCurso = useRef(false);
  function setOcupado(v: null | "pdf" | "redigir" | "idioma") {
    emCurso.current = v !== null;
    setOcupadoEstado(v);
  }
  const podeRedigir = !semLLM && ocupado === null;
  const versao = geracao[idioma];
  const outra = geracao[idioma === "pt" ? "en" : "pt"];
  const idiomas = (["pt", "en"] as Idioma[]).filter((i) => geracao[i]);

  async function redigir() {
    if (semLLM || emCurso.current) return;
    setOcupado("redigir");
    if (await gerar({ perfil: geracao.perfil, job_id: geracao.job_id, idiomas, forcar: true }, abrir)) await aoGerar(geracao.perfil, geracao.job_id);
    setOcupado(null);
  }

  async function gerarIdioma() {
    if (semLLM || emCurso.current) return;
    setOcupado("idioma");
    if (await gerar({ perfil: geracao.perfil, job_id: geracao.job_id, idiomas: [idioma] }, abrir)) await aoGerar(geracao.perfil, geracao.job_id);
    setOcupado(null);
  }

  async function baixarPdf() {
    if (!versao || emCurso.current) return;
    setOcupado("pdf");
    try {
      const onde = await salvarPdf(versao.id);
      if (onde === null) return; // cancelou a janela de salvar
      if ("__TAURI_INTERNALS__" in window) avisar("PDF salvo", { rotulo: "Mostrar na pasta", onClick: () => { mostrarNaPasta(onde); } });
      else avisar(`PDF baixado: ${onde}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      avisar(msg, /redija de novo/i.test(msg) && !semLLM ? { rotulo: "Redigir de novo", onClick: redigir } : undefined);
    } finally {
      setOcupado(null);
    }
  }

  return (
    <section className="area-cv" aria-label="Currículo">
      <div className="barra-cv">
        <Segmentado
          rotulo="Idioma do currículo"
          valor={idioma}
          aoMudar={setIdioma}
          opcoes={[{ id: "pt", nome: "Português" }, { id: "en", nome: "English" }]}
        />
        <span className="meta tabular">
          {versao ? `${versao.fatos.length} fatos do vault · ${versao.palavras ?? "?"} palavras`
            : `${outra?.fatos.length ?? 0} fatos do vault · só em ${idioma === "en" ? "português" : "inglês"}`}
        </span>
        {versao && (
          <div className="acoes-cv">
            <UsaLLM />
            <Botao tipo="fant" onClick={redigir} ocupado={ocupado === "redigir"} textoOcupado="Redigindo…" disabled={semLLM || (ocupado !== null && ocupado !== "redigir")}>
              Redigir de novo
            </Botao>
            <Botao tipo="prim" icone={<Download {...ICONE} />} onClick={baixarPdf} ocupado={ocupado === "pdf"} textoOcupado="Compilando…"
              disabled={ocupado !== null && ocupado !== "pdf"}>
              Baixar PDF
            </Botao>
          </div>
        )}
      </div>
      <div className="mesa">
        {versao ? <Leitura key={versao.id} versao={versao} aoRedigir={redigir} podeRedigir={podeRedigir} />
          : <SemIdioma idioma={idioma} fatos={outra?.fatos.length ?? 0} aoGerar={gerarIdioma} ocupado={ocupado === "idioma"} />}
      </div>
    </section>
  );
}

function SemIdioma({ idioma, fatos, aoGerar, ocupado }: { idioma: Idioma; fatos: number; aoGerar: () => void; ocupado: boolean }) {
  const { semLLM } = useApp();
  const nome = idioma === "en" ? "inglês" : "português";
  return (
    <div className="mesa-centro">
      <Vazio
        icone={<Globe size={20} strokeWidth={1.5} />}
        titulo={`Ainda não há versão em ${nome}`}
        texto={`O Quilha redige em ${nome} os mesmos ${fatos} fatos da outra versão.`}
        acoes={<><Botao tipo="prim" onClick={aoGerar} ocupado={ocupado} textoOcupado="Redigindo…" disabled={semLLM}>Gerar em {nome}</Botao><UsaLLM /></>}
      />
    </div>
  );
}

function Leitura({ versao, aoRedigir, podeRedigir }: { versao: VersaoCV; aoRedigir: () => void; podeRedigir: boolean }) {
  const detalhe = useCarregar(() => api.get<DetalheVersao>(`/api/curriculos/${versao.id}`), [versao.id]);
  const d = detalhe.dados;
  if (detalhe.erro) return <p className="erro-tela">{detalhe.erro}</p>;
  if (!d) return <div className="folha-pdf esqueleto-folha" aria-hidden />;
  return (
    <div className="troca">
      {d.estrutura ? (
        <PaginaPDF versaoId={d.versao.id} estrutura={d.estrutura} fontes={d.fontes} />
      ) : (
        <>
          {/* papel como o do PDF; a origem de cada linha (comentário no Markdown) não aparece na página */}
          <article className="folha-markdown" lang={d.versao.idioma === "pt" ? "pt-BR" : "en"}>
            <Markdown texto={d.versao.conteudo.replace(/<!--[\s\S]*?-->/g, "")} />
          </article>
          <p className="faixa-antiga" role="note">
            <AlertCircle size={16} strokeWidth={1.8} aria-hidden />
            <span>Versão antiga, sem a fonte de cada linha.</span>
            <button className="link-faixa" onClick={aoRedigir} disabled={!podeRedigir}>Redigir de novo</button>
          </p>
        </>
      )}
    </div>
  );
}

/** Balão de procedência por linha: hover com atraso de 300 ms (sem piscar ao passar o mouse pela folha) ou
 *  foco pelo teclado; clique ou Enter deixa preso; Esc fecha. Um balão por vez. */
function useProcedencia() {
  const [aberta, setAberta] = useState<{ ref: string; el: HTMLElement } | null>(null);
  const [presa, setPresa] = useState(false);
  const relogio = useRef<number | undefined>(undefined);
  const limpar = () => window.clearTimeout(relogio.current);
  useEffect(() => limpar, []); // sai da tela com um balão agendado: o relógio não dispara depois

  useEffect(() => {
    if (!aberta) return;
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        aberta.el.focus();
        setAberta(null);
        setPresa(false);
      }
    };
    const fora = (e: MouseEvent) => {
      const alvo = e.target as Node;
      if (!aberta.el.contains(alvo) && !document.getElementById("balao-procedencia")?.contains(alvo)) {
        setAberta(null);
        setPresa(false);
      }
    };
    window.addEventListener("keydown", tecla);
    document.addEventListener("mousedown", fora);
    return () => {
      window.removeEventListener("keydown", tecla);
      document.removeEventListener("mousedown", fora);
    };
  }, [aberta]);

  function props(ref: string) {
    const ativa = aberta?.ref === ref;
    return {
      tabIndex: 0,
      role: "button",
      "aria-expanded": ativa,
      "aria-describedby": ativa ? "balao-procedencia" : undefined,
      onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
        if (presa) return;
        const el = e.currentTarget;
        limpar();
        relogio.current = window.setTimeout(() => setAberta({ ref, el }), 300);
      },
      onMouseLeave: () => {
        limpar();
        if (!presa) relogio.current = window.setTimeout(() => setAberta(null), 160);
      },
      onFocus: (e: React.FocusEvent<HTMLElement>) => {
        if (!presa) setAberta({ ref, el: e.currentTarget });
      },
      onBlur: () => {
        if (!presa) setAberta((a) => (a?.ref === ref ? null : a));
      },
      onClick: (e: React.MouseEvent<HTMLElement>) => {
        limpar();
        const fixar = !(presa && ativa);
        setPresa(fixar);
        setAberta(fixar ? { ref, el: e.currentTarget } : null);
      },
      onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        setPresa(true);
        setAberta({ ref, el: e.currentTarget });
        // preso pelo teclado: o foco vai para o link do balão, que mora fora da folha
        window.setTimeout(() => document.querySelector<HTMLElement>("#balao-procedencia button")?.focus(), 50);
      },
    };
  }

  return { aberta, props, manter: limpar, soltar: () => { if (!presa) setAberta(null); } };
}

// folga em volta do texto do fato (em pontos da página): a marca do Typst é a caixa do texto, colada nas letras
const FOLGA_PT = 2.5;

/** A página como sai no PDF: as imagens do próprio PDF (o mesmo do "Baixar PDF"), com uma área clicável por
 *  fato por cima, para o balão de procedência. Posições em porcentagem: acompanham qualquer largura. */
export function PaginaPDF({ versaoId, estrutura, fontes }: { versaoId: number; estrutura: EstruturaCV; fontes?: Record<string, FonteLinha> }) {
  const previa = useCarregar(() => api.get<PreviaCV>(`/api/curriculos/${versaoId}/previa`), [versaoId]);
  const pilha = useRef<HTMLDivElement>(null);
  const proc = useProcedencia();
  const textos = new Map([...estrutura.experiencias, ...estrutura.projetos].flatMap((x) => x.bullets.map((b) => [b.referencia, b.texto] as const)));
  if (previa.dados) ULTIMA_PREVIA.set(versaoId, previa.dados);
  // `curriculos.yaml` quebrado no meio do caminho: a mensagem vem por cima da última página boa, se houver
  const p = previa.dados ?? (previa.erro ? ULTIMA_PREVIA.get(versaoId) : undefined);
  if (previa.erro && !p) return <p className="erro-tela">{previa.erro}</p>;
  if (!p) return <div className="folha-pdf esqueleto-folha" aria-hidden />;
  const pct = (v: number, total: number) => `${(v / total) * 100}%`;
  return (
    <div className="pilha-pdf" ref={pilha} lang={estrutura.idioma === "pt" ? "pt-BR" : "en"}>
      {previa.erro && <p className="erro-tela" role="alert">{previa.erro}</p>}
      <TextoDoCurriculo estrutura={estrutura} />
      {p.passou && (
        <p className="faixa-antiga" role="note">
          <AlertCircle size={16} strokeWidth={1.8} aria-hidden />
          <span>Passa de {p.limite === 1 ? "1 página" : `${p.limite} páginas`}: o download vai pedir para tirar fatos do recorte.</span>
        </p>
      )}
      {p.paginas.map((src, i) => (
        <div key={i} className="folha-pdf" style={{ aspectRatio: `${p.largura} / ${p.altura}` }}>
          <img src={src} alt={`Página ${i + 1} do currículo`} draggable={false} />
          {fontes && p.linhas.filter((l) => l.pagina === i + 1).map((l) => (
            <span
              key={`${l.ref}-${l.y}`}
              className={`area-linha${proc.aberta?.ref === l.ref ? " ativa" : ""}${!fontes[l.ref]?.no_vault ? " fora" : ""}`}
              style={{
                left: pct(l.x - FOLGA_PT, p.largura), top: pct(l.y - FOLGA_PT, p.altura),
                width: pct(l.w + 2 * FOLGA_PT, p.largura), height: pct(l.h + 2 * FOLGA_PT, p.altura),
              }}
              aria-label={textos.get(l.ref) ?? l.ref}
              {...proc.props(l.ref)}
            />
          ))}
        </div>
      ))}
      {proc.aberta && fontes && (
        <Procedencia id="balao-procedencia" fonte={fontes[proc.aberta.ref]} ancora={proc.aberta.el} folha={pilha.current}
          aoEntrar={proc.manter} aoSair={proc.soltar} />
      )}
    </div>
  );
}

/** A última prévia boa de cada versão, nesta sessão: um erro depois dela não apaga a página da tela. */
const ULTIMA_PREVIA = new Map<number, PreviaCV>();

/** O que na página é só imagem (nome, contato, resumo, competências, formação, idiomas), para o leitor de tela.
 *  Os fatos ficam nas áreas clicáveis, com a procedência. */
function TextoDoCurriculo({ estrutura: e }: { estrutura: EstruturaCV }) {
  return (
    <div className="so-leitor">
      <p>{e.nome}. {e.cargo}.</p>
      {e.contato.length > 0 && <p>{e.contato.map((c) => c.texto).join(", ")}.</p>}
      {e.resumo && <p>{e.resumo}</p>}
      {e.habilidades.map((h) => <p key={h.rotulo}>{h.rotulo}: {h.itens.join(", ")}.</p>)}
      {e.formacao.length > 0 && (
        <p>{e.rotulos.formacao}: {e.formacao.map((f) => [f.curso, f.instituicao, f.periodo].filter(Boolean).join(", ")).join("; ")}.</p>
      )}
      {e.idiomas.length > 0 && <p>{e.rotulos.idiomas}: {e.idiomas.join(", ")}.</p>}
    </div>
  );
}

function RecorteSemVersao({ recorte, aoGerar }: { recorte: RecorteVazio; aoGerar: AoGerar }) {
  const { semLLM, abrir } = useApp();
  const [ocupado, setOcupado] = useState(false);
  const previa = useCarregar(() => api.get<FatoPrevia[]>(urlPrevia(recorte.perfil)), [recorte.perfil]);
  const fatos = previa.dados ?? [];
  return (
    <article className="doc">
      <DocCorpo chave={recorte.chave}>
        <div className="meta">Recorte · nenhuma versão ainda</div>
        <h3 style={{ marginTop: 4 }}>{recorte.grupo}</h3>
        {recorte.cargo && <p className="meta" style={{ marginTop: 6 }}>Cargo no topo: {recorte.cargo.pt} / {recorte.cargo.en}</p>}
        <section className="secao-doc" style={{ marginTop: 24 }}>
          <h2>O que entraria agora <span className="meta sub-h2">sem chamar o modelo</span></h2>
          {previa.erro && <p className="erro-tela">{previa.erro}</p>}
          {previa.dados && fatos.length === 0 && (
            <p className="meta">Nenhum fato sustenta este recorte ainda. Ligue evidências e declare nível 2 ou mais em Competências.</p>
          )}
          <ul className="fatos-previa">
            {fatos.map((f) => (
              <li key={f.referencia}>
                <FileText {...ICONE} />
                <span className="texto-req">{f.texto}</span>
                <span className="fonte-req">{f.nota.split("/").pop()?.replace(/\.md$/, "")}</span>
              </li>
            ))}
          </ul>
        </section>
      </DocCorpo>
      <div className="doc-rodape">
        <UsaLLM />
        <Botao tipo="prim" ocupado={ocupado} textoOcupado="Redigindo PT e EN…" disabled={semLLM || fatos.length === 0}
          onClick={async () => {
            setOcupado(true);
            if (await gerar({ perfil: recorte.perfil, idiomas: ["pt", "en"] }, abrir)) await aoGerar(recorte.perfil);
            setOcupado(false);
          }}>
          Gerar PT e EN
        </Botao>
      </div>
    </article>
  );
}
