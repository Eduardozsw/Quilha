import type { CartaoConversa, Mensagem, ResultadoConfirmacao, RotuloFerramenta } from "../../tipos";

/** Uma chamada na linha de ferramenta. `cancelada` = a confirmação foi recusada: a linha da confirmação já conta. */
export type Chamada = { nome: string; rotulo: RotuloFerramenta | null; estado: "rodando" | "feito" | "falhou" | "cancelada" };

export type Campo = { rotulo: string; valor: string };
export type Linhas = Record<ResultadoConfirmacao, string>;

export type TipoErro = "llm" | "chave" | "teto" | "outro";

/** O que aparece no fio, na ordem: pergunta, linha de ferramenta, texto, confirmação, cartões, custo, erro. */
export type Item =
  | { tipo: "voce"; chave: string; texto: string; voa?: boolean }
  | { tipo: "ferramentas"; chave: string; chamadas: Chamada[] }
  | { tipo: "texto"; chave: string; trechos: string[]; final: boolean }
  | { tipo: "confirmar"; chave: string; id: string; titulo: string; campos: Campo[]; linhas: Linhas | null;
      ferramenta: string; resultado?: ResultadoConfirmacao; linha?: string; enviando?: boolean }
  | { tipo: "resolvida"; chave: string; resultado: ResultadoConfirmacao; linha: string }
  | { tipo: "cartoes"; chave: string; cartoes: CartaoConversa[] }
  | { tipo: "rodape"; chave: string; custo: number | null; parado: boolean }
  | { tipo: "erro"; chave: string; erro: TipoErro; mensagem: string; pergunta: string; gasto?: number | null; teto?: number | null };

let seq = 0;
export const novaChave = (prefixo: string) => `${prefixo}-${++seq}`;

/** "US$ 0,003". Custo desconhecido (modelo local, provedor sem `usage`) ou zero não mostra nada. */
export function formatarCusto(usd: number | null | undefined): string | null {
  if (usd === null || usd === undefined || !(usd > 0)) return null;
  if (usd < 0.001) return "< US$ 0,001";
  const casas = usd < 1 ? 3 : 2;
  return `US$ ${usd.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}`;
}

function juntar(partes: string[]): string {
  if (partes.length <= 1) return partes[0] ?? "";
  return `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}`;
}

const minuscula = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** Frases da linha de ferramenta: chamadas seguidas numa linha só ("Consultou as vagas e as candidaturas").
 *  Rodando mostra o que está rodando agora; falha vira uma segunda linha, em cor de erro. */
export function frasesFerramentas(chamadas: Chamada[]): { rodando: string | null; feito: string | null; falhou: string | null } {
  const visiveis = chamadas.filter((c) => c.estado !== "cancelada");
  const rodando = visiveis.filter((c) => c.estado === "rodando").pop();
  const rot = (c: Chamada): RotuloFerramenta =>
    c.rotulo ?? { rodando: `Usando \`${c.nome}\`…`, feito: `Usou \`${c.nome}\``, falhou: `Não consegui usar \`${c.nome}\``,
                  verbo: "Usou", objeto: `\`${c.nome}\`` };

  // feitas: agrupa por verbo na ordem em que apareceram, sem repetir o mesmo objeto
  const grupos: { verbo: string; objetos: string[] }[] = [];
  for (const c of visiveis.filter((x) => x.estado === "feito")) {
    const r = rot(c);
    const g = grupos.find((x) => x.verbo === r.verbo);
    if (!g) grupos.push({ verbo: r.verbo, objetos: [r.objeto] });
    else if (!g.objetos.includes(r.objeto)) g.objetos.push(r.objeto);
  }
  const feito = grupos.length
    ? juntar(grupos.map((g, i) => `${i === 0 ? g.verbo : minuscula(g.verbo)} ${juntar(g.objetos)}`))
    : null;

  const falhas = [...new Set(visiveis.filter((c) => c.estado === "falhou").map((c) => rot(c).falhou))];
  const falhou = falhas.length ? juntar(falhas.map((f, i) => (i === 0 ? f : minuscula(f.replace(/^Não consegui /, ""))))) : null;
  return { rodando: rodando ? rot(rodando).rodando : null, feito, falhou };
}

function resultadoDaFerramenta(conteudo: string | null): "feito" | "falhou" | "cancelada" {
  try {
    const r = JSON.parse(conteudo ?? "{}");
    if (r.ok) return "feito";
    return r.error?.code === "cancelado" ? "cancelada" : "falhou";
  } catch {
    return "feito";
  }
}

/** Reconstrói o fio a partir do histórico. Usa o `meta` da V3 (cartões, confirmações, custo, "Parado");
 *  conversa da V2, sem `meta`, abre só com perguntas, linhas de ferramenta e respostas. */
export function itensDoHistorico(mensagens: Mensagem[]): Item[] {
  const itens: Item[] = [];
  const resultado = new Map<string, "feito" | "falhou" | "cancelada">();
  for (const m of mensagens) if (m.role === "tool" && m.tool_call_id) resultado.set(m.tool_call_id, resultadoDaFerramenta(m.content));

  let linha: Item & { tipo: "ferramentas" } | null = null;
  let inicioTurno = 0; // as confirmações de um turno só mexem nas linhas de ferramenta dele
  for (const m of mensagens) {
    if (m.role === "user") {
      linha = null;
      inicioTurno = itens.length;
      if (m.content) itens.push({ tipo: "voce", chave: novaChave("voce"), texto: m.content });
      continue;
    }
    if (m.role !== "assistant") continue;
    if (m.content) {
      itens.push({ tipo: "texto", chave: novaChave("texto"), trechos: [m.content], final: true });
      linha = null;
    }
    if (m.tool_calls?.length) {
      if (!linha) {
        linha = { tipo: "ferramentas", chave: novaChave("ferr"), chamadas: [] };
        itens.push(linha);
      }
      m.tool_calls.forEach((c, i) => {
        const r = m.ferramentas?.[i]?.rotulo ?? null;
        linha!.chamadas.push({ nome: c.function.name, rotulo: r, estado: (c.id && resultado.get(c.id)) || "feito" });
      });
    }
    const meta = m.meta;
    if (!meta) continue;
    // a confirmação respondida aparece no lugar da linha da ferramenta que ela gravou (ou que falhou ao gravar:
    // "Não gravado" já diz, sem a linha de falha repetir)
    for (const c of meta.confirmacoes ?? []) {
      const coberto = c.resultado === "gravado" ? "feito" : c.resultado === "falhou" ? "falhou" : null;
      if (c.ferramenta && coberto) {
        for (const it of itens.slice(inicioTurno))
          if (it.tipo === "ferramentas") {
            const ch = it.chamadas.find((x) => x.nome === c.ferramenta && x.estado === coberto);
            if (ch) ch.estado = "cancelada";
          }
      }
      const texto = c.linha ?? (c.resultado === "gravado" ? `${c.objeto} gravado · ${c.resumo}` : `Não gravado · ${c.resumo}`);
      // resposta final (só texto): a confirmação fica antes dela, como no turno ao vivo; turno parado com texto e
      // ferramentas na mesma mensagem: depois da linha de ferramenta, na ordem em que aconteceu
      const fim = m.content && !m.tool_calls?.length ? itens.length - 1 : itens.length;
      itens.splice(fim, 0, { tipo: "resolvida", chave: novaChave("conf"), resultado: c.resultado, linha: texto });
    }
    if (meta.cartoes?.length) itens.push({ tipo: "cartoes", chave: novaChave("cartoes"), cartoes: meta.cartoes });
    itens.push({ tipo: "rodape", chave: novaChave("rodape"), custo: meta.custo_usd, parado: meta.parado });
    linha = null;
  }
  // linha de ferramenta sem nada visível (só confirmações) some
  return itens.filter((it) => it.tipo !== "ferramentas" || it.chamadas.some((c) => c.estado !== "cancelada"));
}

export const SUGESTOES = ["Quais vagas combinam mais comigo?", "Como estão minhas candidaturas?", "Registra 30 min estudando React"];

/** Reduzir movimento (sistema ou Aparência): o voo do balão vira troca instantânea, como o CSS. */
export function semMovimento(): boolean {
  const raiz = document.documentElement;
  if (raiz.classList.contains("sem-movimento")) return true;
  if (raiz.classList.contains("com-movimento")) return false;
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}
