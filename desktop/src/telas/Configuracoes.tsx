import { Activity, Briefcase, FolderOpen, Info, KeyRound, Mail, SunMoon, type LucideIcon } from "lucide-react";
import type { ComponentType } from "react";
import { api } from "../api";
import { useCarregar } from "../comum";
import { quando } from "../formato";
import type { EstadoConfig } from "../tipos";
import Cabecalho from "../ui/Cabecalho";
import Aparencia from "./config/Aparencia";
import Coleta from "./config/Coleta";
import Diagnostico from "./config/Diagnostico";
import Email from "./config/Email";
import LLM from "./config/LLM";
import { SECOES, type IdSecao, type PropsSecao, type Saude } from "./config/pecas";
import Sobre from "./config/Sobre";
import Vault from "./config/Vault";

const NOMES: Record<IdSecao, { nome: string; icone: LucideIcon }> = {
  vault: { nome: "Vault", icone: FolderOpen },
  llm: { nome: "LLM", icone: KeyRound },
  email: { nome: "E-mail", icone: Mail },
  coleta: { nome: "Coleta de vagas", icone: Briefcase },
  aparencia: { nome: "Aparência", icone: SunMoon },
  diagnostico: { nome: "Diagnóstico", icone: Activity },
  sobre: { nome: "Sobre", icone: Info },
};

/** Cada seção mora no seu arquivo em `telas/config/`. */
const CONTEUDO: Partial<Record<IdSecao, ComponentType<PropsSecao>>> = {
  vault: Vault, llm: LLM, email: Email, coleta: Coleta, aparencia: Aparencia, diagnostico: Diagnostico, sobre: Sobre,
};

type Props = {
  secao: IdSecao;
  aoTrocarSecao: (s: IdSecao) => void;
  config: EstadoConfig | null;
  recarregarConfig: () => void;
};

/** A linha de status: o problema mais grave (+N), clicável para a seção dele; sem problema, "Tudo funcionando". */
function Status({ saude, abrir }: { saude: Saude | null; abrir: (s: IdSecao) => void }) {
  if (!saude) return null;
  const [primeiro, ...resto] = saude.problemas;
  if (!primeiro)
    return <>Tudo funcionando{saude.indexado_em ? ` · índice do vault atualizado ${quando(saude.indexado_em, new Date()).toLowerCase()}` : ""}</>;
  return (
    <button className={`config-status ${primeiro.grave ? "grave" : "atencao"}`} onClick={() => abrir(primeiro.secao)}>
      {primeiro.texto}{resto.length ? ` · +${resto.length}` : ""}
    </button>
  );
}

export default function Configuracoes({ secao, aoTrocarSecao, config, recarregarConfig }: Props) {
  const saude = useCarregar(() => api.get<Saude>("/api/config/saude"));
  const Secao = CONTEUDO[secao];

  return (
    <>
      <Cabecalho titulo="Configurações" status={[<Status key="s" saude={saude.dados} abrir={aoTrocarSecao} />]} />
      <div className="config-corpo">
        <nav className="config-secoes" aria-label="Seções">
          {SECOES.map((id) => {
            const { nome, icone: Icone } = NOMES[id];
            return (
              <button key={id} className={`${id === "sobre" ? "separada " : ""}${id === secao ? "ativa" : ""}`}
                aria-current={id === secao ? "page" : undefined} onClick={() => aoTrocarSecao(id)}>
                <Icone size={16} strokeWidth={1.75} aria-hidden />
                {nome}
              </button>
            );
          })}
        </nav>
        <select className="campo config-secoes-estreita" aria-label="Seção" value={secao}
          onChange={(e) => aoTrocarSecao(e.target.value as IdSecao)}>
          {SECOES.map((id) => <option key={id} value={id}>{NOMES[id].nome}</option>)}
        </select>
        <section key={secao} className="config-painel troca" aria-label={NOMES[secao].nome}>
          {config && Secao && (
            <Secao config={config} saude={saude.dados} recarregarConfig={recarregarConfig}
              recarregarSaude={saude.recarregar} abrirSecao={aoTrocarSecao} />
          )}
        </section>
      </div>
    </>
  );
}
