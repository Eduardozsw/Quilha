import { useEffect, useState } from "react";
import { ErroApi, api, eErroDeLLM } from "../../api";
import { abrirExterno } from "../../comum";
import type { Competencia, PlanoGerado, Semana } from "../../tipos";
import Botao from "../../ui/Botao";
import { avisar } from "../../ui/Aviso";
import { useApp } from "../../ui/contexto";
import Folha from "../../ui/Folha";
import UsaLLM from "../../ui/UsaLLM";
import { mensagem } from "../candidaturas/comum";

type Props = {
  aberta: boolean;
  semana: Semana | null;
  competencias: Competencia[];
  aoFechar: () => void;
  /** o plano da semana mudou (gerado ou descartado) */
  aoMudar: () => void;
};

const MES = ["jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."];

/** "6 a 12 de out."; virando o mês, "29 de set. a 5 de out.". */
export function intervalo(inicio: string, fim: string): string {
  const [, m1, d1] = inicio.split("-").map(Number);
  const [, m2, d2] = fim.split("-").map(Number);
  return m1 === m2 ? `${d1} a ${d2} de ${MES[m2 - 1]}` : `${d1} de ${MES[m1 - 1]} a ${d2} de ${MES[m2 - 1]}`;
}

function custo(v: number | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  return v < 0.005 ? "< US$ 0,01" : `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

type Gravado = { ja_gravado: boolean; obsidian?: string };

/** O plano gerado e ainda não gravado nem descartado, fora do componente: sair da tela e voltar não obriga a
 *  gerar de novo (gerar custa crédito). Vale enquanto o app está aberto. */
let planoPendente: PlanoGerado | null = null;

/** Plano da semana (decisão 7): o feito contra o alvo; o da próxima semana é gerado aqui e só vai ao vault em "Gravar no vault". */
export default function FolhaPlano({ aberta, semana: s, competencias, aoFechar, aoMudar }: Props) {
  const { semLLM, abrir } = useApp();
  const [minutos, setMinutos] = useState("300");
  // o plano guardado de uma semana que já acabou (app aberto de uma semana para a outra) não volta
  const [gerado, setGeradoLocal] = useState<PlanoGerado | null>(() => {
    if (planoPendente && planoPendente.fim < new Date().toLocaleDateString("sv")) planoPendente = null;
    return planoPendente;
  });
  function setGerado(p: PlanoGerado | null) {
    planoPendente = p;
    setGeradoLocal(p);
  }
  const [gravado, setGravado] = useState(false);
  const [ocupado, setOcupado] = useState<"gerar" | "gravar" | "descartar" | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // já existe plano para a próxima semana: gerar de novo substitui, então a folha pergunta antes
  const [existe, setExiste] = useState(false);

  // reabrir a folha mantém o plano gerado e ainda não gravado: gerar de novo custaria crédito
  useEffect(() => {
    if (!aberta) return;
    setErro(null);
    setExiste(false);
    if (gravado) { setGerado(null); setGravado(false); }
  }, [aberta]); // eslint-disable-line react-hooks/exhaustive-deps

  const nome = (slug: string | null) => competencias.find((c) => c.slug === slug)?.nome ?? slug ?? "Sem competência";

  // itens da mesma competência dividem o feito: soma o alvo por competência
  const linhas = new Map<string, { alvo: number; feito: number }>();
  for (const i of s?.plano?.itens ?? []) {
    const k = i.competencia ?? "";
    const l = linhas.get(k) ?? { alvo: 0, feito: i.minutos_feitos };
    linhas.set(k, { alvo: l.alvo + i.minutos_alvo, feito: l.feito });
  }

  async function gerar(substituir: boolean) {
    setOcupado("gerar");
    setErro(null);
    try {
      setGerado(await api.post<PlanoGerado>("/api/estudos/plano", { minutos: Number(minutos), substituir }));
      setGravado(false);
      setExiste(false);
      aoMudar();
    } catch (e) {
      if (e instanceof ErroApi && e.status === 409) setExiste(true);
      else if (eErroDeLLM(e)) avisar(mensagem(e), { rotulo: "Configurar LLM", onClick: () => abrir("configuracoes", "llm") });
      else setErro(mensagem(e));
    } finally {
      setOcupado(null);
    }
  }

  async function gravar() {
    if (!gerado) return;
    setOcupado("gravar");
    try {
      const r = await api.post<Gravado>(`/api/estudos/plano/${gerado.semana}/vault`);
      setGravado(true);
      planoPendente = null; // gravado: o que fica na folha é só o aviso, e reabrir começa do zero
      if (r.ja_gravado) avisar("Este plano já está no Diário");
      else if (r.obsidian) avisar("Plano gravado no Diário", { rotulo: "Abrir no Obsidian", onClick: () => abrirExterno(r.obsidian!) });
      else avisar("Plano gravado no Diário");
    } catch (e) {
      setErro(e instanceof ErroApi ? e.message : mensagem(e));
    } finally {
      setOcupado(null);
    }
  }

  async function descartar() {
    if (!gerado) return;
    setOcupado("descartar");
    try {
      await api.del(`/api/estudos/plano/${gerado.semana}`);
      setGerado(null);
      avisar("Plano descartado");
      aoMudar();
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setOcupado(null);
    }
  }

  const rodape = gerado ? (
    <>
      {custo(gerado.custo.custo_usd) && <span className="meta dica-folha tabular">custou {custo(gerado.custo.custo_usd)}</span>}
      {!gerado.ja_existia && !gravado && <Botao tipo="fant" onClick={descartar} ocupado={ocupado === "descartar"}>Descartar</Botao>}
      {gravado ? <Botao tipo="fant" onClick={aoFechar}>Fechar</Botao>
        : <Botao tipo="prim" onClick={gravar} ocupado={ocupado === "gravar"} textoOcupado="Gravando…">Gravar no vault</Botao>}
    </>
  ) : (
    <>
      <UsaLLM para="gerar o plano" />
      <Botao tipo="fant" onClick={aoFechar}>Fechar</Botao>
      <Botao tipo="prim" onClick={() => gerar(existe)} ocupado={ocupado === "gerar"} textoOcupado="Gerando…"
        disabled={semLLM || !(Number(minutos) >= 30)}>{existe ? "Substituir plano" : "Gerar plano da próxima semana"}</Botao>
    </>
  );

  return (
    <Folha aberta={aberta} titulo="Plano da semana" largura={640} aoFechar={() => { if (!ocupado) aoFechar(); }} rodape={rodape}>
      {s && (
        <p className="sub-folha">
          {intervalo(s.inicio, s.fim)} · {s.plano ? `${s.minutos} de ${s.minutos_alvo} min` : `${s.minutos} min`} estudados
        </p>
      )}
      {s?.plano ? (
        <ul className="barras-plano">
          {[...linhas].map(([slug, l]) => (
            <li key={slug}>
              <span className="nome-plano">{nome(slug || null)}</span>
              <span className="barra-plano" aria-hidden><i style={{ width: `${Math.min(100, (l.feito / l.alvo) * 100)}%` }} /></span>
              <span className="meta tabular">{l.feito} de {l.alvo} min</span>
            </li>
          ))}
        </ul>
      ) : s && <p>Ainda sem plano para esta semana.</p>}
      <div className="caixa-proxima">
        <b>Próxima semana{gerado ? ` · ${intervalo(gerado.inicio, gerado.fim)}` : ""}</b>
        {gerado ? (
          <>
            {gerado.plano.objetivo && <p>{gerado.plano.objetivo}</p>}
            <ul className="itens-plano">
              {gerado.plano.itens.map((i, k) => (
                <li key={k}>
                  <span className="tx">
                    <b>{nome(i.competencia)}</b>
                    <span className="meta">{i.descricao}{i.recurso ? ` · ${i.recurso}` : ""}</span>
                  </span>
                  <span className="meta tabular">{i.minutos_alvo} min</span>
                </li>
              ))}
            </ul>
            {gravado && <p className="meta">Gravado no Diário do vault.</p>}
          </>
        ) : (
          <>
            <p>O Quilha divide o seu tempo pelas lacunas das vagas abertas. Você revisa antes de gravar no vault.</p>
            {existe && <p className="aviso-existe" role="status">Já existe um plano para a próxima semana. Gerar de novo substitui esse plano.</p>}
            <label className="tempo-semana" htmlFor="plano-min">
              <span className="meta">Tempo que você tem na semana</span>
              <span className="campo-min">
                <input id="plano-min" className="campo" inputMode="numeric" value={minutos}
                  onChange={(e) => setMinutos(e.target.value.replace(/\D/g, ""))} />
                <span aria-hidden>min</span>
              </span>
            </label>
          </>
        )}
      </div>
      {erro && <div className="erro-folha" role="alert">{erro}</div>}
    </Folha>
  );
}
