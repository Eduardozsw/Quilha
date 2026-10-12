import { Briefcase, FileText, Gauge, LayoutGrid, MessageSquare, Send, type LucideIcon } from "lucide-react";

/** As 7 telas da V3. Configurações não entra na navegação: abre pela engrenagem do rodapé da lateral. */
export type IdTela = "inicio" | "conversa" | "vagas" | "candidaturas" | "curriculos" | "competencias" | "configuracoes";

export const NAVEGACAO: { id: IdTela; nome: string; icone: LucideIcon }[] = [
  { id: "inicio", nome: "Início", icone: LayoutGrid },
  { id: "conversa", nome: "Conversa", icone: MessageSquare },
  { id: "vagas", nome: "Vagas", icone: Briefcase },
  { id: "candidaturas", nome: "Candidaturas", icone: Send },
  { id: "curriculos", nome: "Currículos", icone: FileText },
  { id: "competencias", nome: "Competências", icone: Gauge },
];

export const TELAS: IdTela[] = [...NAVEGACAO.map((t) => t.id), "configuracoes"];
