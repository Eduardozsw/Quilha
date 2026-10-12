-- 002: `fila_coleta.fonte` passa a aceitar 'gupy'. O SQLite não altera CHECK: recria a tabela.
-- Num banco novo o schema.sql já criou a versão nova, e a cópia é inofensiva.
BEGIN;
CREATE TABLE fila_coleta_002 (
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
INSERT INTO fila_coleta_002
    (id, fonte, board, estado, tentativas, proximo_em, ultima_ok_em, ultimo_erro, atualizado_em)
SELECT id, fonte, board, estado, tentativas, proximo_em, ultima_ok_em, ultimo_erro, atualizado_em
FROM fila_coleta;
DROP TABLE fila_coleta;
ALTER TABLE fila_coleta_002 RENAME TO fila_coleta;
COMMIT;
