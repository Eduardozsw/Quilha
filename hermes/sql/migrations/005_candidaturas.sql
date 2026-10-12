-- 005: candidaturas (o que foi enviado, com qual perfil) e os e-mails de processo seletivo triados pelo
-- Jev. Só tabelas novas: nada é recriado. O corpo do e-mail não é guardado (vai ao Jev e é descartado).
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
                  CHECK (status IN ('enviada','em_processo','reprovada','cancelada')),
    teve_avanco   INTEGER NOT NULL DEFAULT 0 CHECK (teve_avanco IN (0,1)),
    respondida_em TEXT,                    -- 1ª resposta (avanço ou reprovação): conta para maturação
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
    processado_em    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emails_cand ON emails (candidatura_id);
