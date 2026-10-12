import { useState, type ReactNode } from "react";
import { BookOpen, Check, ChevronDown, Clock, Mail, Send } from "lucide-react";
import { api } from "../../api";
import { CorpoEmail } from "../../corpoEmail";
import type { DetalheCandidatura, EmailProcesso } from "../../tipos";
import { avisar } from "../../ui/Aviso";
import Selo from "../../ui/Selo";
import { CATEGORIAS, entrevistaFutura, mensagem, nomeCategoria, quandoEntrevista, quandoMarco } from "./comum";

const ICONE = { size: 15, strokeWidth: 1.6, "aria-hidden": true } as const;
const NOVO_MS = 48 * 3600 * 1000; // o e-mail mais recente abre sozinho se chegou nas últimas 48 h

type Props = {
  detalhe: DetalheCandidatura;
  nomePerfil: (slug: string | null) => string | null;
  aoMudar: () => void;
};

type Marco = { chave: string; icone: ReactNode; quando: string; data: string; proximo?: boolean; titulo: ReactNode; email?: EmailProcesso };

/** Linha do tempo (spec §4): marcos de 28 px ligados por fio de 2 px, do mais recente para o mais antigo;
 *  a entrevista futura fica fixa no topo com o selo "Próximo" (decisão 7). */
export default function LinhaDoTempo({ detalhe, nomePerfil, aoMudar }: Props) {
  const { candidatura: c, cv, emails } = detalhe;
  const agora = new Date();
  const futura = entrevistaFutura(c.entrevista_em, agora);
  const tituloEntrevista = c.entrevista_titulo || "Entrevista";

  const datados: Marco[] = emails.map((e) => ({
    chave: `e${e.id}`, icone: <Mail {...ICONE} />, data: e.recebido_em, quando: quandoMarco(e.recebido_em, agora),
    titulo: e.assunto || "(sem assunto)", email: e,
  }));
  if (c.entrevista_em && !futura)
    datados.push({ chave: "entrevista", icone: <Clock {...ICONE} />, data: c.entrevista_em,
      quando: quandoMarco(c.entrevista_em, agora), titulo: tituloEntrevista });
  datados.sort((a, b) => new Date(b.data).getTime() - new Date(a.data).getTime());

  const marcos: Marco[] = [];
  if (c.entrevista_em && futura)
    marcos.push({ chave: "proxima", icone: <Clock {...ICONE} />, data: c.entrevista_em, proximo: true,
      quando: quandoEntrevista(c.entrevista_em, agora), titulo: tituloEntrevista });
  marcos.push(...datados);
  const perfil = nomePerfil(c.perfil);
  if (c.status === "a_enviar") {
    const fatos = cv?.n_fatos ? ` · ${cv.n_fatos} fatos do vault` : "";
    marcos.push({ chave: "gerado", icone: <BookOpen {...ICONE} />, data: cv?.criado_em ?? c.enviada_em,
      quando: quandoMarco(cv?.criado_em ?? c.enviada_em, agora),
      titulo: `Currículo gerado${perfil ? ` com o recorte ${perfil}` : ""}${fatos}` });
  } else if (c.origem !== "email") {
    marcos.push({ chave: "envio", icone: <Send {...ICONE} />, data: c.enviada_em, quando: quandoMarco(c.enviada_em, agora),
      titulo: `Candidatura enviada${perfil ? ` com o currículo ${perfil}` : ""}` });
  }

  const recente = emails.length ? emails.reduce((a, b) => (a.recebido_em > b.recebido_em ? a : b)) : null;
  const abreSozinho = recente && agora.getTime() - new Date(recente.recebido_em).getTime() < NOVO_MS ? recente.id : null;

  return (
    <ol className="linha-tempo">
      {marcos.map((m) => (
        <li key={m.chave} className={`marco${m.proximo ? " proximo" : ""}`}>
          <span className="bola" aria-hidden>{m.icone}</span>
          {m.email ? (
            <MarcoEmail email={m.email} quando={m.quando} abertoAntes={m.email.id === abreSozinho} aoMudar={aoMudar} />
          ) : (
            <div className="cab-marco">
              <span className="titulo-marco">
                {m.proximo && <Selo tom="ok">Próximo</Selo>}
                {m.titulo}
              </span>
              <time dateTime={m.data}>{m.quando}</time>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

function MarcoEmail({ email: e, quando, abertoAntes, aoMudar }: { email: EmailProcesso; quando: string; abertoAntes: boolean; aoMudar: () => void }) {
  const [aberto, setAberto] = useState(abertoAntes);
  const [tudo, setTudo] = useState(false);
  const [gravando, setGravando] = useState<string | null>(null);
  const corpo = (e.corpo ?? "").trim();
  const longo = corpo.length > 260 || corpo.split("\n").length > 3;

  async function corrigir(categoria: string) {
    if (categoria === e.categoria || gravando) return;
    setGravando(categoria);
    try {
      await api.post(`/api/emails/${e.id}/categoria`, { categoria });
      avisar(categoria === "outro" ? "E-mail tirado do processo" : `Categoria: ${nomeCategoria(categoria)}`);
      aoMudar();
    } catch (erro) {
      avisar(mensagem(erro));
    } finally {
      setGravando(null);
    }
  }

  return (
    <div className="marco-email">
      <button className="cab-marco" aria-expanded={aberto} onClick={() => setAberto((a) => !a)}>
        <span className="titulo-marco">
          {`${e.assunto || "(sem assunto)"}${aberto ? "" : ` · ${nomeCategoria(e.categoria)}`}`}
        </span>
        <time dateTime={e.recebido_em}>{quando}</time>
      </button>
      {aberto && (
        <div className="caixa-email troca">
          {corpo ? (
            <CorpoEmail texto={corpo} className={`corpo-email${tudo ? "" : " recolhido"}`} />
          ) : (
            <p className="corpo-email vazio">E-mail sem texto gravado.</p>
          )}
          {longo && (
            <button className="ver-tudo" aria-expanded={tudo} onClick={() => setTudo((t) => !t)}>
              {tudo ? "Recolher" : "Ver tudo"}
              <ChevronDown size={14} strokeWidth={2} aria-hidden />
            </button>
          )}
          <div className="pilulas-cat" role="group" aria-label="Categoria do e-mail">
            <span className="meta">Categoria</span>
            {CATEGORIAS.map((cat) => (
              <button key={cat.id} className="pilula-cat" aria-pressed={cat.id === e.categoria}
                disabled={gravando !== null} onClick={() => corrigir(cat.id)}>
                {cat.id === e.categoria && <Check size={13} strokeWidth={2.2} aria-hidden />}
                {cat.nome}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
