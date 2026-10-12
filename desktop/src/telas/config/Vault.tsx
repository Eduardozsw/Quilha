import { ChevronRight, FolderOpen, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import { useCarregar } from "../../comum";
import { plural, quando } from "../../formato";
import Botao from "../../ui/Botao";
import ProgressoIndexacao from "../../ui/ProgressoIndexacao";
import Selo from "../../ui/Selo";
import { Campo, Divisor, Linha, Painel, type PropsSecao } from "./pecas";

const NO_APP = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function escolherPasta(atual: string): Promise<string | null> {
  if (!NO_APP) return window.prompt("Pasta do vault", atual)?.trim() || null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const escolhida = await open({ directory: true, multiple: false, title: "Pasta do seu vault do Obsidian", defaultPath: atual });
  return typeof escolhida === "string" ? escolhida : null;
}

/** Configurações → Vault: a pasta, o índice com "Reindexar agora" e o resumo dos avisos. */
export default function Vault({ config, saude, recarregarConfig, recarregarSaude, abrirSecao }: PropsSecao) {
  const resumo = useCarregar(() => api.get<{ fatos: { fatos: number }[] }>("/api/operacao/resumo"));
  const [indexando, setIndexando] = useState<{ anterior: string | null } | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const fatos = resumo.dados?.fatos.reduce((s, f) => s + f.fatos, 0) ?? 0;
  const avisos = saude?.problemas.find((p) => p.tipo === "vault_avisos");

  async function indexar(anterior: string | null) {
    setErro(null);
    try {
      await api.post("/api/operacao/index/iniciar");
      setIndexando({ anterior });
    } catch (e) {
      // a pasta já foi trocada: sem índice novo, volta a anterior (o índice antigo continua valendo)
      if (anterior) {
        await api.put("/api/config", { vault_path: anterior }).catch(() => undefined);
        recarregarConfig();
      }
      setErro(e instanceof Error ? e.message : String(e));
    }
  }

  async function trocar() {
    const destino = await escolherPasta(config.vault.caminho);
    if (!destino || destino === config.vault.caminho) return;
    try {
      await api.put("/api/config", { vault_path: destino });
    } catch (e) {
      return setErro(e instanceof Error ? e.message : String(e));
    }
    await indexar(config.vault.caminho);
  }

  function terminou() {
    setIndexando(null);
    recarregarConfig();
    recarregarSaude();
    resumo.recarregar();
  }

  /** cancelar a troca devolve a pasta anterior: o índice antigo continua valendo (a troca é atômica) */
  async function cancelou() {
    if (indexando?.anterior) await api.put("/api/config", { vault_path: indexando.anterior }).catch(() => undefined);
    terminou();
  }

  return (
    <Painel titulo="Vault"
      descricao="A pasta de notas de onde saem os fatos do seu currículo. O Quilha lê as notas de Carreira/ e só grava no vault quando você confirma.">
      <Campo id="vault-pasta" rotulo="Pasta do vault" ajuda="Trocar a pasta reindexa o vault sozinho." erro={erro}>
        <div className="config-acoes linha-campo">
          <input id="vault-pasta" className="campo" value={config.vault.caminho} readOnly />
          <Botao icone={<FolderOpen size={15} strokeWidth={1.75} aria-hidden />} onClick={trocar} disabled={!!indexando}>
            Trocar pasta…
          </Botao>
        </div>
      </Campo>
      <Divisor />
      {indexando ? (
        <div className="config-grupo">
          <Linha titulo="Lendo o vault" descricao="Indexando as notas de Carreira/ para achar os seus fatos." />
          <ProgressoIndexacao aoTerminar={terminou} aoCancelar={cancelou} aoErro={(m) => { setErro(m); cancelou(); }} />
        </div>
      ) : (
        <Linha titulo="Índice"
          descricao={`${plural(config.vault.notas, "nota", "notas")} · ${plural(fatos, "fato", "fatos")}${saude?.indexado_em ? ` · atualizado ${quando(saude.indexado_em, new Date()).toLowerCase()}` : " · ainda não indexado"}`}>
          <Botao icone={<RefreshCw size={15} strokeWidth={1.75} aria-hidden />} onClick={() => indexar(null)}>
            Reindexar agora
          </Botao>
        </Linha>
      )}
      {avisos && (
        <div className="config-acoes">
          <Selo tom="at">{avisos.texto}</Selo>
          <button className="config-link" onClick={() => abrirSecao("diagnostico")}>
            Ver no Diagnóstico <ChevronRight size={14} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      )}
    </Painel>
  );
}
