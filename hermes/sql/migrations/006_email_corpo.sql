-- 006: `emails` guarda o corpo (texto limpo) para a tela de candidaturas mostrar o que a empresa
-- escreveu. Recria a tabela pelo mesmo motivo da 003: num banco novo o schema.sql já tem a coluna.
-- E-mails gravados antes ficam com corpo NULL até `hermes email corpos` buscar no Gmail.
BEGIN;
CREATE TABLE emails_006 (
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
    processado_em    TEXT NOT NULL
);
INSERT INTO emails_006 (id, gmail_id, recebido_em, de, assunto, categoria_jev, prob_categoria,
                        prob_processo, prob_prazo, final, rotulo_manual, empresa_extraida,
                        candidatura_id, latencia_ms, processado_em)
SELECT id, gmail_id, recebido_em, de, assunto, categoria_jev, prob_categoria,
       prob_processo, prob_prazo, final, rotulo_manual, empresa_extraida,
       candidatura_id, latencia_ms, processado_em FROM emails;
DROP TABLE emails;
ALTER TABLE emails_006 RENAME TO emails;
CREATE INDEX IF NOT EXISTS idx_emails_cand ON emails (candidatura_id);
COMMIT;
