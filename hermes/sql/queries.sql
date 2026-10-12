-- Métricas operacionais do Hermes.
-- Uso: sqlite3 data/hermes.db < sql/queries.sql
.headers on
.mode column

-- 1. O que o vault entregou no último `hermes index`
SELECT tipo, COUNT(DISTINCT nota) AS notas, COUNT(*) AS fatos, MAX(indexado_em) AS indexado_em
FROM facts
GROUP BY tipo;

-- 2. Competências: nível vigente, evidências e o que ainda é lacuna
SELECT slug, nome, categoria, peso,
       COALESCE(nivel, 0)       AS nivel,
       n_evidencias,
       CASE
           WHEN nivel IS NULL      THEN 'nunca avaliada'
           WHEN n_evidencias = 0   THEN 'sem evidencia'
           WHEN nivel >= 3 AND n_evidencias < 2 THEN 'evidencia insuficiente'
           ELSE 'ok'
       END                      AS situacao
FROM v_competency_current
ORDER BY peso DESC, nivel ASC, slug;

-- 3. Evidências órfãs: o block id citado sumiu do vault (o índice é descartável, a evidência não)
SELECT e.id, c.slug, e.nota, e.block_id, e.criado_em
FROM evidence e
JOIN competencies c ON c.id = e.competency_id
LEFT JOIN facts f ON f.nota = e.nota AND f.block_id = e.block_id
WHERE f.nota IS NULL;

-- 4. Vagas por status, com o score da avaliação mais recente
SELECT j.id, j.empresa, j.titulo, j.status, j.coletado_em,
       (SELECT score FROM job_matches m WHERE m.job_id = j.id
        ORDER BY criado_em DESC, id DESC LIMIT 1) AS score
FROM jobs j
ORDER BY j.coletado_em DESC
LIMIT 20;

-- 5. Requisitos que nenhuma competência cobre, por frequência entre as vagas
SELECT r.texto, COUNT(*) AS vezes, SUM(r.tipo = 'obrigatorio') AS obrigatorio
FROM job_requirements r
WHERE r.competency_id IS NULL
GROUP BY LOWER(r.texto)
ORDER BY vezes DESC, obrigatorio DESC
LIMIT 15;

-- 6. Estudo declarado por semana, contra o plano da semana
-- Semana ISO (igual a study_plan.semana) pela quinta-feira da semana: funciona em qualquer SQLite,
-- ao contrário de strftime('%G-W%V'), que só existe a partir da 3.46 e devolve NULL antes dela.
WITH sessoes AS (
    SELECT s.*, date(s.data, '-3 days', 'weekday 4') AS quinta FROM study_sessions s
), semanas AS (
    SELECT printf('%s-W%02d', strftime('%Y', quinta),
                  (CAST(strftime('%j', quinta) AS INTEGER) - 1) / 7 + 1) AS semana,
           minutos
    FROM sessoes
)
SELECT semana,
       COUNT(*)                                         AS sessoes,
       SUM(minutos)                                     AS minutos,
       (SELECT SUM(i.minutos_alvo) FROM plan_items i
        JOIN study_plan p ON p.id = i.plan_id
        WHERE p.semana = semanas.semana)                AS minutos_alvo
FROM semanas
GROUP BY semana
ORDER BY semana DESC
LIMIT 8;

-- 7. Commits que o agente ainda não te perguntou (sinal, nunca estudo)
SELECT data, repo, substr(ref, 1, 7) AS sha, resumo, estado
FROM activity_signals
WHERE estado IN ('novo', 'perguntado')
ORDER BY data DESC, id DESC
LIMIT 20;

-- 8. Custo e uso por comando. Execuções com cost_usd NULL ficam fora das somas e são contadas à parte.
SELECT comando,
       COUNT(*)                                         AS n_runs,
       SUM(status = 'success')                          AS success,
       SUM(status = 'partial')                          AS partial,
       SUM(status = 'failed')                           AS failed,
       SUM(llm_calls)                                   AS llm_calls,
       SUM(tool_errors)                                 AS tool_errors,
       COUNT(cost_usd)                                  AS runs_priced,
       SUM(cost_usd IS NULL)                            AS runs_unpriced,
       ROUND(SUM(cost_usd), 4)                          AS total_cost_usd
FROM runs
GROUP BY comando
ORDER BY n_runs DESC;

-- 9. Últimas 10 execuções
SELECT id, started_at, comando, status,
       ROUND((julianday(finished_at) - julianday(started_at)) * 86400, 1) AS duracao_s,
       llm_calls, tool_calls, tool_errors, ROUND(cost_usd, 6) AS cost_usd, error
FROM runs
ORDER BY started_at DESC, id DESC
LIMIT 10;

-- 10. Coletas por execução: vagas novas por fonte, e o run correspondente
SELECT c.execucao, r.status AS run_status, c.fonte, c.board, c.status,
       c.vagas_vistas, c.vagas_filtradas, c.vagas_novas, c.duplicadas, c.duracao_ms, c.erro
FROM coletas c
LEFT JOIN runs r ON r.started_at = c.execucao AND r.comando = 'job collect'
ORDER BY c.execucao DESC, c.fonte, c.board
LIMIT 30;

-- 11. Fila do coletor: fontes com falhas seguidas e quando serão tentadas de novo
SELECT fonte, board, estado, tentativas, proximo_em, ultima_ok_em, ultimo_erro
FROM fila_coleta
ORDER BY tentativas DESC, proximo_em;
