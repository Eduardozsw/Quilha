// Cliente da API local (`hermes serve`). Porta e token vêm do Tauri, que sobe o processo;
// no navegador (desenvolvimento), de VITE_HERMES_PORTA e VITE_HERMES_TOKEN.

type Conexao = { base: string; token: string; log?: string };

let conexao: Promise<Conexao> | null = null;
// a conexão já resolvida, para quem precisa dela sem esperar (o `pagehide` não espera promessa)
let conexaoPronta: Conexao | null = null;

async function descobrir(): Promise<Conexao> {
  if ("__TAURI_INTERNALS__" in window) {
    const { invoke } = await import("@tauri-apps/api/core");
    const info = await invoke<{ porta: number; token: string; log: string }>("api_info");
    return { base: `http://127.0.0.1:${info.porta}`, token: info.token, log: info.log };
  }
  const porta = import.meta.env.VITE_HERMES_PORTA ?? "8765";
  return { base: `http://127.0.0.1:${porta}`, token: import.meta.env.VITE_HERMES_TOKEN ?? "" };
}

function obterConexao(): Promise<Conexao> {
  conexao ??= descobrir().then((c) => (conexaoPronta = c));
  return conexao;
}

/** A Início marca a visita ao sair (troca de tela) e ao fechar o app; nunca ao abrir (decisão do PM).
 *  `quando` é o `agora` do resumo que a tela mostrou: o que chegou depois dele continua como novidade. */
export async function marcarVisita(quando: string): Promise<void> {
  const { base, token } = await obterConexao();
  await fetch(`${base}/api/inicio/visita`, {
    method: "POST", headers: { "X-Hermes-Token": token, "Content-Type": "application/json" }, body: JSON.stringify({ quando }),
  }).catch(() => undefined);
}

/** Versão síncrona para o `pagehide` (navegador): `keepalive` deixa o pedido terminar com a janela fechando. */
export function marcarVisitaAoFechar(quando: string): void {
  if (!conexaoPronta) return;
  fetch(`${conexaoPronta.base}/api/inicio/visita`, {
    method: "POST", keepalive: true, body: JSON.stringify({ quando }),
    headers: { "X-Hermes-Token": conexaoPronta.token, "Content-Type": "application/json" },
  }).catch(() => undefined);
}

/** Pasta dos logs do app (onde o Tauri grava o `backend.log`); no navegador (dev) não há: null. */
export async function pastaDeLogs(): Promise<string | null> {
  const { log } = await obterConexao();
  if (!log) return null;
  return log.replace(/[\\/][^\\/]*$/, "") || null;
}

export class ErroApi extends Error {
  /** `codigo: "llm"` = o provedor do LLM recusou ou não respondeu; a saída é configurar o LLM. */
  constructor(message: string, readonly status: number, readonly codigo?: string) {
    super(message);
  }
}

export const eErroDeLLM = (e: unknown) => e instanceof ErroApi && e.codigo === "llm";

async function pedir<T>(metodo: string, caminho: string, corpo?: unknown): Promise<T> {
  const { base, token } = await obterConexao();
  const r = await fetch(base + caminho, {
    method: metodo,
    headers: { "X-Hermes-Token": token, ...(corpo === undefined ? {} : { "Content-Type": "application/json" }) },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) throw new ErroApi(dados.erro ?? `a API respondeu ${r.status}`, r.status, dados.codigo);
  return dados as T;
}

/** Baixa um arquivo da API (com o token, que um link simples não leva). */
async function arquivo(caminho: string): Promise<Blob> {
  const { base, token } = await obterConexao();
  const r = await fetch(base + caminho, { headers: { "X-Hermes-Token": token } });
  if (!r.ok) {
    const dados = await r.json().catch(() => ({}));
    throw new ErroApi(dados.erro ?? `a API respondeu ${r.status}`, r.status, dados.codigo);
  }
  return r.blob();
}

export const api = {
  arquivo,
  get: <T>(caminho: string) => pedir<T>("GET", caminho),
  post: <T>(caminho: string, corpo: unknown = {}) => pedir<T>("POST", caminho, corpo),
  put: <T>(caminho: string, corpo: unknown) => pedir<T>("PUT", caminho, corpo),
  del: <T>(caminho: string) => pedir<T>("DELETE", caminho),
};

/** Espera o processo do Hermes responder. O Tauri acabou de subir o `hermes serve`. */
export async function esperarHermes(tentativas = 60): Promise<void> {
  const { base, log } = await obterConexao();
  for (let i = 0; i < tentativas; i++) {
    try {
      const r = await fetch(`${base}/api/saude`);
      if (r.ok) return;
    } catch {
      /* ainda subindo */
    }
    await new Promise((ok) => setTimeout(ok, 500));
  }
  throw new Error(`o Quilha não respondeu em 30 s. Veja o log em ${log ?? "data/hermes-serve.log"}.`);
}

/** Um turno de chat em SSE. Chama `aoEvento` para cada evento até `fim` ou `erro`.
 *  `sinal` aborta a leitura (o "Parar"); quem aborta também avisa o backend por `/parar`. */
export async function turno(
  sessao: number,
  texto: string,
  aoEvento: (tipo: string, dados: any) => void,
  sinal?: AbortSignal,
): Promise<void> {
  const { base, token } = await obterConexao();
  const r = await fetch(`${base}/api/chat/sessoes/${sessao}/turnos`, {
    method: "POST",
    headers: { "X-Hermes-Token": token, "Content-Type": "application/json" },
    body: JSON.stringify({ texto }),
    signal: sinal,
  });
  if (!r.ok || !r.body) {
    const dados = await r.json().catch(() => ({}));
    throw new ErroApi(dados.erro ?? `a API respondeu ${r.status}`, r.status);
  }
  const leitor = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let resto = "";
  for (;;) {
    const { value, done } = await leitor.read();
    if (done) return;
    resto += value;
    let fim: number;
    while ((fim = resto.indexOf("\n\n")) >= 0) {
      const bloco = resto.slice(0, fim);
      resto = resto.slice(fim + 2);
      let tipo = "message";
      let dados = "";
      for (const linha of bloco.split("\n")) {
        if (linha.startsWith("event: ")) tipo = linha.slice(7);
        else if (linha.startsWith("data: ")) dados += linha.slice(6);
      }
      aoEvento(tipo, dados ? JSON.parse(dados) : {});
    }
  }
}
