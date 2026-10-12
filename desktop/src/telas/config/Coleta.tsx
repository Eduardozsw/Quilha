import { ArrowUpRight, Briefcase, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import { abrirArquivo, useCarregar } from "../../comum";
import { hora, plural, quando } from "../../formato";
import { avisar } from "../../ui/Aviso";
import Botao from "../../ui/Botao";
import Selo from "../../ui/Selo";
import Vazio from "../../ui/Vazio";
import { Divisor, frase, Painel, type PropsSecao } from "./pecas";

type Fonte = {
  tipo: string; board: string; empresa: string; intervalo_h: number; estado: "ok" | "falhou" | "pendente" | "nova";
  tentativas: number; proximo_em: string | null; ultima_ok_em: string | null; ultimo_erro: string | null;
};
type Estado = { caminho: string; existe: boolean; erro: string | null; fontes: Fonte[]; ultima: { quando: string; vagas_novas: number } | null };
type Resultado = { processadas: number; fontes: number; vagas_novas: number; avisos: string[] };

const TIPO: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", gupy: "Gupy" };

function LinhaFonte({ f }: { f: Fonte }) {
  const agora = new Date();
  let selo, extra: string | null = null;
  if (f.estado === "ok") {
    selo = <Selo tom="ok">ok</Selo>;
    extra = f.ultima_ok_em ? quando(f.ultima_ok_em, agora).toLowerCase() : null;
  } else if (f.estado === "falhou") {
    selo = <Selo tom="er">{f.tentativas > 1 ? `falhou ${f.tentativas} vezes` : "falhou"}</Selo>;
    extra = f.proximo_em ? `tenta de novo às ${hora(new Date(f.proximo_em))}` : null;
  } else {
    selo = <Selo tom="ne">na fila</Selo>;
    extra = f.proximo_em ? `próxima às ${hora(new Date(f.proximo_em))}` : "na próxima coleta";
  }
  return (
    <li className="config-item">
      <div className="texto">
        <strong>{f.empresa}</strong>
        <span>{TIPO[f.tipo] ?? f.tipo} · {f.board} · a cada {f.intervalo_h} h</span>
        {f.estado === "falhou" && f.ultimo_erro && <span className="erro">{frase(f.ultimo_erro)}</span>}
      </div>
      <div className="direita">
        {extra && <span className="meta">{extra}</span>}
        {selo}
      </div>
    </li>
  );
}

/** Configurações → Coleta de vagas: a fila por fonte, "Coletar agora" e o `fontes.yaml` (o editor vem depois do lançamento). */
export default function Coleta({ recarregarSaude }: PropsSecao) {
  const estado = useCarregar(() => api.get<Estado>("/api/coletor/estado"));
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const e = estado.dados;

  async function coletar() {
    setOcupado(true);
    setErro(null);
    try {
      const r = await api.post<Resultado>("/api/coletor/coletar", {});
      avisar(`${plural(r.vagas_novas, "vaga nova", "vagas novas")} em ${plural(r.processadas, "fonte", "fontes")}`);
      estado.recarregar();
      recarregarSaude();
    } catch (x) {
      setErro(x instanceof Error ? x.message : String(x));
    } finally {
      setOcupado(false);
    }
  }

  async function criarExemplo() {
    try {
      const r = await api.post<{ caminho: string }>("/api/coletor/fontes/exemplo", {});
      estado.recarregar();
      await abrirArquivo(r.caminho);
    } catch (x) {
      setErro(x instanceof Error ? x.message : String(x));
    }
  }

  const abrirYaml = e ? (
    <Botao icone={<ArrowUpRight size={15} strokeWidth={1.75} aria-hidden />} onClick={() => abrirArquivo(e.caminho)}>
      Abrir fontes.yaml
    </Botao>
  ) : null;

  return (
    <Painel titulo="Coleta de vagas"
      descricao="O Quilha procura vagas novas nas páginas de carreira públicas (Greenhouse, Lever e Gupy) e filtra pelo título. Coletar não usa o seu LLM.">
      {e && !e.existe ? (
        <Vazio icone={<Briefcase size={20} strokeWidth={1.5} />} titulo="Nenhuma fonte de vagas ainda"
          texto="Comece pelo exemplo e troque pelas empresas que te interessam."
          acoes={<Botao tipo="prim" onClick={criarExemplo}>Criar a partir do exemplo</Botao>} />
      ) : e && (
        <>
          <div className="config-acoes">
            <Botao tipo="prim" icone={<RefreshCw size={15} strokeWidth={1.75} aria-hidden />} onClick={coletar}
              ocupado={ocupado} textoOcupado="Coletando…" disabled={!!e.erro || !e.fontes.length}>
              Coletar agora
            </Botao>
            {abrirYaml}
            {e.ultima && (
              <span className="meta">
                Última coleta {quando(e.ultima.quando, new Date()).toLowerCase()} · {plural(e.ultima.vagas_novas, "vaga nova", "vagas novas")}
              </span>
            )}
          </div>
          {(e.erro || erro) && <div className="erro-caixa" role="alert">{frase(e.erro ?? erro!)}</div>}
          {!e.erro && (
            <>
              <Divisor />
              <div className="config-grupo">
                <div className="rotulo-grupo">Fontes <span className="n">{e.fontes.length}</span></div>
                {e.fontes.length ? (
                  <ul className="config-lista">{e.fontes.map((f) => <LinhaFonte key={`${f.tipo}/${f.board}`} f={f} />)}</ul>
                ) : (
                  <p className="meta">O fontes.yaml não tem nenhuma fonte. Abra o arquivo e acrescente as empresas.</p>
                )}
              </div>
            </>
          )}
        </>
      )}
    </Painel>
  );
}
