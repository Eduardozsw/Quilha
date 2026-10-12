/** Reduzir movimento (Configurações → Aparência): segue o sistema por padrão; "sempre" e "nunca" vencem o sistema.
 *  "sempre" põe `.sem-movimento` no html; "nunca" põe `.com-movimento`, que desliga o `prefers-reduced-motion`. */

export type Movimento = "sistema" | "sempre" | "nunca";

const CHAVE = "quilha.movimento";

export function lerMovimento(): Movimento {
  try {
    const salvo = localStorage.getItem(CHAVE);
    if (salvo === "sempre" || salvo === "nunca") return salvo;
  } catch {
    /* sem armazenamento: segue o sistema */
  }
  return "sistema";
}

export function aplicarMovimento(m: Movimento): void {
  const raiz = document.documentElement;
  raiz.classList.toggle("sem-movimento", m === "sempre");
  raiz.classList.toggle("com-movimento", m === "nunca");
  try {
    if (m === "sistema") localStorage.removeItem(CHAVE);
    else localStorage.setItem(CHAVE, m);
  } catch {
    /* ignora: a escolha vale só nesta sessão */
  }
}
