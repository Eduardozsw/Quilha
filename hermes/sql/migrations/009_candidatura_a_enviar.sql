-- 009: etapa `a_enviar` (currículo gerado, ainda não mandado) e, na candidatura, o título da entrevista
-- (`entrevista_titulo`) e o roteiro de preparo salvo (`roteiro`, JSON, gerado em `roteiro_em`). Recria a
-- tabela porque o SQLite não altera CHECK; chaves estrangeiras desligadas na troca, como na 007, para o
-- DROP TABLE não apagar a ligação dos e-mails (ON DELETE SET NULL).
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE candidaturas_009 (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    empresa           TEXT,
    empresa_norm      TEXT,
    titulo            TEXT,
    perfil            TEXT,
    cv_version_id     INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,
    origem            TEXT NOT NULL CHECK (origem IN ('cv','email','manual')),
    enviada_em        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'enviada'
                      CHECK (status IN ('a_enviar','enviada','em_processo','entrevista','reprovada','cancelada')),
    teve_avanco       INTEGER NOT NULL DEFAULT 0 CHECK (teve_avanco IN (0,1)),
    respondida_em     TEXT,
    entrevista_em     TEXT,
    entrevista_titulo TEXT,
    roteiro           TEXT,
    roteiro_em        TEXT,
    atualizada_em     TEXT NOT NULL
);
INSERT INTO candidaturas_009 (id, job_id, empresa, empresa_norm, titulo, perfil, cv_version_id, origem,
                              enviada_em, status, teve_avanco, respondida_em, entrevista_em, atualizada_em)
SELECT id, job_id, empresa, empresa_norm, titulo, perfil, cv_version_id, origem,
       enviada_em, status, teve_avanco, respondida_em, entrevista_em, atualizada_em FROM candidaturas;
DROP TABLE candidaturas;
ALTER TABLE candidaturas_009 RENAME TO candidaturas;
CREATE UNIQUE INDEX IF NOT EXISTS idx_cand_job ON candidaturas (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cand_empresa ON candidaturas (empresa_norm);
COMMIT;
PRAGMA foreign_keys = ON;
