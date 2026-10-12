import { useId, useState } from "react";
import { api } from "../../api";
import type { EstadoConfig } from "../../tipos";
import Botao from "../../ui/Botao";
import Selo from "../../ui/Selo";
import { Campo, frase, Interruptor, Linha, Salvo, useGravar, type PropsSecao } from "./pecas";

type Teste = { ok: true; ms: number } | { ok: false; mensagem: string };

function SeloTeste({ teste }: { teste: Teste | null }) {
  if (!teste) return null;
  if (teste.ok) return <Selo tom="ok">Funcionando · respondeu em {(teste.ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s</Selo>;
  return <Selo tom="er">Não funcionou</Selo>;
}

/** Configurações → LLM → "Triagem dos e-mails": o Jev no lugar do LLM do usuário. A chave é testada antes de ligar. */
export default function Jev({ config, recarregarConfig, recarregarSaude }: PropsSecao) {
  const atualizar = () => { recarregarConfig(); recarregarSaude(); };
  const { gravar, salvo } = useGravar(atualizar);
  const idChave = useId();
  const ligado = config.triagem.classificador === "jev";
  const temChave = config.triagem.jev_chave_definida;
  const [aberto, setAberto] = useState(false);
  const [chave, setChave] = useState("");
  const [teste, setTeste] = useState<Teste | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<"salvar" | "testar" | null>(null);

  function fecharCampo() {
    setAberto(false);
    setChave("");
    setErro(null);
  }

  async function ligar(sim: boolean) {
    setErro(null);
    setTeste(null);
    if (!sim) {
      fecharCampo();
      await gravar("jev", { email_classificador: "llm" });
    } else if (temChave) {
      await gravar("jev", { email_classificador: "jev" });
    } else {
      setAberto(true);
    }
  }

  async function salvarETestar() {
    setOcupado("salvar");
    setErro(null);
    try {
      const r = await api.post<{ estado: EstadoConfig; teste: Teste }>("/api/config/jev/salvar-e-testar", { typesafe_api_key: chave });
      setTeste(r.teste);
      if (r.teste.ok) fecharCampo();
      else setErro(r.teste.mensagem);
      atualizar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setOcupado(null);
    }
  }

  async function testar() {
    setOcupado("testar");
    try {
      setTeste(await api.post<Teste>("/api/config/jev/testar"));
    } catch (e) {
      setTeste({ ok: false, mensagem: e instanceof Error ? e.message : String(e) });
    } finally {
      setOcupado(null);
    }
  }

  return (
    <>
      <div className="config-linha">
        <div className="texto">
          <strong>Triagem dos e-mails pelo Jev</strong>
          <span>
            Ganha: não gasta o seu LLM na triagem. Perde: os e-mails passam pelo serviço deles, que é pago, e no nosso
            teste acertou 92 de 100 (gpt-4o-mini acertou 98).
          </span>
        </div>
        <div className="direita">
          <Salvo visivel={salvo === "jev"} />
          {/* aceso enquanto a chave é digitada; recusada, apaga: o Jev não ligou */}
          <Interruptor ligado={ligado || (aberto && !erro)} aoMudar={ligar} rotulo="Triagem pelo Jev" />
        </div>
      </div>
      {aberto ? (
        <>
          <Campo id={idChave} rotulo="Chave do Jev" erro={erro}>
            <input id={idChave} className={`campo${erro ? " com-erro" : ""}`} type="password" autoComplete="off"
              spellCheck={false} value={chave} onChange={(e) => setChave(e.target.value)} placeholder="tsk_…"
              aria-invalid={erro ? true : undefined} />
          </Campo>
          <div className="config-acoes">
            <Botao tipo="prim" onClick={salvarETestar} ocupado={ocupado === "salvar"} textoOcupado="Testando…"
              disabled={!chave.trim() || ocupado !== null}>
              Salvar e testar
            </Botao>
            <Botao tipo="fant" onClick={fecharCampo}>Cancelar</Botao>
            <span className="meta">chamada mínima ao Jev</span>
          </div>
        </>
      ) : ligado && temChave ? (
        <>
          <Linha titulo="Chave do Jev" descricao="Definida · guardada só neste computador">
            <Botao onClick={() => { setAberto(true); setTeste(null); }}>Trocar</Botao>
          </Linha>
          <div className="config-acoes">
            <Botao onClick={testar} ocupado={ocupado === "testar"} textoOcupado="Testando…">Testar chave do Jev</Botao>
            <SeloTeste teste={teste} />
          </div>
          {teste && !teste.ok && <p className="ajuda-erro" role="alert">{frase(teste.mensagem)}</p>}
        </>
      ) : null}
    </>
  );
}
