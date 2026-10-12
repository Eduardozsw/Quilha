import { ArrowUpRight, Check, ChevronDown, ChevronUp } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { api } from "../../api";
import { abrirExterno } from "../../comum";
import { useApp } from "../../ui/contexto";
import Botao from "../../ui/Botao";
import Selo from "../../ui/Selo";
import { Campo, Divisor, frase, Linha, Painel, REPO, Salvo, useGravar, type PropsSecao } from "./pecas";

export const DIAS = [7, 14, 30, 60, 90];
const SENHAS_DE_APP = "https://myaccount.google.com/apppasswords";

type Teste = { ok: boolean; mensagem: string; origem: string };

function Passo({ n, feito, titulo, children }: { n: number; feito: boolean; titulo: string; children: ReactNode }) {
  return (
    <div className="config-passo">
      <span className={`marca${feito ? " feito" : ""}`} aria-label={feito ? `Passo ${n}, feito` : `Passo ${n}`}>
        {feito ? <Check size={13} strokeWidth={2.5} aria-hidden /> : n}
      </span>
      <div className="conteudo">
        <strong>{titulo}</strong>
        {children}
      </div>
    </div>
  );
}

function SeloTeste({ teste }: { teste: Teste | null }) {
  if (!teste) return null;
  return <Selo tom={teste.ok ? "ok" : "er"}>{frase(teste.mensagem)}</Selo>;
}

/** Configurações → E-mail: guia IMAP em 3 passos (ou o OAuth próprio, se já está em uso), janela de busca e Avançado. */
export default function Email({ config, recarregarConfig, recarregarSaude }: PropsSecao) {
  const e = config.email;
  const { abrir } = useApp();
  const atualizar = () => { recarregarConfig(); recarregarSaude(); };
  const { gravar, salvo, erroDe } = useGravar(atualizar);
  const idUsuario = useId();
  const idSenha = useId();
  const idDias = useId();
  const oauthAtivo = e.origem === "gmail" && e.gmail_credenciais;
  const [guiaImap, setGuiaImap] = useState(!oauthAtivo);
  const [usuario, setUsuario] = useState(e.imap_usuario);
  const [senha, setSenha] = useState("");
  const [teste, setTeste] = useState<Teste | null>(null);
  const [ocupado, setOcupado] = useState<"salvar" | "testar" | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [avancado, setAvancado] = useState(false);
  const jevLigado = config.triagem.classificador === "jev";

  async function testar() {
    setOcupado("testar");
    try {
      setTeste(await api.post<Teste>("/api/emails/testar"));
      recarregarSaude();
    } catch (x) {
      setTeste({ ok: false, mensagem: x instanceof Error ? x.message : String(x), origem: e.origem });
    } finally {
      setOcupado(null);
    }
  }

  async function salvarETestar() {
    setOcupado("salvar");
    setErro(null);
    try {
      await api.put("/api/config", { email_origem: "imap", imap_usuario: usuario.trim(), imap_senha: senha.replace(/\s+/g, "") });
      setSenha("");
      atualizar();
    } catch (x) {
      setErro(x instanceof Error ? x.message : String(x));
      setOcupado(null);
      return;
    }
    await testar();
  }

  const feito1 = e.imap_senha_definida;
  const feito2 = !!e.imap_usuario && e.imap_senha_definida;
  const feito3 = !!teste?.ok;
  const usandoImap = e.origem === "imap";

  return (
    <Painel titulo="E-mail"
      descricao={`O Quilha lê só os e-mails de candidatura, por IMAP, com uma senha de app. Na triagem, o texto de cada e-mail vai para ${jevLigado ? "o Jev" : "o seu LLM"}.`}>
      {!guiaImap ? (
        <>
          <Linha titulo="Conectado pelo OAuth próprio" descricao={e.gmail_pasta} />
          <div className="config-acoes">
            <Botao onClick={testar} ocupado={ocupado === "testar"} textoOcupado="Testando…">
              {teste ? "Testar de novo" : "Testar conexão"}
            </Botao>
            <SeloTeste teste={teste} />
            <Botao tipo="fant" onClick={() => { setGuiaImap(true); setTeste(null); }}>Usar senha de app em vez disso</Botao>
          </div>
        </>
      ) : (
        <>
          <Passo n={1} feito={feito1} titulo="Crie uma senha de app na sua conta Google">
            <button className="config-link" onClick={() => abrirExterno(SENHAS_DE_APP)}>
              Abrir a página de senhas de app <ArrowUpRight size={14} strokeWidth={1.75} aria-hidden />
            </button>
          </Passo>
          <Passo n={2} feito={feito2 && usandoImap} titulo="Informe o endereço e a senha de app">
            <div className="campos-2">
              <Campo id={idUsuario} rotulo="Endereço" salvo={salvo === "usuario"}>
                <input id={idUsuario} className="campo" type="email" autoComplete="off" spellCheck={false}
                  value={usuario} onChange={(x) => setUsuario(x.target.value)} placeholder="voce@gmail.com"
                  onBlur={() => { if (usuario.trim() !== e.imap_usuario && e.imap_senha_definida) gravar("usuario", { imap_usuario: usuario.trim() }); }} />
              </Campo>
              <Campo id={idSenha} rotulo="Senha de app">
                <input id={idSenha} className="campo" type="password" autoComplete="off" spellCheck={false}
                  value={senha} onChange={(x) => setSenha(x.target.value)}
                  placeholder={e.imap_senha_definida ? "•••• •••• •••• ••••" : "16 letras, com ou sem espaços"} />
              </Campo>
            </div>
            {(senha.trim() || !e.imap_senha_definida || ocupado === "salvar") && (
              <div className="config-acoes">
                <Botao onClick={salvarETestar} ocupado={ocupado === "salvar"} textoOcupado="Salvando…"
                  disabled={!usuario.trim() || !senha.trim() || ocupado !== null}>
                  Salvar e testar
                </Botao>
              </div>
            )}
            {erro && <p className="ajuda-erro" role="alert">{frase(erro)}</p>}
          </Passo>
          <Passo n={3} feito={feito3} titulo="Teste a conexão">
            <div className="config-acoes">
              <Botao onClick={testar} ocupado={ocupado === "testar"} textoOcupado="Testando…" disabled={!feito2 || ocupado !== null}>
                {teste ? "Testar de novo" : "Testar conexão"}
              </Botao>
              <SeloTeste teste={teste} />
            </div>
          </Passo>
        </>
      )}

      <Divisor />
      <div className="config-linha">
        <div className="texto">
          <strong><label htmlFor={idDias}>Buscar e-mails dos últimos</label></strong>
          <span>
            A triagem usa {jevLigado ? "o Jev" : "o seu LLM"} em cada e-mail novo.{" "}
            <button className="config-link" onClick={() => abrir("configuracoes", "llm")}>Mudar em LLM</button>
          </span>
        </div>
        <div className="direita">
          <Salvo visivel={salvo === "dias"} />
          <select id={idDias} className="campo seletor" value={e.dias}
            onChange={(x) => gravar("dias", { email_dias: x.target.value })}>
            {(DIAS.includes(e.dias) ? DIAS : [...DIAS, e.dias].sort((a, b) => a - b)).map((d) => (
              <option key={d} value={d}>{d} dias</option>
            ))}
          </select>
        </div>
      </div>
      {erroDe("dias") && <p className="ajuda-erro" role="alert">{frase(erroDe("dias")!)}</p>}

      <button className="config-avancado" aria-expanded={avancado} onClick={() => setAvancado((a) => !a)}>
        {avancado ? "Avançado" : "Avançado: conta corporativa com OAuth próprio"}
        {avancado ? <ChevronUp size={14} strokeWidth={1.75} aria-hidden /> : <ChevronDown size={14} strokeWidth={1.75} aria-hidden />}
      </button>
      {avancado && (
        <div className="config-bloco troca">
          <Linha titulo="Conta corporativa com OAuth próprio"
            descricao="Para contas que bloqueiam senha de app. Pede um projeto seu no Google Cloud e o arquivo credentials.json. Com ele, o Quilha também cria os rótulos Vagas/… na caixa.">
            <Botao icone={<ArrowUpRight size={15} strokeWidth={1.75} aria-hidden />} onClick={() => abrirExterno(`${REPO}#e-mail-e-candidaturas`)}>
              Ver o guia
            </Botao>
          </Linha>
        </div>
      )}
    </Painel>
  );
}
