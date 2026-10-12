// Formatos de data, nome e categoria que mais de uma tela usa.

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export const CATEGORIA: Record<string, string> = {
  avanco: "avanço",
  pendencia: "pendência",
  inscricao_confirmada: "inscrição confirmada",
  reprovado: "reprovado",
  revisar: "a revisar",
  outro: "outro",
};

export function plural(n: number, um: string, varios: string) {
  return `${n} ${n === 1 ? um : varios}`;
}

export function horas(minutos: number) {
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  if (!h) return m ? `${m}min` : "0h";
  return m ? `${h}h${String(m).padStart(2, "0")}` : `${h}h`;
}

export function hora(d: Date) {
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function diaMes(d: Date) {
  return `${String(d.getDate()).padStart(2, "0")} ${MESES[d.getMonth()]}`;
}

/** "Hoje, 08:42", "Ontem, 19:10" ou "27 set, 23:23". */
export function quando(iso: string, agora: Date) {
  const d = new Date(iso);
  const dias = Math.round((new Date(agora).setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (dias === 0) return `Hoje, ${hora(d)}`;
  if (dias === 1) return `Ontem, ${hora(d)}`;
  return `${diaMes(d)}, ${hora(d)}`;
}

export function diasDesde(iso: string, agora: Date) {
  return Math.max(0, Math.floor((agora.getTime() - new Date(iso).getTime()) / 86_400_000));
}

/** Empresa que veio do e-mail em minúsculas ("veloz") aparece com inicial maiúscula. */
const MINUSCULAS = new Set(["a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "na", "no", "para", "com", "of", "and", "the", "to", "at"]);

/** Nome de vaga ou empresa num padrão só: primeira letra de cada palavra.
 *  Só mexe no que veio todo em MAIÚSCULAS ou todo em minúsculas; "iMarket" e "MoBi Global" ficam como estão.
 *  Preposição fica minúscula (menos na abertura) e sigla com ponto ou número ("S.A", "5H") não muda. */
export function padronizar(texto: string | null) {
  if (!texto) return null;
  if (texto !== texto.toUpperCase() && texto !== texto.toLowerCase()) return texto;
  let primeira = true;
  return texto.replace(/[\p{L}\p{N}.]+/gu, (palavra) => {
    const abre = primeira;
    primeira = false;
    if (/[\d.]/.test(palavra) && palavra === palavra.toUpperCase()) return palavra;
    const minuscula = palavra.toLowerCase();
    if (!abre && MINUSCULAS.has(minuscula)) return minuscula;
    return minuscula.charAt(0).toUpperCase() + minuscula.slice(1);
  });
}

export const empresa = padronizar;

export function remetente(de: string | null) {
  if (!de) return "";
  const nome = de.replace(/<[^>]*>/, "").replace(/"/g, "").trim();
  return nome || de.replace(/[<>]/g, "");
}
