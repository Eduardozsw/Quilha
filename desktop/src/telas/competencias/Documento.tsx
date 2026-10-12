import type { ReactNode } from "react";
import { Link2, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import { api } from "../../api";
import type { Candidato, DetalheCompetencia, Evidencia } from "../../tipos";
import Botao from "../../ui/Botao";
import { avisar } from "../../ui/Aviso";
import { DocCorpo } from "../../ui/ListaSelecao";
import Menu from "../../ui/Menu";
import Selo from "../../ui/Selo";
import { mensagem } from "../candidaturas/comum";
import Medidor from "./Medidor";
import { dataCurta, grupo, plural, referencia, type Grupo } from "./comum";

const ICONE = { size: 16, strokeWidth: 1.5, "aria-hidden": true } as const;

const SELO: Record<Grupo, { tom: "ok" | "at" | "ne"; nome: string }> = {
  sustenta: { tom: "ok", nome: "sustenta o currículo" },
  falta: { tom: "at", nome: "falta evidência" },
  sem: { tom: "ne", nome: "sem nível" },
};

const FORCAS = [
  { n: 1, nome: "fraca" },
  { n: 2, nome: "média" },
  { n: 3, nome: "forte" },
];

type Props = {
  detalhe: DetalheCompetencia | null;
  erro: string | null;
  carregando: boolean;
  aoMudar: () => void;
  aoMudarNivel: () => void;
  aoLigar: () => void;
  aoRemover: () => void;
  /** "Fechar a lacuna", o histórico e os commits sem resposta */
  depois?: ReactNode;
};

type Desligada = { slug: string; nivel_sem_base: string | null; forca?: number; tem_metrica?: boolean; observacao?: string | null };

function Fonte({ nota, bloco }: { nota: string; bloco: string }) {
  return (
    <span className="fonte-evid meta">
      <Link2 size={13} strokeWidth={1.5} aria-hidden /> {nota} · ^{bloco}
    </span>
  );
}

/** Uma evidência do vault: a citação, a fonte e o "⋯" com a força e "Desligar" (com "Desfazer" no aviso). */
function LinhaEvidencia({ slug, ev, aoMudar }: { slug: string; ev: Evidencia; aoMudar: () => void }) {
  const ref = referencia(ev.nota, ev.block_id);

  async function ligar(forca: number) {
    await api.post(`/api/competencias/${slug}/evidencias`, { referencia: ref, forca, metrica: !!ev.tem_metrica });
  }

  async function mudarForca(forca: number) {
    try {
      await ligar(forca);
      avisar(`Força ${FORCAS.find((f) => f.n === forca)?.nome}`);
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  async function desligar() {
    try {
      const r = await api.del<Desligada>(`/api/competencias/${slug}/evidencias?referencia=${encodeURIComponent(ref)}`);
      aoMudar();
      avisar(r.nivel_sem_base ? `Evidência desligada · ${r.nivel_sem_base}` : "Evidência desligada", {
        rotulo: "Desfazer",
        // a ligação volta inteira (força, métrica, observação), mesmo se o fato já saiu do vault
        onClick: () => api.post(`/api/competencias/${slug}/evidencias`, {
          referencia: ref, forca: r.forca ?? ev.forca, metrica: r.tem_metrica ?? !!ev.tem_metrica,
          obs: r.observacao ?? null, restaurar: true,
        }).then(aoMudar, (e) => avisar(mensagem(e))),
      });
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  return (
    <li className="evid">
      <div className="tx-evid">
        <p className={ev.texto === null ? "sumiu" : undefined}>{ev.texto ?? "O fato sumiu do vault"}</p>
        <Fonte nota={ev.nota} bloco={ev.block_id} />
      </div>
      <Menu
        rotulo="Opções da evidência"
        gatilho={<MoreHorizontal {...ICONE} />}
        itens={[
          ...FORCAS.map((f) => ({ rotulo: `Força ${f.nome}`, marcado: ev.forca === f.n, aoEscolher: () => mudarForca(f.n) })),
          { rotulo: "Desligar", perigo: true, separado: true, aoEscolher: desligar },
        ]}
      />
    </li>
  );
}

/** Candidato do vault com "Ligar" direto: força média, como na folha de ligar. */
export function LinhaCandidato({ c, aoLigar, ligado }: { c: Candidato; aoLigar: () => void; ligado?: boolean }) {
  const [nota, bloco] = c.referencia.split("#");
  return (
    <li className="evid">
      <div className="tx-evid">
        <p>{c.texto}</p>
        <span className="fonte-linha">
          <Fonte nota={nota} bloco={bloco} />
          {c.tem_metrica && <span className="com-metrica">com métrica</span>}
        </span>
      </div>
      {ligado ? <span className="ligado-evid">✓ Ligado</span> : <Botao onClick={aoLigar}>Ligar</Botao>}
    </li>
  );
}

/** Documento da competência: contexto e selo, título, nível com "Mudar nível", justificativa e evidências do vault. */
export default function Documento({ detalhe: d, erro, carregando, aoMudar, aoMudarNivel, aoLigar, aoRemover, depois }: Props) {
  if (!d) return <article className="doc" aria-busy={carregando || undefined}>{erro && <p className="erro-tela">{erro}</p>}</article>;
  const c = d.competencia;
  const g = grupo(c);
  const n = d.evidencias.length;

  async function ligarCandidato(cand: Candidato) {
    try {
      await api.post(`/api/competencias/${c.slug}/evidencias`, { referencia: cand.referencia, forca: 2 });
      avisar("Fato ligado");
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  return (
    <article className="doc doc-comp" aria-busy={carregando || undefined}>
      <DocCorpo chave={c.slug}>
        <header className="topo-comp">
          <div>
            <div className="meta-comp">
              <span className="meta">peso {c.peso} · {n === 0 ? "nenhuma evidência" : plural(n, "evidência", "evidências")}</span>
              <Selo tom={SELO[g].tom}>{SELO[g].nome}</Selo>
            </div>
            <h3>{c.nome}</h3>
          </div>
          <Menu rotulo="Opções da competência" gatilho={<MoreHorizontal {...ICONE} />}
            itens={[{ rotulo: "Remover competência", icone: <Trash2 {...ICONE} />, perigo: true, aoEscolher: aoRemover }]} />
        </header>
        {erro && <p className="erro-tela">{erro}</p>}

        <div className="linha-nivel">
          <Medidor nivel={c.nivel} grupo={g} />
          {c.nivel !== null ? (
            <>
              <button className="nivel-declarado" onClick={aoMudarNivel}>
                Nível {c.nivel}{c.avaliado_em ? `, declarado em ${dataCurta(c.avaliado_em)}` : ""}
              </button>
              <Botao tipo="fant" onClick={aoMudarNivel}>Mudar nível</Botao>
            </>
          ) : (
            <>
              <span>Ainda sem nível</span>
              <span className="meta" aria-hidden>·</span>
              <button className="declarar" onClick={aoMudarNivel}>Declarar nível</button>
            </>
          )}
        </div>
        {c.nivel !== null && c.justificativa && <p className="justificativa">“{c.justificativa}”</p>}

        <section className="secao-comp">
          <div className="titulo-secao">
            <h2>Evidências do vault</h2>
            <Botao tipo="fant" icone={<Plus {...ICONE} />} onClick={aoLigar}>Ligar um fato</Botao>
          </div>
          {n > 0 ? (
            <ul className="evids">
              {d.evidencias.map((ev) => <LinhaEvidencia key={referencia(ev.nota, ev.block_id)} slug={c.slug} ev={ev} aoMudar={aoMudar} />)}
            </ul>
          ) : d.candidatos.length > 0 ? (
            <>
              <p className="meta">O vault parece ter isto:</p>
              <ul className="evids">
                {d.candidatos.map((cand) => <LinhaCandidato key={cand.referencia} c={cand} aoLigar={() => ligarCandidato(cand)} />)}
              </ul>
            </>
          ) : (
            <p className="meta">Nenhum fato no vault ainda.</p>
          )}
        </section>
        {depois}
      </DocCorpo>
    </article>
  );
}
