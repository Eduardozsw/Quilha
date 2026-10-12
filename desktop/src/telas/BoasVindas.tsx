import { useState } from "react";
import { FolderOpen, Plus, Sparkles } from "lucide-react";
import { api } from "../api";
import { Logo } from "../marca";
import type { EstadoConfig } from "../tipos";
import Botao from "../ui/Botao";
import ProgressoIndexacao from "../ui/ProgressoIndexacao";

const NO_APP = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Primeira abertura: escolher o vault (ou criar um de exemplo), indexar com progresso e "Cancelar". */
export default function BoasVindas({ config, aoConcluir, aoRecarregar }: {
  config: EstadoConfig; aoConcluir: () => void; aoRecarregar: () => Promise<void> | void;
}) {
  const [opcao, setOpcao] = useState<"pasta" | "exemplo">("pasta");
  const [caminho, setCaminho] = useState("");
  const [fase, setFase] = useState<"escolha" | "indexando">("escolha");
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  async function escolherPasta(): Promise<string | null> {
    if (!NO_APP) return caminho.trim() || null;
    const { open } = await import("@tauri-apps/plugin-dialog");
    const escolhida = await open({ directory: true, multiple: false, title: "Pasta do seu vault do Obsidian" });
    return typeof escolhida === "string" ? escolhida : null;
  }

  async function continuar() {
    setErro(null);
    setOcupado(true);
    try {
      let destino: string | null;
      if (opcao === "exemplo") {
        destino = config.vault.sugestao;
        await api.post("/api/vault/exemplo", { caminho: destino });
      } else {
        destino = await escolherPasta();
        if (!destino) return; // cancelou o seletor
      }
      await api.put("/api/config", { vault_path: destino });
      await api.post("/api/operacao/index/iniciar");
      setFase("indexando");
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setOcupado(false);
    }
  }

  async function voltarAEscolha(mensagem?: string) {
    if (mensagem) setErro(mensagem);
    setFase("escolha");
    await api.put("/api/config", { vault_path: "" }).catch(() => undefined); // volta a pedir o vault
    // a pasta sugerida para o exemplo pode ter acabado de nascer: a sugestão nova é outra pasta livre
    await aoRecarregar();
  }

  if (fase === "indexando") {
    return (
      <div className="boas-vindas">
        <div className="card-bv">
          <Logo tamanho={44} />
          <h1>Lendo o seu vault</h1>
          <p className="meta-bv">O Quilha está indexando as notas de Carreira/ para achar os seus fatos.</p>
          <ProgressoIndexacao aoTerminar={aoConcluir} aoCancelar={() => voltarAEscolha()} aoErro={voltarAEscolha} />
        </div>
      </div>
    );
  }

  return (
    <div className="boas-vindas">
      <div className="card-bv">
        <Logo tamanho={44} />
        <h1>Boas-vindas ao Quilha</h1>
        <p className="meta-bv">Seu vault do Obsidian vira currículos sob medida e o acompanhamento das suas candidaturas. Tudo fica na sua máquina.</p>
        <div className="opcoes-bv" role="radiogroup" aria-label="Como começar">
          <button role="radio" aria-checked={opcao === "pasta"} className="opcao-bv" onClick={() => setOpcao("pasta")}>
            <span className="ic-bv"><FolderOpen size={17} strokeWidth={1.5} aria-hidden /></span>
            <span><b>Escolher a pasta do meu vault</b><small>Use as notas que você já tem no Obsidian</small></span>
          </button>
          {opcao === "pasta" && !NO_APP && (
            <input className="campo" value={caminho} onChange={(e) => setCaminho(e.target.value)}
              placeholder="/caminho/para/o/vault" aria-label="Caminho do vault" />
          )}
          <button role="radio" aria-checked={opcao === "exemplo"} className="opcao-bv" onClick={() => setOpcao("exemplo")}>
            <span className="ic-bv"><Plus size={17} strokeWidth={1.5} aria-hidden /></span>
            <span><b>Criar um vault de exemplo</b><small>Para experimentar antes, com notas fictícias (em ~/{config.vault.sugestao.split(/[\\/]/).pop()})</small></span>
          </button>
        </div>
        {erro && (
          <div className="erro-folha" role="alert">
            {erro}
            {opcao === "pasta" && NO_APP && <Botao onClick={continuar} disabled={ocupado}>Escolher outra pasta</Botao>}
          </div>
        )}
        <div className="rodape-bv">
          <span className="llm"><Sparkles size={13} strokeWidth={1.5} aria-hidden />O LLM é opcional: dá pra configurar depois.</span>
          <Botao tipo="prim" onClick={continuar} ocupado={ocupado} textoOcupado="Preparando…"
            disabled={opcao === "pasta" && !NO_APP && !caminho.trim()}>
            Continuar
          </Botao>
        </div>
      </div>
    </div>
  );
}
