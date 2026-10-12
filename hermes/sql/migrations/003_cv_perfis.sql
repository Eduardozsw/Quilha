-- 003: `cv_versions` ganha perfil, hash da seleção, palavras e o conteúdo gerado (galeria por perfil).
-- Recria a tabela em vez de ALTER: num banco novo o schema.sql já criou a versão nova, e a cópia
-- é inofensiva — um ALTER ADD COLUMN falharia ali com coluna duplicada.
BEGIN;
CREATE TABLE cv_versions_003 (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    INTEGER REFERENCES jobs(id) ON DELETE SET NULL,  -- NULL = currículo base
    idioma    TEXT NOT NULL CHECK (idioma IN ('pt','en')),
    caminho   TEXT NOT NULL,
    fatos     TEXT NOT NULL DEFAULT '[]',  -- JSON: ["nota.md#block-id", ...]
    model     TEXT,
    cost_usd  REAL,
    criado_em TEXT NOT NULL,
    perfil       TEXT,
    selecao_hash TEXT,
    palavras     INTEGER CHECK (palavras IS NULL OR palavras >= 0),
    conteudo     TEXT
);
INSERT INTO cv_versions_003 (id, job_id, idioma, caminho, fatos, model, cost_usd, criado_em)
SELECT id, job_id, idioma, caminho, fatos, model, cost_usd, criado_em FROM cv_versions;
DROP TABLE cv_versions;
ALTER TABLE cv_versions_003 RENAME TO cv_versions;
CREATE INDEX IF NOT EXISTS idx_cv_hash ON cv_versions (selecao_hash);
CREATE INDEX IF NOT EXISTS idx_cv_perfil ON cv_versions (perfil, criado_em DESC);
COMMIT;
