import { useState } from "react";
import { GitCommitHorizontal, MoreHorizontal } from "lucide-react";
import { api } from "../../api";
import type { DetalheCompetencia, EstudoFeito, Sinal } from "../../tipos";
import Botao from "../../ui/Botao";
import { avisar } from "../../ui/Aviso";
import Menu from "../../ui/Menu";
import { haTempo, mensagem } from "../candidaturas/comum";
import { quando } from "./comum";

const MAX_COMMITS = 5;

type Props = {
  detalhe: DetalheCompetencia;
  /** commits sem resposta (de todos os repositórios), mais recentes primeiro; `null` se a leitura falhou */
  sinais: Sinal[] | null;
  lidosEm: string | null;
  lendo: boolean;
  aoLerDeNovo: () => void;
  /** um estudo foi gravado ou um commit respondido: detalhe, cabeçalho e commits recarregam */
  aoMudar: () => void;
};

/** "feat: consulta via GraphQL" → "consulta via GraphQL": o ponto de partida do que você estudou. */
function semPrefixo(resumo: string): string {
  return resumo.replace(/^[a-z]+(\([^)]*\))?!?:\s*/i, "");
}

function Minutos({ id, valor, aoMudar }: { id: string; valor: string; aoMudar: (v: string) => void }) {
  return (
    <label className="campo-min" htmlFor={id}>
      <input id={id} className="campo" inputMode="numeric" value={valor} aria-label="Minutos"
        onChange={(e) => aoMudar(e.target.value.replace(/\D/g, ""))} />
      <span aria-hidden>min</span>
    </label>
  );
}

/** Linha do commit: "Foi estudo" abre a linha inline; "Não foi estudo" mora no "⋯". */
function LinhaCommit({ s, slug, nome, aoMudar }: { s: Sinal; slug: string; nome: string; aoMudar: () => void }) {
  const [aberta, setAberta] = useState(false);
  const [min, setMin] = useState("30");
  const [oQue, setOQue] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function gravar() {
    setOcupado(true);
    try {
      await api.post("/api/estudos/sinais/confirmar", { ids: [s.id], minutos: Number(min), o_que_fez: oQue.trim(), comp: slug });
      avisar(`Estudo registrado · ${min} min em ${nome}`);
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  async function ignorar() {
    try {
      await api.post("/api/estudos/sinais/ignorar", { ids: [s.id] });
      avisar("Commit marcado como não estudo");
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  if (aberta)
    return (
      <li className="commit aberto">
        <form className="linha-estudo" onSubmit={(e) => { e.preventDefault(); if (Number(min) > 0 && oQue.trim() && !ocupado) gravar(); }}>
          <Minutos id={`min-${s.id}`} valor={min} aoMudar={setMin} />
          <input className="campo" value={oQue} aria-label="O que você estudou" autoFocus
            onChange={(e) => setOQue(e.target.value)} />
          <span className="meta em-comp">em {nome}</span>
          <Botao tipo="prim" submit ocupado={ocupado} disabled={!(Number(min) > 0) || !oQue.trim()}>Gravar</Botao>
          <Botao tipo="fant" onClick={() => setAberta(false)} disabled={ocupado}>Cancelar</Botao>
        </form>
      </li>
    );
  return (
    <li className="commit">
      <GitCommitHorizontal size={16} strokeWidth={1.5} aria-hidden />
      <span className="resumo-commit">{s.resumo}</span>
      <span className="meta">{s.repo} · {quando(s.data)}</span>
      <Botao tipo="fant" onClick={() => { setOQue(semPrefixo(s.resumo)); setAberta(true); }}>Foi estudo</Botao>
      <Menu rotulo="Opções do commit" gatilho={<MoreHorizontal size={16} strokeWidth={1.5} aria-hidden />}
        itens={[{ rotulo: "Não foi estudo", aoEscolher: ignorar }]} />
    </li>
  );
}

/** "Fechar a lacuna" (decisões 5, 6 e 8): registrar estudo, commits sem resposta e o histórico da competência. */
export default function FecharLacuna({ detalhe, sinais, lidosEm, lendo, aoLerDeNovo, aoMudar }: Props) {
  const c = detalhe.competencia;
  const [min, setMin] = useState("30");
  const [oQue, setOQue] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [todosCommits, setTodosCommits] = useState(false);
  const [todosEstudos, setTodosEstudos] = useState<EstudoFeito[] | null>(null);

  async function registrar() {
    setOcupado(true);
    try {
      await api.post("/api/estudos/sessoes", { minutos: Number(min), o_que_fez: oQue.trim(), comp: c.slug });
      avisar(`Estudo registrado · ${min} min em ${c.nome}`);
      setOQue("");
      setTodosEstudos(null);
      aoMudar();
    } catch (e) {
      avisar(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  async function verTodos() {
    try {
      setTodosEstudos(await api.get<EstudoFeito[]>(`/api/competencias/${c.slug}/estudos`));
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  const commits = sinais ?? [];
  const visiveis = todosCommits ? commits : commits.slice(0, MAX_COMMITS);
  const estudos = todosEstudos ?? detalhe.estudos.ultimos;

  return (
    <section className="secao-comp fechar-lacuna">
      <div className="titulo-secao">
        <h2>Fechar a lacuna <small>estudo conta quando você diz o que estudou</small></h2>
      </div>
      <form className="linha-estudo" onSubmit={(e) => { e.preventDefault(); if (Number(min) > 0 && oQue.trim() && !ocupado) registrar(); }}>
        <Minutos id="estudo-min" valor={min} aoMudar={setMin} />
        <input className="campo" value={oQue} placeholder="O que você estudou, ex.: mocks de rede no Playwright"
          aria-label="O que você estudou" onChange={(e) => setOQue(e.target.value)} />
        <Botao submit ocupado={ocupado} disabled={!(Number(min) > 0) || !oQue.trim()}>Registrar estudo</Botao>
      </form>

      {commits.length > 0 && (
        <div className="commits">
          <div className="meta cab-commits">
            Commits sem resposta{lidosEm && ` · lidos ${haTempo(lidosEm)}`} ·{" "}
            <button className="ler-de-novo" onClick={aoLerDeNovo} disabled={lendo}>{lendo ? "Lendo…" : "Ler de novo"}</button>
          </div>
          <ul>
            {visiveis.map((s) => <LinhaCommit key={s.id} s={s} slug={c.slug} nome={c.nome} aoMudar={aoMudar} />)}
          </ul>
          {commits.length > MAX_COMMITS && !todosCommits && (
            <button className="ver-tudo" onClick={() => setTodosCommits(true)}>Ver todos ({commits.length})</button>
          )}
        </div>
      )}

      {detalhe.estudos.total > 0 && (
        <div className="historico">
          <h3 className="titulo-hist">Estudado</h3>
          <ul>
            {estudos.map((e, i) => (
              <li key={i} className="meta"><span className="tabular">{e.minutos} min</span> · {e.o_que_fez} · {quando(e.data)}</li>
            ))}
          </ul>
          {detalhe.estudos.total > estudos.length && (
            <button className="ver-tudo" onClick={verTodos}>Ver todos ({detalhe.estudos.total})</button>
          )}
        </div>
      )}
    </section>
  );
}
