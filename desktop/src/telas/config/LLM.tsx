import { useId, useState } from "react";
import { api } from "../../api";
import type { EstadoConfig } from "../../tipos";
import Botao from "../../ui/Botao";
import Selo from "../../ui/Selo";
import UsaLLM from "../../ui/UsaLLM";
import { modeloLocal } from "../../ui/contexto";
import Jev from "./Jev";
import { Campo, CampoTexto, Divisor, frase, Linha, Painel, useGravar, type PropsSecao } from "./pecas";

/** Sugestões do combobox; qualquer modelo do LiteLLM continua valendo. */
const MODELOS = ["gpt-4o-mini", "gpt-4o", "claude-sonnet-4-5", "gemini/gemini-2.5-flash", "ollama/llama3.1"];

type Teste = { ok: true; ms: number; modelo: string } | { ok: false; mensagem: string };

const dolar = (v: number) => `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function SeloTeste({ teste }: { teste: Teste | null }) {
  if (!teste) return null;
  if (teste.ok) return <Selo tom="ok">Funcionando · respondeu em {(teste.ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s</Selo>;
  return <Selo tom="er">Não funcionou</Selo>;
}

/** Configurações → LLM: modelo (grava ao sair), chave só de escrita com "Salvar e testar", teste e limite de custo. */
export default function LLM(props: PropsSecao) {
  const { config, recarregarConfig, recarregarSaude } = props;
  const atualizar = () => { recarregarConfig(); recarregarSaude(); };
  const { gravar, salvo, erroDe } = useGravar(atualizar);
  const idChave = useId();
  const [trocando, setTrocando] = useState(!config.llm.chave_definida);
  const [chave, setChave] = useState("");
  const [teste, setTeste] = useState<Teste | null>(null);
  const [erroChave, setErroChave] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<"salvar" | "testar" | null>(null);

  async function testar() {
    setOcupado("testar");
    try {
      setTeste(await api.post<Teste>("/api/config/llm/testar"));
      recarregarSaude();
    } catch (e) {
      // a rota devolve a falha do provedor como resposta; o que chega aqui é falha de rede ou do próprio Quilha
      setTeste({ ok: false, mensagem: e instanceof Error ? e.message : String(e) });
    } finally {
      setOcupado(null);
    }
  }

  async function salvarETestar() {
    setOcupado("salvar");
    setErroChave(null);
    try {
      const r = await api.post<{ estado: EstadoConfig; teste: Teste }>("/api/config/llm/salvar-e-testar", { llm_api_key: chave });
      setTeste(r.teste);
      if (r.teste.ok) {
        setTrocando(false);
        setChave("");
      } else {
        setErroChave(r.teste.mensagem);
      }
      atualizar();
    } catch (e) {
      setErroChave(e instanceof Error ? e.message : String(e));
    } finally {
      setOcupado(null);
    }
  }

  return (
    <Painel titulo="LLM"
      descricao="O modelo que analisa vagas, redige currículos e faz a triagem dos e-mails (ou o Jev, se você ligar abaixo). As chaves ficam só neste computador.">
      <CampoTexto rotulo="Modelo" valor={config.llm.modelo ?? ""} lista={MODELOS} salvo={salvo === "modelo"} erro={erroDe("modelo")}
        ajuda="Escolha um da lista ou escreva qualquer modelo do LiteLLM. Para rodar local: ollama/llama3.1."
        aoSalvar={async (v) => !!v && !!(await gravar("modelo", { llm_model: v }))} />

      {modeloLocal(config.llm.modelo) && !config.llm.chave_definida ? (
        <>
          <Linha titulo="Chave da API" descricao="Modelo local: não precisa de chave e não tem custo" />
          <div className="config-acoes">
            <Botao onClick={testar} ocupado={ocupado === "testar"} textoOcupado="Testando…">Testar modelo</Botao>
            <SeloTeste teste={teste} />
          </div>
          {teste && !teste.ok && <p className="ajuda-erro" role="alert">{frase(teste.mensagem)}</p>}
        </>
      ) : trocando ? (
        <>
          <Campo id={idChave} rotulo="Chave da API" erro={erroChave}>
            <input id={idChave} className={`campo${erroChave ? " com-erro" : ""}`} type="password" autoComplete="off"
              spellCheck={false} value={chave} onChange={(e) => setChave(e.target.value)} placeholder="Cole a chave do seu provedor"
              aria-invalid={erroChave ? true : undefined} />
          </Campo>
          <div className="config-acoes">
            <Botao tipo="prim" onClick={salvarETestar} ocupado={ocupado === "salvar"} textoOcupado="Testando…"
              disabled={!chave.trim() || ocupado !== null}>
              Salvar e testar
            </Botao>
            {config.llm.chave_definida && (
              <Botao tipo="fant" onClick={() => { setTrocando(false); setChave(""); setErroChave(null); }}>Cancelar</Botao>
            )}
            <UsaLLM detalhe="chamada mínima" />
          </div>
        </>
      ) : (
        <>
          <Linha titulo="Chave da API" descricao="Definida · guardada só neste computador">
            <Botao onClick={() => setTrocando(true)}>Trocar</Botao>
          </Linha>
          <div className="config-acoes">
            <Botao onClick={testar} ocupado={ocupado === "testar"} textoOcupado="Testando…">Testar chave</Botao>
            <UsaLLM detalhe="chamada mínima" />
            <SeloTeste teste={teste} />
          </div>
          {teste && !teste.ok && <p className="ajuda-erro" role="alert">{frase(teste.mensagem)}</p>}
        </>
      )}

      <Divisor />
      <div className="config-linha">
        <div className="texto">
          <strong>Limite por execução</strong>
          <span>Uma execução que passaria desse valor para antes de gastar. Protege contra uma vaga gigante ou um laço.</span>
        </div>
        <div className="direita limite">
          <CampoTexto rotulo="Limite em dólares" valor={String(config.llm.limite_usd)} largura={110}
            mostrar={(v) => dolar(Number(v))} salvo={salvo === "limite"} erro={erroDe("limite")}
            aoSalvar={async (v) => !!(await gravar("limite", { hermes_max_cost_usd: v.replace(/^US\$\s*/, "") }))} />
        </div>
      </div>

      <Divisor />
      <Jev {...props} />
    </Painel>
  );
}
