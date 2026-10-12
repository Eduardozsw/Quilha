import type { Competencia } from "../../tipos";
import { diaMes } from "../candidaturas/comum";

export type Grupo = "sustenta" | "falta" | "sem";

/** Sem nível declarado; sustenta quando o vault prova (nível ≥ 2 com evidência); o resto falta evidência. */
export function grupo(c: Competencia): Grupo {
  if (c.nivel === null) return "sem";
  return c.pronta_para_cv ? "sustenta" : "falta";
}

export const GRUPOS: { id: Grupo; nome: string }[] = [
  { id: "sustenta", nome: "Sustentam o currículo" },
  { id: "falta", nome: "Falta evidência" },
  { id: "sem", nome: "Sem nível" },
];

/** Cor das barras cheias do medidor: acento quando sustenta, âmbar quando falta; sem nível, nenhuma cheia. */
export function corMedidor(g: Grupo): string {
  return g === "sustenta" ? "var(--acento)" : g === "falta" ? "var(--atencao)" : "var(--linha-forte)";
}

/** "22 de set." */
export function dataCurta(iso: string): string {
  return diaMes(iso);
}

function inicioDoDia(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "hoje", "ontem", "seg" (nesta semana) ou "12 de set.". */
export function quando(iso: string, agora = new Date()): string {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  const dias = Math.round((inicioDoDia(agora) - inicioDoDia(d)) / 86_400_000);
  if (dias <= 0) return "hoje";
  if (dias === 1) return "ontem";
  if (dias < 7) return d.toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "");
  return dataCurta(iso);
}

export function plural(n: number, um: string, varios: string): string {
  return `${n} ${n === 1 ? um : varios}`;
}

/** "nota.md#bloco", a referência que a API aceita para ligar e desligar. */
export function referencia(nota: string, bloco: string): string {
  return `${nota}#${bloco}`;
}
