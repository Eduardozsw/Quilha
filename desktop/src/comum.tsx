import { useCallback, useEffect, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Custo as TipoCusto } from "./tipos";

/** Carrega dados da API e expõe `recarregar`. Erro vira texto para a tela, nunca exceção solta. */
export function useCarregar<T>(buscar: () => Promise<T>, deps: unknown[] = []) {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      setDados(await buscar());
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setCarregando(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    recarregar();
  }, [recarregar]);

  return { dados, erro, carregando, recarregar, setDados };
}

/** Executa uma ação (gravar, gerar). Guarda o erro da recusa para mostrar como veio do domínio. */
export function useAcao() {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function executar<T>(acao: () => Promise<T>): Promise<T | undefined> {
    setOcupado(true);
    setErro(null);
    try {
      return await acao();
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setOcupado(false);
    }
  }

  return { ocupado, erro, executar, limparErro: () => setErro(null) };
}

/** Degraus de sustentação: preenchidos = nível; verdete se o vault sustenta, âmbar se não. */
export function Nivel({ nivel, sustentado }: { nivel: number | null; sustentado: boolean }) {
  const classe = nivel === null ? "n-sem" : sustentado ? "n-ok" : "n-falta";
  const rotulo = nivel === null ? "nível nunca avaliado" : `nível ${nivel}${sustentado ? "" : ", sem sustentação"}`;
  return (
    <span className={`nivel ${classe}`} role="img" aria-label={rotulo} title={rotulo}>
      {[1, 2, 3, 4].map((n) => (
        <i key={n} className={nivel !== null && n <= nivel ? "on" : ""} />
      ))}
    </span>
  );
}

/** Um `^block-id`: de onde vem a afirmação. O texto do fato aparece ao passar o mouse. */
export function Ref({ id, texto, orfa }: { id: string; texto?: string | null; orfa?: boolean }) {
  return (
    <span className={`ref${orfa ? " orfa" : ""}`} title={orfa ? "o fato sumiu do vault" : (texto ?? undefined)}>
      ^{id.replace(/^\^/, "")}
    </span>
  );
}

const SITUACAO: Record<string, [string, string]> = {
  ok: ["ok", "sustenta currículo"],
  "nunca avaliada": ["neutro", "nunca avaliada"],
  "sem evidencia": ["erro", "sem evidência"],
  "evidencia insuficiente": ["atencao", "evidência insuficiente"],
};

export function Situacao({ valor }: { valor: string }) {
  const [classe, texto] = SITUACAO[valor] ?? ["neutro", valor];
  return <span className={`selo ${classe}`}>{texto}</span>;
}

export function dolares(v: number | null | undefined, casas = 4) {
  if (v === null || v === undefined) return "custo desconhecido";
  return `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}`;
}

export function Custo({ custo }: { custo: TipoCusto | null | undefined }) {
  if (!custo) return null;
  if (!custo.llm_calls) return <span className="custo">sem chamada ao modelo</span>;
  return (
    <span className="custo">
      {custo.llm_calls} chamada(s), {custo.tokens} tokens, {dolares(custo.custo_usd)}
    </span>
  );
}

export function Erro({ texto }: { texto: string | null }) {
  return texto ? <div className="erro-caixa" role="alert">{texto}</div> : null;
}

export function Avisos({ avisos }: { avisos?: (string | null | undefined)[] }) {
  const lista = (avisos ?? []).filter(Boolean);
  if (!lista.length) return null;
  return (
    <div className="aviso">
      {lista.map((a, i) => (
        <p key={i}>{a}</p>
      ))}
    </div>
  );
}

/** Abrir pelo sistema (navegador, programa padrão, gerenciador de arquivos) pode falhar: permissão, app ausente,
 *  caminho que sumiu. A falha vira aviso na tela, nunca silêncio; devolve se deu certo. */
async function semSilencio(acao: () => Promise<unknown>): Promise<boolean> {
  try {
    await acao();
    return true;
  } catch (e) {
    const { avisar } = await import("./ui/Aviso");
    avisar(`Não deu para abrir: ${e instanceof Error ? e.message : String(e)}`);
    return false;
  }
}

/** Link para fora do app: no Tauri abre no navegador do sistema; no webview, `_blank` não abre nada. */
export function abrirExterno(url: string): Promise<boolean> {
  return semSilencio(async () => {
    if ("__TAURI_INTERNALS__" in window) {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
    } else {
      window.open(url, "_blank", "noopener");
    }
  });
}

type PdfGerado = { caminho: string; paginas: number; nome_sugerido: string };

/** "Baixar PDF". No app: janela "Salvar como…" do sistema, já na pasta Downloads com o nome sugerido; devolve
 *  onde gravou, ou null se a pessoa cancelou. No navegador (dev): download comum. */
export async function baixarPdf(versaoId: number): Promise<string | null> {
  const { api } = await import("./api");
  const gerado = await api.post<PdfGerado>(`/api/curriculos/${versaoId}/pdf`, {});
  if ("__TAURI_INTERNALS__" in window) {
    const [{ save }, { downloadDir, join }] = await Promise.all([
      import("@tauri-apps/plugin-dialog"), import("@tauri-apps/api/path"),
    ]);
    const destino = await save({
      defaultPath: await join(await downloadDir(), gerado.nome_sugerido),
      filters: [{ name: "PDF", extensions: ["pdf"] }],
    });
    if (!destino) return null;
    const salvo = await api.post<PdfGerado>(`/api/curriculos/${versaoId}/pdf`, { destino });
    return salvo.caminho;
  }
  const blob = await api.arquivo(`/api/curriculos/${versaoId}/pdf`);
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: gerado.nome_sugerido });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return gerado.nome_sugerido;
}

/** Abre um arquivo gerado (o PDF) no programa padrão do sistema. No navegador (dev) não há como: mostra o caminho. */
export function abrirArquivo(caminho: string): Promise<boolean> {
  return semSilencio(async () => {
    if ("__TAURI_INTERNALS__" in window) {
      const { openPath } = await import("@tauri-apps/plugin-opener");
      await openPath(caminho);
    } else {
      console.info("abrir arquivo:", caminho);
    }
  });
}

/** Mostra o arquivo selecionado na pasta, no gerenciador de arquivos do sistema. */
export function mostrarNaPasta(caminho: string): Promise<boolean> {
  return semSilencio(async () => {
    if ("__TAURI_INTERNALS__" in window) {
      const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
      await revealItemInDir(caminho);
    } else {
      console.info("mostrar na pasta:", caminho);
    }
  });
}

export function LinkExterno({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        abrirExterno(href);
      }}
    >
      {children}
    </a>
  );
}

/** Markdown com a procedência visível: `<!-- ^id @ nota -->` do currículo vira chip. */
export function Markdown({ texto }: { texto: string }) {
  const comChips = texto.replace(/<!--\s*\^([\w-]+)\s*@\s*([^>]*?)\s*-->/g, (_, id) => `\`^${id}\``);
  return (
    <div className="markdown">
      <ReactMarkdown
        components={{
          // link do modelo para `nota.md#block-id` é procedência, não navegação
          a: ({ href, children }) => {
            const bloco = href && !/^https?:/.test(href) ? href.match(/#\^?([\w-]+)$/) : null;
            if (bloco) return <Ref id={bloco[1]} />;
            return href ? <LinkExterno href={href}>{children}</LinkExterno> : <>{children}</>;
          },
          code: ({ children }) => {
            const t = String(children);
            return t.startsWith("^") ? <Ref id={t} /> : <code>{t}</code>;
          },
        }}
      >
        {comChips}
      </ReactMarkdown>
    </div>
  );
}

export function data(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

export function dataHora(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
