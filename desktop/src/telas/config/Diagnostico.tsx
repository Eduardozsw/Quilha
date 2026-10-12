import { Copy, Download, FolderOpen } from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import { mostrarNaPasta, useCarregar } from "../../comum";
import { quando } from "../../formato";
import type { Problema, Run } from "../../tipos";
import { avisar } from "../../ui/Aviso";
import Botao from "../../ui/Botao";
import Selo from "../../ui/Selo";
import { Divisor, frase, Linha, Painel, type PropsSecao } from "./pecas";

const NOME_EXECUCAO: Record<string, string> = {
  index: "Indexação do vault", "job collect": "Coleta de vagas", "job extrair": "Requisitos extraídos",
  "job add": "Vaga adicionada", "job map": "Vaga comparada com o vault", "job match": "Vaga comparada com o vault",
  "cv draft": "Currículo redigido", "cv pdf": "PDF do currículo", "email sync": "Triagem de e-mails",
  chat: "Conversa", "comp assess": "Competência avaliada", "comp evidence": "Evidência de competência",
  "comp export": "Competências exportadas", "comp seed": "Competências carregadas", "comp remove": "Competência removida",
  backup: "Cópia do banco", "interview prep": "Roteiro de entrevista", "llm teste": "Teste da chave do LLM",
  "study log": "Estudo registrado", "study plan": "Plano de estudo", "study git": "Atividade do Git",
  "study confirm": "Estudo confirmado", "study ignore": "Estudo ignorado", "mcp call": "Ferramenta externa",
};

const STATUS: Record<Run["status"], { tom: "ok" | "at" | "er"; texto: string }> = {
  success: { tom: "ok", texto: "ok" }, partial: { tom: "at", texto: "parcial" }, failed: { tom: "er", texto: "falhou" },
};

type Resumo = { runs: Run[]; gasto_30d: { total: number; chamadas: number } };

const dinheiro = (v: number) => `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Sem custo: execução sem LLM ou com modelo local (custo 0); menos de um centavo: "< US$ 0,01" (nunca "US$ 0,00"). */
function valor(v: number): string {
  if (v === 0) return "sem custo";
  return v < 0.005 ? "< US$ 0,01" : dinheiro(v);
}

function custo(r: Run): string {
  if (!r.llm_calls) return "sem custo";
  if (r.cost_usd === null) return "custo desconhecido";
  return valor(r.cost_usd);
}

const AVISOS_VISIVEIS = 5;

/** Configurações → Diagnóstico: avisos do vault, execuções recentes com custo e os arquivos do Quilha. */
export default function Diagnostico({ config, recarregarConfig }: PropsSecao) {
  const avisos = useCarregar(() => api.get<Problema[]>("/api/operacao/check"));
  const resumo = useCarregar(() => api.get<Resumo>("/api/operacao/resumo"));
  const [ocupado, setOcupado] = useState<"copia" | "export" | null>(null);
  const agora = new Date();
  const runs = (resumo.dados?.runs ?? []).filter((r) => !r.comando.startsWith("app ")).slice(0, 10);
  const gasto = resumo.dados?.gasto_30d;
  const p = config.pastas;
  // lista longa de avisos empurrava Execuções e Arquivos para fora da tela: 5 e "Ver todos"
  const [todos, setTodos] = useState(false);
  const listaAvisos = avisos.dados ?? [];
  const avisosVisiveis = todos ? listaAvisos : listaAvisos.slice(0, AVISOS_VISIVEIS);

  async function copiar() {
    setOcupado("copia");
    try {
      await api.post("/api/operacao/backup");
      avisar("Cópia do banco salva");
      recarregarConfig();
      resumo.recarregar();
    } catch (e) {
      avisar(frase(e instanceof Error ? e.message : String(e)));
    } finally {
      setOcupado(null);
    }
  }

  async function exportar() {
    setOcupado("export");
    try {
      const r = await api.post<{ caminho: string }>("/api/competencias/exportar");
      avisar(`Competências exportadas para ${r.caminho}`);
      resumo.recarregar();
    } catch (e) {
      avisar(frase(e instanceof Error ? e.message : String(e)));
    } finally {
      setOcupado(null);
    }
  }

  return (
    <Painel titulo="Diagnóstico"
      descricao="Os avisos do vault, o que o Quilha executou e onde ficam os seus arquivos. Comece por aqui quando algo não sair como esperado.">
      <div className="config-grupo">
        <div className="rotulo-grupo">Avisos do vault {avisos.dados && <span className="n">{avisos.dados.length}</span>}</div>
        {avisos.erro && <div className="erro-caixa" role="alert">{frase(avisos.erro)}</div>}
        {avisos.dados?.length === 0 && <p className="meta">Nenhum aviso no vault.</p>}
        {!!avisos.dados?.length && (
          <ul className="config-lista">
            {avisosVisiveis.map((a, i) => (
              <li key={i} className="config-item inicio">
                <Selo tom={a.nivel === "erro" ? "er" : "at"}>{a.nivel}</Selo>
                <div className="texto">
                  <strong className="normal">{frase(a.mensagem)}</strong>
                  <span>{a.nota}{a.linha ? ` · linha ${a.linha}` : ""}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
        {listaAvisos.length > AVISOS_VISIVEIS && (
          <button className="config-link" onClick={() => setTodos((t) => !t)} aria-expanded={todos}>
            {todos ? "Mostrar só os 5 primeiros" : `Ver todos (${listaAvisos.length})`}
          </button>
        )}
      </div>
      <Divisor />
      <div className="config-grupo">
        <div className="rotulo-grupo">Execuções recentes</div>
        {gasto && (
          <p className="meta resumo-gasto">
            {gasto.chamadas
              ? `${gasto.total === 0 ? "Sem custo" : valor(gasto.total)} nos últimos 30 dias, em ${gasto.chamadas} ${gasto.chamadas === 1 ? "execução" : "execuções"} com o seu LLM`
              : "Nenhuma execução com o seu LLM nos últimos 30 dias"}
          </p>
        )}
        {resumo.dados && !runs.length && <p className="meta">Nada executado ainda.</p>}
        <ul className="config-lista">
          {runs.map((r) => (
            <li key={r.id} className="config-item">
              <div className="texto">
                <strong>{NOME_EXECUCAO[r.comando] ?? r.comando}</strong>
                <span>
                  {quando(r.started_at, agora).toLowerCase()}
                  {r.model && r.llm_calls ? ` · ${r.model}` : ""}
                  {r.llm_calls ? ` · ${r.llm_calls} ${r.llm_calls === 1 ? "chamada" : "chamadas"}` : ""}
                </span>
                {r.error && <span className="erro">{frase(r.error)}</span>}
              </div>
              <div className="direita">
                <span className={r.llm_calls ? "meta" : "meta sem-custo"}>{custo(r)}</span>
                <Selo tom={STATUS[r.status].tom}>{STATUS[r.status].texto}</Selo>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <Divisor />
      <div className="config-grupo arquivos">
        <div className="rotulo-grupo">Arquivos</div>
        <Linha titulo="Pasta de saída" descricao={`${p.saida} · currículos em PDF e exportações`}>
          <Botao icone={<FolderOpen size={15} strokeWidth={1.75} aria-hidden />} onClick={() => mostrarNaPasta(p.saida)}>Mostrar na pasta</Botao>
        </Linha>
        <Linha titulo="Cópia do banco"
          descricao={p.ultima_copia ? `Última cópia ${quando(p.ultima_copia, agora).toLowerCase()} · ${p.backups}` : `Nenhuma cópia ainda · ficam em ${p.backups}`}>
          <Botao icone={<Copy size={15} strokeWidth={1.75} aria-hidden />} onClick={copiar} ocupado={ocupado === "copia"} textoOcupado="Copiando…">
            Copiar o banco
          </Botao>
        </Linha>
        <Linha titulo="Competências" descricao="Exporta os seus níveis e evidências como nota no vault">
          <Botao icone={<Download size={15} strokeWidth={1.75} aria-hidden />} onClick={exportar} ocupado={ocupado === "export"} textoOcupado="Exportando…">
            Exportar competências
          </Botao>
        </Linha>
      </div>
    </Painel>
  );
}
