-- Hermes — estado operacional. Uma migração por mudança destrutiva (ver sql/migrations/).
-- Convenções: datas em TEXT ISO 8601 UTC; campos JSON como TEXT; CHECK em todo domínio
-- fechado; valor desconhecido é NULL, nunca 0.

-- Índice do vault. DESCARTÁVEL: apagado e reconstruído por `hermes index`.
CREATE TABLE IF NOT EXISTS facts (
    nota        TEXT NOT NULL,             -- caminho relativo no vault
    block_id    TEXT NOT NULL,             -- sem o "^", ex: pipeline
    tipo        TEXT NOT NULL CHECK (tipo IN ('experience','project')),
    entidade    TEXT NOT NULL,             -- campo `id` do frontmatter
    texto       TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',
    indexado_em TEXT NOT NULL,
    PRIMARY KEY (nota, block_id)
);

CREATE TABLE IF NOT EXISTS competencies (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    slug      TEXT NOT NULL UNIQUE,
    nome      TEXT NOT NULL,
    categoria TEXT NOT NULL CHECK (categoria IN
              ('linguagem','dados','automacao','ia','processo','idioma','soft')),
    peso      INTEGER NOT NULL DEFAULT 1 CHECK (peso BETWEEN 1 AND 3),
    criado_em TEXT NOT NULL
);

-- Liga competência a um fato do vault pelo block id.
-- Sem FK para `facts` de propósito: o índice é descartável, a evidência não.
CREATE TABLE IF NOT EXISTS evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    competency_id INTEGER NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
    nota          TEXT NOT NULL,
    block_id      TEXT NOT NULL,
    forca         INTEGER NOT NULL CHECK (forca BETWEEN 1 AND 3),
    tem_metrica   INTEGER NOT NULL DEFAULT 0 CHECK (tem_metrica IN (0,1)),
    observacao    TEXT,
    criado_em     TEXT NOT NULL,
    UNIQUE (competency_id, nota, block_id)
);

-- Histórico de autoavaliação. Nível vigente = linha mais recente.
CREATE TABLE IF NOT EXISTS competency_state (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    competency_id INTEGER NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
    nivel         INTEGER NOT NULL CHECK (nivel BETWEEN 0 AND 4),
    justificativa TEXT NOT NULL,
    origem        TEXT NOT NULL CHECK (origem IN ('declarado','assistido')),
    criado_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_state_comp ON competency_state (competency_id, criado_em DESC);

CREATE VIEW IF NOT EXISTS v_competency_current AS
SELECT c.id, c.slug, c.nome, c.categoria, c.peso,
       s.nivel, s.justificativa, s.criado_em AS avaliado_em,
       (SELECT COUNT(*) FROM evidence e WHERE e.competency_id = c.id) AS n_evidencias
FROM competencies c
LEFT JOIN competency_state s ON s.id = (
    SELECT id FROM competency_state
    WHERE competency_id = c.id
    ORDER BY criado_em DESC, id DESC
    LIMIT 1
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa     TEXT NOT NULL,
    titulo      TEXT NOT NULL,
    url         TEXT,
    fonte       TEXT NOT NULL CHECK (fonte IN ('colado','url','greenhouse','lever','gupy')),
    senioridade TEXT,
    local       TEXT,
    texto_bruto TEXT NOT NULL,
    hash_texto  TEXT NOT NULL,             -- sha256 do texto normalizado; dedup de vaga sem URL
    coletado_em TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'novo'
                CHECK (status IN ('novo','analisado','aplicado','descartado'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_hash ON jobs (hash_texto);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_url  ON jobs (url) WHERE url IS NOT NULL;

-- Coletor (fase 6). A fila é uma linha por fonte de `fontes.yaml` e sobrevive entre execuções:
-- é ela que guarda quantas falhas seguidas houve e quando tentar de novo (backoff entre execuções).
CREATE TABLE IF NOT EXISTS fila_coleta (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte         TEXT NOT NULL CHECK (fonte IN ('greenhouse','lever','gupy')),
    board         TEXT NOT NULL,           -- token (greenhouse), empresa (lever) ou subdomínio (gupy)
    estado        TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','ok','falhou')),
    tentativas    INTEGER NOT NULL DEFAULT 0 CHECK (tentativas >= 0),  -- falhas seguidas
    proximo_em    TEXT NOT NULL,
    ultima_ok_em  TEXT,
    ultimo_erro   TEXT,
    atualizado_em TEXT NOT NULL,
    UNIQUE (fonte, board)
);

-- Uma linha por fonte processada numa execução de `job collect`. `execucao` = runs.started_at.
-- Contagem desconhecida (coleta que falhou) é NULL, nunca 0.
CREATE TABLE IF NOT EXISTS coletas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao        TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    board           TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ok','falhou','bloqueada')),
    vagas_vistas    INTEGER,
    vagas_filtradas INTEGER,               -- passaram no filtro de título
    vagas_novas     INTEGER,
    duplicadas      INTEGER,
    duracao_ms      INTEGER NOT NULL,
    erro            TEXT,
    criado_em       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coletas_execucao ON coletas (execucao);

CREATE TABLE IF NOT EXISTS job_requirements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    texto         TEXT NOT NULL,
    tipo          TEXT NOT NULL CHECK (tipo IN ('obrigatorio','desejavel')),
    competency_id INTEGER REFERENCES competencies(id) ON DELETE SET NULL,
    confianca     REAL CHECK (confianca IS NULL OR (confianca BETWEEN 0 AND 1))
);
CREATE INDEX IF NOT EXISTS idx_req_job ON job_requirements (job_id);

CREATE TABLE IF NOT EXISTS job_matches (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    score     INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    formula   TEXT NOT NULL,               -- versão da fórmula, ex: 'v1'
    cobertura TEXT NOT NULL DEFAULT '[]',
    lacunas   TEXT NOT NULL DEFAULT '[]',
    riscos    TEXT NOT NULL DEFAULT '[]',
    model     TEXT,
    cost_usd  REAL,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_match_job ON job_matches (job_id, criado_em DESC);

CREATE TABLE IF NOT EXISTS cv_versions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    INTEGER REFERENCES jobs(id) ON DELETE SET NULL,  -- NULL = currículo base
    idioma    TEXT NOT NULL CHECK (idioma IN ('pt','en')),
    caminho   TEXT NOT NULL,
    fatos     TEXT NOT NULL DEFAULT '[]',  -- JSON: ["nota.md#block-id", ...]
    model     TEXT,
    cost_usd  REAL,
    criado_em TEXT NOT NULL,
    perfil       TEXT,              -- slug de curriculos.yaml; NULL = currículo geral
    selecao_hash TEXT,              -- mesma seleção = mesmo hash: reaproveita, não paga de novo
    palavras     INTEGER CHECK (palavras IS NULL OR palavras >= 0),
    conteudo     TEXT,              -- o Markdown gerado; o arquivo em out/ é só a cópia mais recente
    redacao      TEXT,              -- JSON {resumo, bullets}: o que o modelo escreveu (migração 004)
    estrutura    TEXT               -- JSON de curriculo.estruturar: página, fonte de cada linha e PDF (008)
);
-- Índices de perfil e hash ficam na migração 003: num banco antigo este arquivo roda antes dela,
-- quando as colunas ainda não existem.

-- Fonte confiável do estudo: você declarando.
CREATE TABLE IF NOT EXISTS study_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    data          TEXT NOT NULL,           -- YYYY-MM-DD, data local
    competency_id INTEGER REFERENCES competencies(id) ON DELETE SET NULL,
    minutos       INTEGER NOT NULL CHECK (minutos > 0),
    o_que_fez     TEXT NOT NULL,
    dificuldade   INTEGER CHECK (dificuldade IS NULL OR dificuldade BETWEEN 1 AND 5),
    travou_em     TEXT,
    criado_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_study_data ON study_sessions (data);

-- Sinal, não estudo. Serve para o agente PERGUNTAR.
CREATE TABLE IF NOT EXISTS activity_signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    data          TEXT NOT NULL,
    repo          TEXT NOT NULL,
    ref           TEXT NOT NULL,           -- sha do commit
    resumo        TEXT NOT NULL,
    competency_id INTEGER REFERENCES competencies(id) ON DELETE SET NULL,
    estado        TEXT NOT NULL DEFAULT 'novo'
                  CHECK (estado IN ('novo','perguntado','confirmado','ignorado')),
    session_id    INTEGER REFERENCES study_sessions(id) ON DELETE SET NULL,
    criado_em     TEXT NOT NULL,
    UNIQUE (repo, ref)
);

CREATE TABLE IF NOT EXISTS study_plan (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    semana    TEXT NOT NULL UNIQUE,        -- ISO, ex: 2026-W39
    objetivo  TEXT NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id       INTEGER NOT NULL REFERENCES study_plan(id) ON DELETE CASCADE,
    competency_id INTEGER REFERENCES competencies(id) ON DELETE SET NULL,
    job_id        INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    descricao     TEXT NOT NULL,
    recurso       TEXT,
    minutos_alvo  INTEGER NOT NULL CHECK (minutos_alvo > 0),
    status        TEXT NOT NULL DEFAULT 'previsto'
                  CHECK (status IN ('previsto','feito','parcial','abandonado'))
);

-- Conversa: permite `hermes chat --continue` e auditoria de custo.
CREATE TABLE IF NOT EXISTS agent_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    model       TEXT,
    cost_usd    REAL,
    resumo      TEXT,                      -- resumo das mensagens antigas, quando houve truncamento
    titulo      TEXT                       -- título editado na Conversa; NULL = a primeira pergunta cortada (010)
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content      TEXT,
    tool_calls   TEXT,                     -- JSON, quando role='assistant'
    tool_call_id TEXT,                     -- quando role='tool'
    criado_em    TEXT NOT NULL,
    meta         TEXT,                     -- JSON da Conversa: custo, cartões, confirmações, parado (010)
    UNIQUE (session_id, idx)
);

-- Observabilidade: uma linha por execução, gravada no finally.
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    comando           TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('success','partial','failed')),
    llm_calls         INTEGER NOT NULL DEFAULT 0 CHECK (llm_calls >= 0),
    tool_calls        INTEGER NOT NULL DEFAULT 0 CHECK (tool_calls >= 0),
    tool_errors       INTEGER NOT NULL DEFAULT 0 CHECK (tool_errors >= 0),
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL,                -- NULL = alguma chamada sem preço conhecido
    model             TEXT,
    session_id        INTEGER REFERENCES agent_sessions(id) ON DELETE SET NULL,
    warnings          TEXT NOT NULL DEFAULT '[]',
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs (started_at);

-- Fase 10: candidaturas e e-mails de processo seletivo (migração 005).
CREATE TABLE IF NOT EXISTS candidaturas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    empresa       TEXT,
    empresa_norm  TEXT,                    -- candidaturas.normalizar_empresa(empresa): chave da ligação
    titulo        TEXT,
    perfil        TEXT,                    -- slug de curriculos.yaml; 'geral'; NULL = pingada
    cv_version_id INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,
    origem        TEXT NOT NULL CHECK (origem IN ('cv','email','manual')),
    enviada_em    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'enviada'
                  CHECK (status IN ('a_enviar','enviada','em_processo','entrevista','reprovada','cancelada')),
    teve_avanco   INTEGER NOT NULL DEFAULT 0 CHECK (teve_avanco IN (0,1)),
    respondida_em TEXT,                    -- 1ª resposta (avanço ou reprovação): conta para maturação
    entrevista_em TEXT,                    -- ISO com fuso; com data, o status é 'entrevista'
    entrevista_titulo TEXT,                -- "O quê" da entrevista (padrão "Entrevista") (migração 009)
    roteiro       TEXT,                    -- roteiro de preparo salvo, JSON (migração 009)
    roteiro_em    TEXT,
    atualizada_em TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cand_job ON candidaturas (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cand_empresa ON candidaturas (empresa_norm);

CREATE TABLE IF NOT EXISTS emails (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id         TEXT NOT NULL UNIQUE,  -- re-sync não classifica de novo
    recebido_em      TEXT NOT NULL,         -- ISO, do internalDate do Gmail
    de               TEXT NOT NULL,
    assunto          TEXT NOT NULL,
    corpo            TEXT,                  -- texto limpo; NULL = gravado antes da 006
    categoria_jev    TEXT,
    prob_categoria   REAL,
    prob_processo    REAL,
    prob_prazo       REAL,                  -- só gravado; prazo fica fora da fase 10
    final            TEXT NOT NULL CHECK (final IN
                     ('avanco','pendencia','inscricao_confirmada','reprovado','revisar','outro')),
    rotulo_manual    TEXT CHECK (rotulo_manual IS NULL OR rotulo_manual IN
                     ('avanco','pendencia','inscricao_confirmada','reprovado','outro')),
    empresa_extraida TEXT,
    candidatura_id   INTEGER REFERENCES candidaturas(id) ON DELETE SET NULL,
    latencia_ms      INTEGER,
    entrevista_em    TEXT,                  -- data da entrevista que a triagem leu no e-mail (ISO com fuso)
    processado_em    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emails_cand ON emails (candidatura_id);

-- Estado do app que não é dado de domínio (ex.: a última visita à Início).
CREATE TABLE IF NOT EXISTS estado_app (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- Servidor MCP sem LLM próprio: o pedido que espera o texto do modelo do cliente (`submit_draft`).
-- `respostas` = {chave do pedido: texto}; vale 24 h e é apagado quando a tool termina.
CREATE TABLE IF NOT EXISTS rascunhos_mcp (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    argumentos TEXT NOT NULL,
    pendente TEXT NOT NULL,
    respostas TEXT NOT NULL DEFAULT '{}',
    criado_em TEXT NOT NULL
);
