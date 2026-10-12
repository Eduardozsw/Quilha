import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronDown, ChevronRight, Inbox } from "lucide-react";
import { api } from "../../api";
import { CorpoEmail } from "../../corpoEmail";
import { useCarregar } from "../../comum";
import type { Candidatura, EmailTriagem, ListaEmails } from "../../tipos";
import { avisar } from "../../ui/Aviso";
import Botao from "../../ui/Botao";
import ListaSelecao from "../../ui/ListaSelecao";
import UsaLLM from "../../ui/UsaLLM";
import Vazio from "../../ui/Vazio";
import { CATEGORIAS, type IdCategoria, mensagem, nomeCategoria, nomeDa, quandoMarco } from "./comum";

type Visao = "pendentes" | "outros";

type Props = {
  candidaturas: Candidatura[];
  ultimaBusca: string | null;
  aoVoltar: () => void;
  /** a triagem ligou, criou ou desfez: a lista de candidaturas e a Início recarregam */
  aoMudar: () => void;
};

type Triado = { candidatura_id: number | null; criada: number | null; candidatura_antes: unknown; email: EmailTriagem };

const PROCESSO = ["avanco", "pendencia", "inscricao_confirmada", "reprovado"];
const LIGAVEIS = ["a_enviar", "enviada", "em_processo", "entrevista"];

/** "Nome <endereço>" → endereço; o que vier sem <> fica como está. */
function endereco(de: string): string {
  return de.match(/<([^>]+)>/)?.[1] ?? de.replace(/"/g, "").trim();
}

function norm(s: string | null | undefined): string {
  return (s ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

/** Teclas 1–5 só valem com o foco fora de campos editáveis (Review Focus 3) e sem folha aberta. */
function focoEmCampo(alvo: EventTarget | null): boolean {
  const el = alvo instanceof HTMLElement ? alvo : null;
  return !!el && (el.isContentEditable || !!el.closest("input, select, textarea, [contenteditable]"));
}

/** Triagem na própria tela (decisão 1): a lista vira os e-mails a triar e o documento mostra um por vez. */
export default function Triagem({ candidaturas, ultimaBusca, aoVoltar, aoMudar }: Props) {
  const [visao, setVisao] = useState<Visao>("pendentes");
  const lista = useCarregar(() => api.get<ListaEmails>(`/api/emails?visao=${visao}`), [visao]);
  const [atualId, setAtualId] = useState<number | null>(null);
  const emails = lista.dados?.emails ?? [];
  const atual = emails.find((e) => e.id === atualId) ?? emails[0] ?? null;
  const detalhe = useCarregar(
    () => (atual ? api.get<EmailTriagem>(`/api/emails/${atual.id}`) : Promise.resolve(null)), [atual?.id]);
  const [empresa, setEmpresa] = useState("");
  const [ligar, setLigar] = useState("");
  const [tudo, setTudo] = useState(false);
  const [saindo, setSaindo] = useState(false);
  const [gravando, setGravando] = useState(false);
  // conta as escolhas explícitas de qual e-mail ver (Desfazer, clique): uma classificação que termina depois
  // não tira o foco do que a pessoa escolheu no meio dela
  const escolhas = useRef(0);
  const contagens = lista.dados?.contagens;

  const ligaveis = candidaturas.filter((c) => LIGAVEIS.includes(c.status));
  const d = detalhe.dados && detalhe.dados.id === atual?.id ? detalhe.dados : null;

  // e-mail novo na tela: a empresa vem do e-mail, a ligação sugere a candidatura ativa da mesma empresa
  useEffect(() => {
    const e = atual;
    setTudo(false);
    setEmpresa(e?.empresa_extraida ?? "");
    const mesma = e?.empresa_extraida ? ligaveis.filter((c) => norm(c.empresa) === norm(e.empresa_extraida)) : [];
    setLigar(mesma.length === 1 ? String(mesma[0].id) : "");
  }, [atual?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function classificar(categoria: IdCategoria) {
    const e = atual;
    if (!e || gravando) return;
    const i = emails.findIndex((x) => x.id === e.id);
    const proximo = emails[i + 1] ?? emails[i - 1] ?? null;
    const anterior = { rotulo_manual: e.manual ? e.categoria : null, candidatura_id: e.candidatura_id, empresa: e.empresa_extraida };
    const deVisao = visao;
    const outro = categoria === "outro";
    const escolhaAntes = escolhas.current;
    // o campo "Ligar a uma candidatura" só existe na tela fora de "outro": escondido, o valor pré-escolhido não vai
    const campoLigar = (d?.categoria ?? e.categoria) !== "outro";
    const ligacao = campoLigar && !outro ? ligar : "";
    const corpo = {
      categoria,
      empresa: !outro && empresa.trim() && empresa.trim() !== (e.empresa_extraida ?? "") ? empresa.trim() : null,
      candidatura_id: ligacao && ligacao !== "nova" ? Number(ligacao) : null,
      nova: ligacao === "nova",
    };
    setGravando(true);
    setSaindo(true);
    try {
      const r = await api.post<Triado>(`/api/emails/${e.id}/triar`, corpo);
      const ficou = !outro && r.candidatura_id === null && PROCESSO.includes(r.email.categoria) && deVisao === "pendentes";
      if (ficou) {
        avisar(r.email.empresa_extraida
          ? `Mais de uma candidatura em ${r.email.empresa_extraida}: escolha em “Ligar a uma candidatura”`
          : "Falta a empresa: preencha ou escolha em “Ligar a uma candidatura”");
        if (escolhas.current === escolhaAntes) setAtualId(e.id);
      } else {
        if (escolhas.current === escolhaAntes) setAtualId(proximo?.id ?? null);
        avisar(`Triado: ${e.assunto} · ${nomeCategoria(categoria)}`, {
          rotulo: "Desfazer",
          onClick: async () => {
            try {
              await api.post(`/api/emails/${e.id}/restaurar`, { ...anterior, apagar: r.criada, candidatura_antes: r.candidatura_antes });
              escolhas.current += 1;
              setVisao(deVisao);
              setAtualId(e.id);
              lista.recarregar();
              aoMudar();
            } catch (erro) {
              avisar(mensagem(erro));
            }
          },
        });
      }
      await lista.recarregar();
      aoMudar();
    } catch (erro) {
      avisar(mensagem(erro));
    } finally {
      setSaindo(false);
      setGravando(false);
    }
  }

  // atalhos 1–5
  const classificarRef = useRef(classificar);
  classificarRef.current = classificar;
  useEffect(() => {
    function tecla(ev: KeyboardEvent) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat || focoEmCampo(ev.target)) return;
      if (document.querySelector('[role="dialog"]')) return;
      const cat = CATEGORIAS.find((c) => c.tecla === ev.key);
      if (!cat) return;
      ev.preventDefault();
      classificarRef.current(cat.id);
    }
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, []);

  function pular() {
    if (!atual) return;
    const i = emails.findIndex((x) => x.id === atual.id);
    escolhas.current += 1;
    setAtualId((emails[i + 1] ?? emails[0]).id);
  }

  const n = emails.length;
  const posicao = atual ? emails.findIndex((x) => x.id === atual.id) + 1 : 0;
  const outros = contagens?.outros ?? 0;
  const eOutro = visao === "outros";
  const categoriaAtual = d?.categoria ?? atual?.categoria;
  const palpite = d && !d.manual ? [d.categoria_jev, d.categoria].find((c) => CATEGORIAS.some((x) => x.id === c)) : undefined;
  const sugerida = d && !d.manual ? (palpite ? `sugeriu ${nomeCategoria(palpite)}` : "ficou na dúvida") : null;
  const corpo = (d?.corpo ?? "").trim();
  const longo = corpo.length > 260 || corpo.split("\n").length > 3;

  return (
    <>
      <div className="coluna-lista lista-cand lista-triagem">
        <button className="voltar-triagem" onClick={eOutro ? () => { setVisao("pendentes"); setAtualId(null); } : aoVoltar}>
          <ArrowLeft size={15} strokeWidth={1.8} aria-hidden />
          {eOutro ? "A triar" : "Candidaturas"}
        </button>
        <div className="grupo-triagem">
          <span>{eOutro ? "Não são de processo" : "A triar"}</span>
          <span className="tabular">{lista.dados ? n : ""}</span>
        </div>
        {!lista.dados ? (
          <div className="esqueleto-lista" aria-hidden>{Array.from({ length: 3 }, (_, i) => <span key={i} />)}</div>
        ) : (
          <ListaSelecao
            rotulo={eOutro ? "E-mails que não são de processo" : "E-mails a triar"}
            itens={emails}
            chave={(e) => String(e.id)}
            selecionado={atual ? String(atual.id) : null}
            aoSelecionar={(k) => { escolhas.current += 1; setAtualId(Number(k)); }}
            render={(e) => (
              <span className="tx">
                <b>{e.assunto || "(sem assunto)"}</b>
                <span className="meta">{`${e.empresa_extraida || endereco(e.de)} · ${quandoMarco(e.recebido_em)}`}</span>
              </span>
            )}
          />
        )}
        {!eOutro && (
          <button className="ver-outros" onClick={() => { setVisao("outros"); setAtualId(null); }}>
            Ver e-mails que não são de processo ({outros})
            <ChevronRight size={14} strokeWidth={2} aria-hidden />
          </button>
        )}
      </div>

      {lista.dados && !atual ? (
        <article className="doc doc-vazio">
          <Vazio
            icone={eOutro ? <Inbox size={20} strokeWidth={1.5} /> : <Check size={20} strokeWidth={1.8} className="ic-ok" />}
            titulo={eOutro ? "Nenhum e-mail fora de processo" : "Nada a triar"}
            texto={eOutro
              ? "Os e-mails que o classificador disse não serem de processo aparecem aqui, para você corrigir."
              : `Todos os e-mails de processo já estão ligados a uma candidatura.${ultimaBusca ? ` ${ultimaBusca[0].toUpperCase()}${ultimaBusca.slice(1)}.` : ""}`}
            acoes={<Botao icone={<ArrowLeft size={15} strokeWidth={1.8} aria-hidden />} onClick={aoVoltar}>Voltar às candidaturas</Botao>}
          />
        </article>
      ) : (
        <article className="doc doc-triagem" aria-busy={detalhe.carregando || undefined}>
          {atual && (
            <div key={atual.id} className={`doc-corpo troca${saindo ? " saindo" : ""}`}>
              <div className="meta">{[atual.empresa_extraida, endereco(atual.de), quandoMarco(atual.recebido_em)].filter(Boolean).join(" · ")}</div>
              <h3 className="titulo-email">{atual.assunto || "(sem assunto)"}</h3>
              <div className="caixa-email corpo-triagem">
                {d ? (corpo ? <CorpoEmail texto={corpo} className={`corpo-email${tudo ? "" : " recolhido"}`} />
                  : <p className="corpo-email vazio">E-mail sem texto gravado.</p>) : <p className="corpo-email vazio">Carregando…</p>}
                {longo && (
                  <button className="ver-tudo" aria-expanded={tudo} onClick={() => setTudo((t) => !t)}>
                    {tudo ? "Recolher" : "Ver tudo"}
                    <ChevronDown size={14} strokeWidth={2} aria-hidden />
                  </button>
                )}
              </div>

              <div className="rotulo-triagem">
                <span>Categoria</span>
                {sugerida && <UsaLLM detalhe={sugerida} />}
              </div>
              <div className="pilulas-cat pilulas-triagem" role="group" aria-label="Categoria do e-mail">
                {CATEGORIAS.map((c) => (
                  <button key={c.id} className="pilula-cat" aria-pressed={c.id === categoriaAtual} disabled={gravando}
                    aria-keyshortcuts={c.tecla} onClick={() => classificar(c.id)}>
                    <kbd className="tecla-pilula">{c.tecla}</kbd>
                    {c.id === categoriaAtual && <Check size={13} strokeWidth={2.2} aria-hidden />}
                    {c.nome}
                  </button>
                ))}
              </div>

              {categoriaAtual !== "outro" && (
                <div className="campos-triagem">
                  <label className="rotulo-campo" htmlFor="tr-ligar">Ligar a uma candidatura
                    <select id="tr-ligar" className="campo" value={ligar} onChange={(e) => setLigar(e.target.value)}>
                      <option value="">Achar pela empresa</option>
                      {ligaveis.map((c) => (
                        <option key={c.id} value={c.id}>{[nomeDa(c), c.titulo ? c.empresa : null].filter(Boolean).join(" · ")}</option>
                      ))}
                      {empresa.trim() && <option value="nova">Nova candidatura ({empresa.trim()})</option>}
                    </select>
                  </label>
                  <label className="rotulo-campo" htmlFor="tr-empresa">Empresa
                    <input id="tr-empresa" className="campo" value={empresa} onChange={(e) => setEmpresa(e.target.value)}
                      placeholder="De que empresa é?" autoComplete="off" />
                  </label>
                </div>
              )}
            </div>
          )}
          {atual && (
            <div className="doc-rodape">
              <span className="meta dica-rodape">
                {eOutro ? "escolha outra categoria para devolver o e-mail à triagem"
                  : `${posicao} de ${n} · ao escolher a categoria, o próximo entra sozinho`}
              </span>
              <Botao tipo="fant" onClick={pular} disabled={n < 2 || gravando}>Pular</Botao>
            </div>
          )}
        </article>
      )}
    </>
  );
}
