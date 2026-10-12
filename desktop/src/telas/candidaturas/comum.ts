import { padronizar } from "../../formato";
import type { Candidatura, StatusCandidatura } from "../../tipos";

export type IdEtapa = "a_enviar" | "entrevista" | "em_processo" | "enviada";

/** Etapas da lista, nesta ordem (decisão 3); "Aguardando resposta" é o mesmo rótulo da Início. */
export const ETAPAS: { id: IdEtapa; nome: string }[] = [
  { id: "a_enviar", nome: "A enviar" },
  { id: "entrevista", nome: "Entrevista" },
  { id: "em_processo", nome: "Em análise" },
  { id: "enviada", nome: "Aguardando resposta" },
];

const ORDEM = new Map(ETAPAS.map((e, i) => [e.id as string, i]));

/** Ordem da lista: por etapa; dentro dela, a mais recente primeiro (na Entrevista, a mais próxima). */
/** Instante em ms (fusos diferentes comparam pelo relógio, não pelo texto); sem data = NaN. */
const instante = (iso: string | null | undefined) => (iso ? Date.parse(iso) : NaN);

/** Na etapa Entrevista: as próximas primeiro (a mais perto no topo), depois as que já passaram (a mais recente
 *  primeiro), sem data no fim. Nas outras: a mais recente (último e-mail ou envio) primeiro. */
export function ordenar(a: Candidatura, b: Candidatura, agora = Date.now()): number {
  const etapa = (ORDEM.get(a.status) ?? 9) - (ORDEM.get(b.status) ?? 9);
  if (etapa) return etapa;
  if (a.status === "entrevista") {
    const [ta, tb] = [instante(a.entrevista_em), instante(b.entrevista_em)];
    const grupo = (t: number) => (Number.isNaN(t) ? 2 : t >= agora ? 0 : 1);
    if (grupo(ta) !== grupo(tb)) return grupo(ta) - grupo(tb);
    if (grupo(ta) === 0) return ta - tb;
    if (grupo(ta) === 1) return tb - ta;
    return b.id - a.id;
  }
  return instante(b.ultimo_email_em ?? b.enviada_em) - instante(a.ultimo_email_em ?? a.enviada_em) || b.id - a.id;
}

export const ENCERRADAS: StatusCandidatura[] = ["reprovada", "cancelada"];

export type IdCategoria = "avanco" | "pendencia" | "inscricao_confirmada" | "reprovado" | "outro";

/** As 5 pílulas de categoria, as mesmas na triagem e dentro do e-mail da linha do tempo (decisão 7). */
export const CATEGORIAS: { id: IdCategoria; nome: string; tecla: "1" | "2" | "3" | "4" | "5" }[] = [
  { id: "avanco", nome: "Avanço", tecla: "1" },
  { id: "pendencia", nome: "Pendência", tecla: "2" },
  { id: "inscricao_confirmada", nome: "Inscrição confirmada", tecla: "3" },
  { id: "reprovado", nome: "Reprovado", tecla: "4" },
  { id: "outro", nome: "Não é de processo", tecla: "5" },
];

export function nomeCategoria(id: string | null | undefined): string {
  return CATEGORIAS.find((c) => c.id === id)?.nome ?? "A revisar";
}

/** Selo da etapa: `a_enviar` âmbar, `entrevista` acento, `reprovada` tijolo, os demais neutros. */
export const SELO: Record<StatusCandidatura, { tom: "ok" | "at" | "er" | "ne"; nome: string }> = {
  a_enviar: { tom: "at", nome: "A enviar" },
  entrevista: { tom: "ok", nome: "Entrevista" },
  em_processo: { tom: "ne", nome: "Em análise" },
  enviada: { tom: "ne", nome: "Aguardando resposta" },
  reprovada: { tom: "er", nome: "reprovada" },
  cancelada: { tom: "ne", nome: "cancelada" },
};

type Basica = Pick<Candidatura, "titulo" | "empresa" | "origem">;

/** A pingada nasce de um e-mail, só com a empresa. */
export function ePingada(c: Basica): boolean {
  return c.origem === "email" && !c.titulo;
}

/** O título padronizado ("DESENVOLVEDOR REACT" → "Desenvolvedor React"), ou a empresa. */
export function nomeDa(c: Basica): string {
  return padronizar(c.titulo?.trim() || null) || padronizar(c.empresa?.trim() || null) || "Candidatura sem empresa";
}

function inicioDoDia(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function diasEntre(iso: string, agora: Date) {
  return Math.round((inicioDoDia(agora) - inicioDoDia(new Date(dataLocal(iso)))) / 86_400_000);
}

/** "2026-10-09" sozinho é meia-noite UTC: vira o meio-dia local para não cair no dia anterior. */
function dataLocal(iso: string) {
  return iso.length === 10 ? `${iso}T12:00:00` : iso;
}

/** "hoje", "há 1 dia", "há 11 dias" */
export function ha(iso: string, agora = new Date()): string {
  const dias = diasEntre(iso, agora);
  if (dias <= 0) return "hoje";
  return dias === 1 ? "há 1 dia" : `há ${dias} dias`;
}

/** "27 de set." */
export function diaMes(iso: string): string {
  return new Date(dataLocal(iso)).toLocaleDateString("pt-BR", { day: "numeric", month: "short" });
}

function hora(d: Date) {
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

/** Data de um marco: "hoje, 08:42", "ontem, 17:10" ou "30 de set." */
export function quandoMarco(iso: string, agora = new Date()): string {
  const dias = diasEntre(iso, agora);
  if (iso.length > 10 && dias === 0) return `hoje, ${hora(new Date(iso))}`;
  if (iso.length > 10 && dias === 1) return `ontem, ${hora(new Date(iso))}`;
  return diaMes(iso);
}

/** "amanhã, 14h", "hoje, 9h30", "sex, 10h" ou "12 de out., 10h" */
export function quandoEntrevista(iso: string, agora = new Date()): string {
  const d = new Date(iso);
  const dias = -diasEntre(iso, agora);
  const dia = dias === 0 ? "hoje" : dias === 1 ? "amanhã" : dias > 1 && dias < 7
    ? d.toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "") : diaMes(iso);
  const h = d.getHours(), min = d.getMinutes();
  return `${dia}, ${h}h${min ? String(min).padStart(2, "0") : ""}`;
}

export function entrevistaFutura(iso: string | null, agora = new Date()): boolean {
  return !!iso && new Date(iso).getTime() > agora.getTime();
}

/** Metadado do item da lista: "Orla Tech · entrevista amanhã, 14h", "Lumina Saúde · há 11 dias",
 *  "Maré Digital · currículo gerado hoje"; na pingada, "sem título · sem perfil · há 1 dia". */
export function metaDa(c: Candidatura, agora = new Date()): string {
  const quando = ha(c.ultimo_email_em ?? c.enviada_em, agora);
  if (ePingada(c)) return ["sem título", !c.perfil && "sem perfil", quando].filter(Boolean).join(" · ");
  const empresa = c.empresa ?? "Sem empresa";
  if (c.status === "a_enviar") return `${empresa} · currículo gerado ${ha(c.enviada_em, agora)}`;
  if (c.status === "entrevista" && c.entrevista_em && entrevistaFutura(c.entrevista_em, agora))
    return `${empresa} · entrevista ${quandoEntrevista(c.entrevista_em, agora)}`;
  return `${empresa} · ${quando}`;
}

/** "agora", "há 5 min", "há 2 h", "há 3 dias" */
export function haTempo(iso: string, agora = new Date()): string {
  const min = Math.round((agora.getTime() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  if (min < 24 * 60) return `há ${Math.round(min / 60)} h`;
  return ha(iso, agora);
}

export function plural(n: number, um: string, varios: string): string {
  return `${n} ${n === 1 ? um : varios}`;
}

export function mensagem(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
