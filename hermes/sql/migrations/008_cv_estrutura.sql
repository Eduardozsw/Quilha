-- 008: `cv_versions` guarda a estrutura do currículo (JSON de `curriculo.estruturar`): a tela Currículos
-- desenha a página e a fonte de cada linha a partir dela, e o PDF compila dela. O `cv-<idioma>.json`
-- do disco só guarda a última geração de cada recorte. Recria a tabela pelo mesmo motivo da 004 (num
-- banco novo o schema.sql já tem a coluna) e com as chaves estrangeiras desligadas, pelo mesmo motivo
-- da 007: `candidaturas.cv_version_id` perderia a ligação no DROP.
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE cv_versions_008 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    idioma       TEXT NOT NULL CHECK (idioma IN ('pt','en')),
    caminho      TEXT NOT NULL,
    fatos        TEXT NOT NULL DEFAULT '[]',
    model        TEXT,
    cost_usd     REAL,
    criado_em    TEXT NOT NULL,
    perfil       TEXT,
    selecao_hash TEXT,
    palavras     INTEGER CHECK (palavras IS NULL OR palavras >= 0),
    conteudo     TEXT,
    redacao      TEXT,
    estrutura    TEXT
);
INSERT INTO cv_versions_008 (id, job_id, idioma, caminho, fatos, model, cost_usd, criado_em,
                             perfil, selecao_hash, palavras, conteudo, redacao)
SELECT id, job_id, idioma, caminho, fatos, model, cost_usd, criado_em,
       perfil, selecao_hash, palavras, conteudo, redacao FROM cv_versions;
DROP TABLE cv_versions;
ALTER TABLE cv_versions_008 RENAME TO cv_versions;
CREATE INDEX IF NOT EXISTS idx_cv_hash ON cv_versions (selecao_hash);
CREATE INDEX IF NOT EXISTS idx_cv_perfil ON cv_versions (perfil, criado_em DESC);
COMMIT;
PRAGMA foreign_keys = ON;
