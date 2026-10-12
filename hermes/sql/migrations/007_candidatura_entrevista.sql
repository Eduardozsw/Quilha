-- 007: etapa `entrevista` nas candidaturas, com a data em `entrevista_em` (ISO com fuso), e a data que a
-- triagem leu no e-mail em `emails.entrevista_em`. Recria as tabelas porque o SQLite não altera CHECK e
-- porque num banco novo o schema.sql já traz as colunas (ADD COLUMN falharia). As chaves estrangeiras ficam desligadas durante a
-- troca: com elas ligadas, o DROP TABLE apagaria a ligação dos e-mails (ON DELETE SET NULL).
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE candidaturas_007 (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    empresa       TEXT,
    empresa_norm  TEXT,
    titulo        TEXT,
    perfil        TEXT,
    cv_version_id INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,
    origem        TEXT NOT NULL CHECK (origem IN ('cv','email','manual')),
    enviada_em    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'enviada'
                  CHECK (status IN ('enviada','em_processo','entrevista','reprovada','cancelada')),
    teve_avanco   INTEGER NOT NULL DEFAULT 0 CHECK (teve_avanco IN (0,1)),
    respondida_em TEXT,
    entrevista_em TEXT,
    atualizada_em TEXT NOT NULL
);
INSERT INTO candidaturas_007 (id, job_id, empresa, empresa_norm, titulo, perfil, cv_version_id, origem,
                              enviada_em, status, teve_avanco, respondida_em, atualizada_em)
SELECT id, job_id, empresa, empresa_norm, titulo, perfil, cv_version_id, origem,
       enviada_em, status, teve_avanco, respondida_em, atualizada_em FROM candidaturas;
DROP TABLE candidaturas;
ALTER TABLE candidaturas_007 RENAME TO candidaturas;
CREATE UNIQUE INDEX IF NOT EXISTS idx_cand_job ON candidaturas (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cand_empresa ON candidaturas (empresa_norm);
CREATE TABLE emails_007 (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id         TEXT NOT NULL UNIQUE,
    recebido_em      TEXT NOT NULL,
    de               TEXT NOT NULL,
    assunto          TEXT NOT NULL,
    corpo            TEXT,
    categoria_jev    TEXT,
    prob_categoria   REAL,
    prob_processo    REAL,
    prob_prazo       REAL,
    final            TEXT NOT NULL CHECK (final IN
                     ('avanco','pendencia','inscricao_confirmada','reprovado','revisar','outro')),
    rotulo_manual    TEXT CHECK (rotulo_manual IS NULL OR rotulo_manual IN
                     ('avanco','pendencia','inscricao_confirmada','reprovado','outro')),
    empresa_extraida TEXT,
    candidatura_id   INTEGER REFERENCES candidaturas(id) ON DELETE SET NULL,
    latencia_ms      INTEGER,
    entrevista_em    TEXT,
    processado_em    TEXT NOT NULL
);
INSERT INTO emails_007 (id, gmail_id, recebido_em, de, assunto, corpo, categoria_jev, prob_categoria,
                        prob_processo, prob_prazo, final, rotulo_manual, empresa_extraida,
                        candidatura_id, latencia_ms, processado_em)
SELECT id, gmail_id, recebido_em, de, assunto, corpo, categoria_jev, prob_categoria,
       prob_processo, prob_prazo, final, rotulo_manual, empresa_extraida,
       candidatura_id, latencia_ms, processado_em FROM emails;
DROP TABLE emails;
ALTER TABLE emails_007 RENAME TO emails;
CREATE INDEX IF NOT EXISTS idx_emails_cand ON emails (candidatura_id);
COMMIT;
PRAGMA foreign_keys = ON;
