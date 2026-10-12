import { useState } from "react";
import { FileText } from "lucide-react";
import { api, eErroDeLLM } from "../../api";
import { data } from "../../comum";
import type { CartaoCandidatura, CartaoConversa, CartaoVaga, StatusCandidatura } from "../../tipos";
import { avisar } from "../../ui/Aviso";
import Botao from "../../ui/Botao";
import { useApp } from "../../ui/contexto";
import { SELO, mensagem } from "../candidaturas/comum";

/** Cartões dentro da resposta, depois do texto do turno: vaga (de `match_job`/`parse_job`) e candidatura. */
export default function Cartoes({ cartoes, abrirCandidatura }: { cartoes: CartaoConversa[]; abrirCandidatura: (id: number) => void }) {
  return (
    <>
      {cartoes.map((c) => (c.tipo === "vaga"
        ? <Vaga key={`v${c.job_id}`} vaga={c} />
        : <Candidatura key={`c${c.id}`} cand={c} abrir={() => abrirCandidatura(c.id)} />))}
    </>
  );
}

function Vaga({ vaga }: { vaga: CartaoVaga }) {
  const { abrir, semLLM } = useApp();
  const [gerando, setGerando] = useState(false);
  const meta = [vaga.empresa, vaga.senioridade, vaga.local].filter(Boolean).join(" · ");

  async function gerar() {
    setGerando(true);
    try {
      await api.post("/api/curriculos", { job_id: vaga.job_id });
      avisar("Currículo gerado · a candidatura fica em “A enviar”", { rotulo: "Abrir", onClick: () => abrir("curriculos") });
    } catch (e) {
      avisar(mensagem(e), eErroDeLLM(e) ? { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") } : undefined);
    } finally {
      setGerando(false);
    }
  }

  return (
    <article className="cartao-conversa cresce" aria-label={`Vaga: ${vaga.titulo}`}>
      <div className="topo">
        <div className="tx">
          <h3>{vaga.titulo}</h3>
          <p className="meta">{meta}</p>
        </div>
        {vaga.score === null
          ? <span className="score"><b>—</b>sem requisitos</span>
          : <span className="score"><b>{vaga.score}</b>/100</span>}
      </div>
      <div className="lacunas">
        <p className="meta">
          Cobre {vaga.cobertos} de {vaga.total} requisitos.{vaga.lacunas.length ? " Falta evidência em:" : ""}
        </p>
        {vaga.lacunas.length > 0 && <ul>{vaga.lacunas.map((l) => <li key={l}>{l}</li>)}</ul>}
      </div>
      <div className="acoes">
        <Botao tipo="prim" icone={<FileText size={15} strokeWidth={1.5} aria-hidden />} onClick={gerar} ocupado={gerando}
          textoOcupado="Gerando currículo…" disabled={semLLM} title={semLLM ? "Configure um LLM para gerar o currículo" : undefined}>
          Gerar currículo sob medida
        </Botao>
        <Botao onClick={() => abrir("vagas", String(vaga.job_id))}>Abrir vaga</Botao>
      </div>
    </article>
  );
}

function Candidatura({ cand, abrir }: { cand: CartaoCandidatura; abrir: () => void }) {
  const nome = SELO[cand.status as StatusCandidatura]?.nome ?? cand.status;
  const etapa = nome.charAt(0).toUpperCase() + nome.slice(1);
  return (
    <article className="cartao-conversa cresce" aria-label={`Candidatura: ${cand.titulo ?? cand.empresa ?? ""}`}>
      <div className="tx">
        <h3>{cand.titulo ?? cand.empresa ?? "Candidatura"}</h3>
        <p className="meta">{[cand.titulo ? cand.empresa : null, etapa].filter(Boolean).join(" · ")}</p>
      </div>
      {cand.ultimo_email && (
        <p className="ultimo-email">
          <span className="meta">Último e-mail, {data(cand.ultimo_email.recebido_em)}:</span> {cand.ultimo_email.assunto}
        </p>
      )}
      <div className="acoes"><Botao onClick={abrir}>Abrir candidatura</Botao></div>
    </article>
  );
}
