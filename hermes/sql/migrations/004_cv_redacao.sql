-- 004: `cv_versions` guarda a redação do modelo (resumo + bullets, JSON). Reaproveitar uma versão
-- passa a remontar o currículo com o cabeçalho atual do vault sem chamar o modelo de novo.
-- Recria a tabela pelo mesmo motivo da 003: num banco novo o schema.sql já tem a coluna.
BEGIN;
CREATE TABLE cv_versions_004 (
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
    conteudo     TEXT,
    redacao      TEXT
);
INSERT INTO cv_versions_004 (id, job_id, idioma, caminho, fatos, model, cost_usd, criado_em,
                             perfil, selecao_hash, palavras, conteudo)
SELECT id, job_id, idioma, caminho, fatos, model, cost_usd, criado_em,
       perfil, selecao_hash, palavras, conteudo FROM cv_versions;
DROP TABLE cv_versions;
ALTER TABLE cv_versions_004 RENAME TO cv_versions;
CREATE INDEX IF NOT EXISTS idx_cv_hash ON cv_versions (selecao_hash);
CREATE INDEX IF NOT EXISTS idx_cv_perfil ON cv_versions (perfil, criado_em DESC);
COMMIT;
