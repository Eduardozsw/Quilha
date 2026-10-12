// Formas que a API devolve. Espelham os dicts de hermes/domain; só o que as telas usam.

export type Competencia = {
  slug: string;
  nome: string;
  categoria: string;
  peso: number;
  nivel: number | null;
  justificativa: string | null;
  avaliado_em: string | null;
  n_evidencias: number;
  situacao: "ok" | "nunca avaliada" | "sem evidencia" | "evidencia insuficiente";
  pronta_para_cv: boolean;
};

export type Evidencia = {
  nota: string;
  block_id: string;
  forca: number;
  tem_metrica: number;
  observacao: string | null;
  texto: string | null;
};

export type Candidato = { referencia: string; block_id: string; texto: string; tem_metrica: boolean };

/** Por que a evidência não sustenta um nível, na língua da tela; `null` quando passa. */
export type Recusa = { titulo: string; texto: string } | null;

export type EstudoFeito = { data: string; minutos: number; o_que_fez: string };

export type DetalheCompetencia = {
  competencia: Competencia;
  evidencias: Evidencia[];
  candidatos: Candidato[];
  recusas: Record<string, Recusa>;
  estudos: { ultimos: EstudoFeito[]; total: number };
};

export type Categoria = { id: string; nome: string };

export type Sinais = { sinais: Sinal[]; lidos_em: string | null };

export type LeituraGit = { lido: boolean; lidos_em: string; sinais_novos?: number; avisos?: string[] };

export type PlanoGerado = {
  plano: {
    semana: string;
    objetivo: string;
    itens: { competencia: string; descricao: string; recurso: string | null; minutos_alvo: number }[];
    minutos_alvo: number;
    minutos_disponiveis: number;
  };
  markdown: string;
  custo: Custo;
  semana: string;
  inicio: string;
  fim: string;
  ja_existia: boolean;
};

export type Custo = {
  llm_calls: number;
  tokens: number;
  custo_usd: number | null;
  avisos?: string[];
};

export type Vaga = {
  id: number;
  empresa: string;
  titulo: string;
  status: string;
  coletado_em: string;
  n_requisitos: number;
  score: number | null;
};

export type Requisito = {
  id: number;
  texto: string;
  tipo: "obrigatorio" | "desejavel";
  confianca: number | null;
  competencia: string | null;
};

export type ItemCobertura = {
  requisito_id: number;
  texto: string;
  tipo: string;
  competencia: string | null;
  nivel: number | null;
  evidencias: string[];
  cobertura: number;
};

export type Lacuna = {
  requisito_id: number;
  texto: string;
  motivo: string;
  ligadas?: string[];
  candidatos?: { block_id: string; referencia?: string }[];
  comentario?: string;
};

export type Match = {
  score: number;
  formula: string;
  cobertura: ItemCobertura[];
  lacunas: Lacuna[];
  riscos: string[];
  criado_em?: string;
  cost_usd?: number | null;
};

export type VersaoCV = {
  id: number;
  perfil: string | null;
  idioma: "pt" | "en";
  job_id: number | null;
  vaga_titulo: string | null;
  vaga_empresa: string | null;
  criado_em: string;
  palavras: number | null;
  fatos: string[];
  model: string | null;
  cost_usd: number | null;
  conteudo: string;
  caminho: string;
  tem_estrutura?: boolean;
};

export type GrupoCV = {
  perfil: string | null;
  titulo: string;
  cargo: { pt: string; en: string } | null;
  foco: string;
  versoes: VersaoCV[];
};

export type Sessao = {
  id: number;
  started_at: string;
  finished_at: string | null;
  model: string | null;
  cost_usd: number | null;
  titulo: string | null;
  n_mensagens: number;
};

export type Mensagem = {
  role: "user" | "assistant" | "tool" | "system";
  content: string | null;
  tool_calls?: { id?: string; function: { name: string; arguments: string } }[];
  tool_call_id?: string;
  /** só nas `assistant` com `tool_calls`: os rótulos da linha de ferramenta */
  ferramentas?: { nome: string; rotulo: RotuloFerramenta }[];
  /** da tela, na última resposta de cada turno (V3); conversas da V2 vêm sem */
  meta?: MetaResposta | null;
};

export type RotuloFerramenta = { rodando: string; feito: string; falhou: string; verbo: string; objeto: string };

export type CartaoVaga = {
  tipo: "vaga"; job_id: number; titulo: string; empresa: string; senioridade: string | null; local: string | null;
  /** null: requisitos ainda não extraídos (sem nota) */
  score: number | null; cobertos: number; total: number; lacunas: string[];
};
export type CartaoCandidatura = {
  tipo: "candidatura"; id: number; titulo: string | null; empresa: string | null; status: string;
  ultimo_email: { assunto: string; recebido_em: string } | null;
};
export type CartaoConversa = CartaoVaga | CartaoCandidatura;

export type ResultadoConfirmacao = "gravado" | "recusado" | "expirou" | "falhou";

export type MetaResposta = {
  custo_usd: number | null;
  cartoes: CartaoConversa[];
  confirmacoes: { objeto: string; resumo: string; resultado: ResultadoConfirmacao; linha?: string; ferramenta?: string }[];
  ferramentas: { nome: string; ok: boolean; cancelada?: boolean }[];
  parado: boolean;
};

export type Sinal = { id: number; data: string; repo: string; sha: string; resumo: string };

export type Semana = {
  semana: string;
  inicio: string;
  fim: string;
  minutos: number;
  minutos_alvo: number;
  por_competencia: Record<string, number>;
  sessoes: { id: number; data: string; minutos: number; o_que_fez: string; competencia: string | null }[];
  plano: {
    objetivo: string;
    itens: { descricao: string; competencia: string | null; minutos_alvo: number; minutos_feitos: number }[];
  } | null;
  sinais_pendentes: number;
};

export type Run = {
  id: number;
  started_at: string;
  comando: string;
  status: "success" | "partial" | "failed";
  llm_calls: number;
  cost_usd: number | null;
  model: string | null;
  error: string | null;
};

export type Problema = { nivel: "erro" | "aviso"; nota: string; mensagem: string; linha: number | null };

export type CandidaturaPainel = {
  id: number;
  empresa: string | null;
  titulo: string | null;
  perfil: string | null;
  status: "enviada" | "em_processo";
  enviada_em: string;
  job_id: number | null;
  score: number | null;
  ultimo_email_em: string | null;
  ultimo_email: { assunto: string; categoria: string } | null;
};

export type EventoAtividade = { quando: string; titulo: string; detalhe: string | null } & (
  | { tipo: "email"; categoria: string; manual: boolean }
  | { tipo: "curriculo"; perfil: string | null; idioma: "pt" | "en"; palavras: number | null; fatos: number }
  | { tipo: "match"; score: number }
  | { tipo: "estudo"; minutos: number }
);

export type Painel = {
  agora: string;
  numeros: {
    vagas_abertas: number;
    vagas_novas_hoje: number;
    candidaturas_ativas: number;
    candidaturas_em_processo: number;
    emails_a_triar: number;
    estudo_minutos: number;
    estudo_minutos_alvo: number | null;
    vagas_com_requisitos: number;
  };
  desde_ontem: { emails_triados: number; vagas_boas: number; avancos: number; score_bom: number };
  desde_visita: { desde: string; emails_triados: number; vagas_boas: number; avancos: number; score_bom: number };
  pede_acao: CartaoInicio[];
  mudancas: MudancaInicio[];
  etapas: Record<"a_enviar" | "entrevista" | "em_processo" | "enviada", { total: number; itens: { id: number; empresa: string | null; titulo: string | null; quando: string }[] }>;
  candidaturas: CandidaturaPainel[];
  atividade: EventoAtividade[];
  indice: { notas: number; indexado_em: string | null };
};

export type StatusCandidatura = "a_enviar" | "enviada" | "em_processo" | "entrevista" | "reprovada" | "cancelada";

export type Candidatura = {
  id: number;
  job_id: number | null;
  empresa: string | null;
  titulo: string | null;
  perfil: string | null;
  origem: "cv" | "email" | "manual";
  enviada_em: string;
  status: StatusCandidatura;
  teve_avanco: number;
  respondida_em: string | null;
  entrevista_em: string | null;
  entrevista_titulo: string | null;
  atualizada_em: string;
  n_emails: number;
  ultimo_email_em: string | null;
  score: number | null;
};

export type EmailProcesso = {
  id: number;
  recebido_em: string;
  de: string;
  assunto: string;
  corpo: string | null;
  categoria: string;
  manual: boolean;
};

export type DetalheCandidatura = {
  candidatura: Omit<Candidatura, "n_emails" | "ultimo_email_em" | "score"> & { roteiro_em: string | null };
  vaga: { id: number; titulo: string; empresa: string; url: string | null; score: number | null } | null;
  cv: { id: number; perfil: string | null; idioma: "pt" | "en"; criado_em: string; palavras: number | null; n_fatos: number | null } | null;
  emails: EmailProcesso[];
  /** só na pingada: candidaturas ativas (ou a enviar) da mesma empresa, para juntar */
  parecidas: { id: number; titulo: string | null; empresa: string | null; status: StatusCandidatura }[];
  roteiro: { itens: ItemRoteiro[]; gerado_em: string } | null;
};

export type ItemRoteiro = { tema: string; o_que_revisar?: string; pergunta_provavel?: string };

export type PerfilCurriculo = { slug: string; titulo: string; cargo: { pt: string; en: string } | null };

export type VagaAnunciada = {
  id: string;
  titulo: string;
  empresa: string;
  local: string | null;
  url: string;
  fonte: string;
  anunciada_em: string;
  alerta: string | null;
  vezes: number;
  ja_candidatou: boolean;
};

export type VisaoEmail = "pendentes" | "processo" | "outros";

export type EmailTriagem = {
  id: number;
  recebido_em: string;
  de: string;
  assunto: string;
  categoria: string;
  categoria_jev: string | null;
  prob_categoria: number | null;
  manual: boolean;
  empresa_extraida: string | null;
  candidatura_id: number | null;
  cand_empresa: string | null;
  cand_titulo: string | null;
  corpo?: string | null;
};

export type ListaEmails = {
  emails: EmailTriagem[];
  contagens: Record<VisaoEmail, number>;
  ultimo_sync: string | null;
};

export type ResultadoSync = {
  lidos: number;
  novos: number;
  ja_vistos: number;
  ligados: number;
  pendentes: number;
  por_categoria: Record<string, number>;
  chegou_ao_maximo: boolean;
  custo: Custo;
};

// --- V3 · Vagas ---------------------------------------------------------------------

export type StatusVaga = "novo" | "analisado" | "aplicado" | "descartado";

export type VagaLista = {
  id: number;
  empresa: string;
  titulo: string;
  status: StatusVaga;
  coletado_em: string;
  n_requisitos: number;
  /** null: requisitos ainda não extraídos (sem nota) */
  score: number | null;
  nova: boolean;
  senioridade: string | null;
  local: string | null;
  url: string | null;
};

export type RequisitoAvaliado = {
  id: number;
  texto: string;
  tipo: "obrigatorio" | "desejavel";
  competencia: string | null;
  coberto: boolean;
  fonte: string;
};

export type Avaliacao = { score: number | null; cobertos: number; total: number; requisitos: RequisitoAvaliado[] };

export type DetalheVaga = {
  vaga: VagaLista;
  sobre: string;
  avaliacao: Avaliacao;
  match: Match | null;
};

// --- V3 · Currículos ------------------------------------------------------------------

export type BulletCV = { texto: string; origem: string; referencia: string };

export type EntradaCV = {
  entidade: string;
  titulo: string;
  subtitulo: string | null;
  cargo: string | null;
  periodo: string | null;
  local: string | null;
  stack: string[];
  link: string | null;
  bullets: BulletCV[];
};

export type EstruturaCV = {
  idioma: "pt" | "en";
  rotulos: { experience: string; project: string; competencias: string; formacao: string; idiomas: string };
  nome: string;
  cargo: string;
  contato: { texto: string; url: string | null }[];
  idiomas: string[];
  resumo: string;
  experiencias: EntradaCV[];
  projetos: EntradaCV[];
  habilidades: { rotulo: string; itens: string[] }[];
  formacao: { curso: string; instituicao: string; periodo: string }[];
};

export type FonteLinha = { nota: string; block_id: string; texto: string | null; no_vault: boolean; obsidian: string | null };

export type DetalheVersao = {
  versao: VersaoCV & { irma_id: number | null };
  estrutura: EstruturaCV | null;
  fontes: Record<string, FonteLinha>;
};

export type LinhaPrevia = { ref: string; pagina: number; x: number; y: number; w: number; h: number };
export type PreviaCV = { largura: number; altura: number; paginas: string[]; linhas: LinhaPrevia[]; limite: number; passou: boolean };

export type FatoPrevia = { referencia: string; nota: string; block_id: string; texto: string; entidade: string };

// --- V3 · Início ----------------------------------------------------------------------

export type CartaoInicio =
  | { tipo: "entrevista"; candidatura_id: number; empresa: string | null; titulo: string | null; entrevista_em: string }
  | { tipo: "a_enviar"; candidatura_id: number; empresa: string | null; titulo: string | null; gerado_em: string; outras: number }
  | { tipo: "vaga"; job_id: number; empresa: string; titulo: string; score: number; coletado_em: string; outras: number }
  | { tipo: "emails"; quantos: number; primeiro: { email_id: number; assunto: string; de: string; empresa: string | null; recebido_em: string } };

export type MudancaInicio =
  | { tipo: "vagas_boas"; quantas: number; quando: string }
  | { tipo: "avanco" | "reprovado"; candidatura_id: number; empresa: string | null; quando: string }
  | { tipo: "curriculo"; empresa: string | null; fatos: number; quando: string }
  | { tipo: "nivel"; competencia: string; nivel: number; quando: string }
  | { tipo: "niveis"; quantos: number; quando: string };

export type EstadoConfig = {
  base: string;
  vault: { caminho: string; existe: boolean; notas: number; sugestao: string };
  llm: { modelo: string | null; chave_definida: boolean; limite_usd: number };
  triagem: { classificador: "llm" | "jev"; jev_chave_definida: boolean };
  email: {
    origem: string; imap_host: string; imap_usuario: string; imap_senha_definida: boolean;
    gmail_pasta: string; gmail_credenciais: boolean; rotulos_disponiveis: boolean; dias: number;
  };
  pastas: { base: string; saida: string; backups: string; ultima_copia: string | null };
  app: { versao: string; sistema: string };
  pronto: boolean;
  configurado: boolean;
};

/** GET /api/candidaturas/notas: a nota de cada recorte pela taxa de avanço das candidaturas enviadas. */
export type NotasPerfil = {
  perfis: { perfil: string; enviados: number; maturados: number; avancos: number; taxa: number | null; nota: number | null; falta: string }[];
  pingadas: number;
};
