-- 010: a Conversa da V3 guarda o título editado da sessão (`agent_sessions.titulo`; NULL = a primeira
-- pergunta cortada) e, por mensagem, o que a tela precisa para remontar o fio (`agent_messages.meta`, JSON:
-- custo, cartões, confirmações, ferramentas, parado). Recria as duas tabelas pelo mesmo motivo da 008 (num
-- banco novo o schema.sql já tem as colunas, e ADD COLUMN repetido falha) e com as chaves estrangeiras
-- desligadas, como na 007: o DROP de `agent_sessions` soltaria `runs.session_id` e apagaria as mensagens.
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE agent_sessions_010 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    model       TEXT,
    cost_usd    REAL,
    resumo      TEXT,
    titulo      TEXT
);
INSERT INTO agent_sessions_010 (id, started_at, finished_at, model, cost_usd, resumo)
SELECT id, started_at, finished_at, model, cost_usd, resumo FROM agent_sessions;
CREATE TABLE agent_messages_010 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content      TEXT,
    tool_calls   TEXT,
    tool_call_id TEXT,
    criado_em    TEXT NOT NULL,
    meta         TEXT,
    UNIQUE (session_id, idx)
);
INSERT INTO agent_messages_010 (id, session_id, idx, role, content, tool_calls, tool_call_id, criado_em)
SELECT id, session_id, idx, role, content, tool_calls, tool_call_id, criado_em FROM agent_messages;
DROP TABLE agent_messages;
DROP TABLE agent_sessions;
ALTER TABLE agent_sessions_010 RENAME TO agent_sessions;
ALTER TABLE agent_messages_010 RENAME TO agent_messages;
COMMIT;
PRAGMA foreign_keys = ON;
