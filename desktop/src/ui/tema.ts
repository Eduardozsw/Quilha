/** Tema da V3: segue o sistema por padrão; a escolha em Configurações → Aparência vence nos dois sentidos.
 *  A troca ao vivo do sistema vem de graça pelo `prefers-color-scheme` do CSS; aqui só mora a escolha manual. */

export type Tema = "sistema" | "claro" | "escuro";

const CHAVE = "quilha.tema";

export function lerTema(): Tema {
  try {
    const salvo = localStorage.getItem(CHAVE);
    if (salvo === "claro" || salvo === "escuro") return salvo;
  } catch {
    /* sem armazenamento: segue o sistema */
  }
  return "sistema";
}

export function aplicarTema(tema: Tema): void {
  const raiz = document.documentElement;
  if (tema === "sistema") raiz.removeAttribute("data-tema");
  else raiz.setAttribute("data-tema", tema);
  try {
    if (tema === "sistema") localStorage.removeItem(CHAVE);
    else localStorage.setItem(CHAVE, tema);
  } catch {
    /* ignora: a escolha vale só nesta sessão */
  }
}
