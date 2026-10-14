import sqlite3

import pytest

from hermes.db import store
from hermes.run_status import RunStatus


def test_schema_aplicado_e_idempotente(conn):
    tabelas = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"facts", "competencies", "evidence", "jobs", "runs"} <= tabelas
    store.apply_schema(conn)  # rodar de novo não quebra
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION


def test_migracao_002_aceita_gupy_e_preserva_a_fila(tmp_path):
    """Banco da versão 1: `fila_coleta` com o CHECK antigo e uma fonte na fila."""
    caminho = tmp_path / "v1.db"
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "CREATE TABLE fila_coleta (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " fonte TEXT NOT NULL CHECK (fonte IN ('greenhouse','lever')), board TEXT NOT NULL,"
        " estado TEXT NOT NULL DEFAULT 'pendente', tentativas INTEGER NOT NULL DEFAULT 0,"
        " proximo_em TEXT NOT NULL, ultima_ok_em TEXT, ultimo_erro TEXT,"
        " atualizado_em TEXT NOT NULL, UNIQUE (fonte, board));"
        "INSERT INTO fila_coleta (fonte, board, tentativas, proximo_em, atualizado_em)"
        " VALUES ('lever', 'beta', 3, '2026-09-22', '2026-09-22');"
        "PRAGMA user_version = 1;"
    )
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    assert tuple(conn.execute("SELECT fonte, board, tentativas FROM fila_coleta").fetchone()) == (
        "lever", "beta", 3)
    conn.execute("INSERT INTO fila_coleta (fonte, board, proximo_em, atualizado_em)"
                 " VALUES ('gupy', 'gama', '2026-09-23', '2026-09-23')")
    conn.close()


def test_migracao_003_preserva_os_curriculos_e_abre_espaco_para_perfil(tmp_path):
    """Banco da versão 2: `cv_versions` sem perfil nem conteúdo, com uma versão gravada."""
    caminho = tmp_path / "v2.db"
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "CREATE TABLE cv_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER,"
        " idioma TEXT NOT NULL CHECK (idioma IN ('pt','en')), caminho TEXT NOT NULL,"
        " fatos TEXT NOT NULL DEFAULT '[]', model TEXT, cost_usd REAL, criado_em TEXT NOT NULL);"
        "INSERT INTO cv_versions (idioma, caminho, criado_em) VALUES ('pt', 'out/cv-pt.md', '2026-09-20');"
        "PRAGMA user_version = 2;"
    )
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    linha = conn.execute("SELECT idioma, caminho, perfil, conteudo FROM cv_versions").fetchone()
    assert tuple(linha) == ("pt", "out/cv-pt.md", None, None)
    indices = {r[1] for r in conn.execute("PRAGMA index_list('cv_versions')")}
    assert {"idx_cv_hash", "idx_cv_perfil"} <= indices
    conn.close()


def test_migracao_004_preserva_a_galeria_e_abre_espaco_para_a_redacao(tmp_path):
    """Banco da versão 3: versão com conteúdo e hash, ainda sem a redação guardada."""
    caminho = tmp_path / "v3.db"
    store.connect(caminho).close()
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "DROP TABLE cv_versions;"
        "CREATE TABLE cv_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER,"
        " idioma TEXT NOT NULL, caminho TEXT NOT NULL, fatos TEXT NOT NULL DEFAULT '[]', model TEXT,"
        " cost_usd REAL, criado_em TEXT NOT NULL, perfil TEXT, selecao_hash TEXT, palavras INTEGER,"
        " conteudo TEXT);"
        "INSERT INTO cv_versions (idioma, caminho, criado_em, perfil, selecao_hash, conteudo)"
        " VALUES ('pt', 'out/cv-pt.md', '2026-09-27', 'engenharia-ia', 'abc', '# CV');"
        "PRAGMA user_version = 3;"
    )
    antigo.close()

    conn = store.connect(caminho)
    linha = conn.execute("SELECT perfil, selecao_hash, conteudo, redacao FROM cv_versions").fetchone()
    assert tuple(linha) == ("engenharia-ia", "abc", "# CV", None)
    conn.close()


def test_migracao_007_abre_a_etapa_entrevista_sem_perder_os_emails_ligados(tmp_path):
    """Banco da versão 6: `candidaturas` com o CHECK antigo e um e-mail ligado a ela."""
    caminho = tmp_path / "v6.db"
    store.connect(caminho).close()
    antigo = sqlite3.connect(caminho)  # foreign_keys desligado aqui, como o sqlite3 abre por padrão
    antigo.executescript(
        "DROP TABLE candidaturas;"
        "CREATE TABLE candidaturas (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL, empresa TEXT, empresa_norm TEXT, titulo TEXT,"
        " perfil TEXT, cv_version_id INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,"
        " origem TEXT NOT NULL CHECK (origem IN ('cv','email','manual')), enviada_em TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'enviada' CHECK (status IN ('enviada','em_processo','reprovada','cancelada')),"
        " teve_avanco INTEGER NOT NULL DEFAULT 0 CHECK (teve_avanco IN (0,1)), respondida_em TEXT,"
        " atualizada_em TEXT NOT NULL);"
        "INSERT INTO candidaturas (empresa, empresa_norm, titulo, origem, enviada_em, status, teve_avanco,"
        " atualizada_em) VALUES ('Orla Tech', 'orla tech', 'Dev React', 'manual', '2026-10-01', 'em_processo', 1,"
        " '2026-10-02');"
        "INSERT INTO emails (gmail_id, recebido_em, de, assunto, corpo, final, rotulo_manual, candidatura_id,"
        " processado_em) VALUES ('m1', '2026-10-02', 'rh@orla.example', 'Próxima etapa', 'Olá, vamos seguir.',"
        " 'avanco', 'avanco', 1, '2026-10-02');"
        "PRAGMA user_version = 6;"
    )
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    c = conn.execute("SELECT empresa, status, teve_avanco, entrevista_em FROM candidaturas").fetchone()
    assert tuple(c) == ("Orla Tech", "em_processo", 1, None)
    assert tuple(conn.execute("SELECT candidatura_id, entrevista_em, corpo, rotulo_manual FROM emails"
                              " WHERE gmail_id = 'm1'").fetchone()) == (1, None, "Olá, vamos seguir.", "avanco")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    novo = store.connect(tmp_path / "novo.db")
    indices_emails = lambda c: {r[1] for r in c.execute("PRAGMA index_list('emails')") if not r[1].startswith("sqlite_")}
    assert indices_emails(conn) == indices_emails(novo)  # a tabela recriada tem os mesmos índices de um banco novo
    novo.close()
    indices = {r[1] for r in conn.execute("PRAGMA index_list('candidaturas')")}
    assert {"idx_cand_job", "idx_cand_empresa"} <= indices
    conn.execute("UPDATE candidaturas SET status = 'entrevista' WHERE id = 1")  # o CHECK novo aceita
    conn.close()


def test_migracao_009_abre_a_enviar_sem_perder_emails(tmp_path):
    """Banco da versão 8: `candidaturas` sem `a_enviar`, com e-mail ligado e entrevista marcada."""
    caminho = tmp_path / "v8.db"
    store.connect(caminho).close()
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "DROP TABLE candidaturas;"
        "CREATE TABLE candidaturas (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL, empresa TEXT, empresa_norm TEXT, titulo TEXT,"
        " perfil TEXT, cv_version_id INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,"
        " origem TEXT NOT NULL CHECK (origem IN ('cv','email','manual')), enviada_em TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'enviada'"
        " CHECK (status IN ('enviada','em_processo','entrevista','reprovada','cancelada')),"
        " teve_avanco INTEGER NOT NULL DEFAULT 0 CHECK (teve_avanco IN (0,1)), respondida_em TEXT,"
        " entrevista_em TEXT, atualizada_em TEXT NOT NULL);"
        "CREATE UNIQUE INDEX idx_cand_job ON candidaturas (job_id) WHERE job_id IS NOT NULL;"
        "CREATE INDEX idx_cand_empresa ON candidaturas (empresa_norm);"
        "INSERT INTO candidaturas (empresa, empresa_norm, titulo, origem, enviada_em, status, teve_avanco,"
        " entrevista_em, atualizada_em) VALUES ('Orla Tech', 'orla tech', 'Dev React', 'manual', '2026-10-01',"
        " 'entrevista', 1, '2026-10-11T14:00:00-03:00', '2026-10-02');"
        "INSERT INTO emails (gmail_id, recebido_em, de, assunto, final, candidatura_id, processado_em)"
        " VALUES ('m1', '2026-10-02', 'rh@orla.example', 'Próxima etapa', 'avanco', 1, '2026-10-02');"
        "PRAGMA user_version = 8;"
    )
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    c = conn.execute("SELECT empresa, status, teve_avanco, entrevista_em, entrevista_titulo, roteiro, roteiro_em"
                     " FROM candidaturas").fetchone()
    assert tuple(c) == ("Orla Tech", "entrevista", 1, "2026-10-11T14:00:00-03:00", None, None, None)
    assert conn.execute("SELECT candidatura_id FROM emails WHERE gmail_id = 'm1'").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    indices = {r[1] for r in conn.execute("PRAGMA index_list('candidaturas')")}
    assert {"idx_cand_job", "idx_cand_empresa"} <= indices
    conn.execute("UPDATE candidaturas SET status = 'a_enviar' WHERE id = 1")  # o CHECK novo aceita
    conn.close()


def test_migracao_008_guarda_a_estrutura_do_curriculo_sem_perder_versoes(tmp_path):
    """Banco da versão 7: `cv_versions` sem `estrutura`, com uma versão ligada a uma candidatura."""
    caminho = tmp_path / "v7.db"
    store.connect(caminho).close()
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "DROP TABLE cv_versions;"
        "CREATE TABLE cv_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, idioma TEXT NOT NULL,"
        " caminho TEXT NOT NULL, fatos TEXT NOT NULL DEFAULT '[]', model TEXT, cost_usd REAL, criado_em TEXT NOT NULL,"
        " perfil TEXT, selecao_hash TEXT, palavras INTEGER, conteudo TEXT, redacao TEXT);"
        "INSERT INTO cv_versions (idioma, caminho, criado_em, conteudo) VALUES ('pt', 'out/cv-pt.md', '2026-10-01', '# CV');"
        "INSERT INTO candidaturas (empresa, origem, enviada_em, cv_version_id, atualizada_em)"
        " VALUES ('Orla Tech', 'cv', '2026-10-01', 1, '2026-10-01');"
        "PRAGMA user_version = 7;"
    )
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    assert tuple(conn.execute("SELECT conteudo, estrutura FROM cv_versions").fetchone()) == ("# CV", None)
    assert conn.execute("SELECT cv_version_id FROM candidaturas").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    indices = {r[1] for r in conn.execute("PRAGMA index_list('cv_versions')")}
    assert {"idx_cv_hash", "idx_cv_perfil"} <= indices
    conn.close()


def test_queries_sql_roda_inteiro(conn):
    """As consultas de operação precisam rodar mesmo com o banco vazio."""
    bruto = (store.SQL_DIR / "queries.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in bruto.splitlines() if not l.startswith("."))
    conn.executescript(sql)


def test_foreign_keys_ligadas(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO evidence (competency_id, nota, block_id, forca, criado_em)"
            " VALUES (999, 'n.md', 'b', 1, '2026-01-01T00:00:00+00:00')"
        )


def test_check_constraint_de_nivel(conn):
    conn.execute(
        "INSERT INTO competencies (slug, nome, categoria, criado_em)"
        " VALUES ('python', 'Python', 'linguagem', '2026-01-01T00:00:00+00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO competency_state (competency_id, nivel, justificativa, origem, criado_em)"
            " VALUES (1, 9, 'x', 'declarado', '2026-01-01T00:00:00+00:00')"
        )


def _fato(block_id="pipeline"):
    return {
        "nota": "Carreira/Projetos/Mirante.md",
        "block_id": block_id,
        "tipo": "project",
        "entidade": "mirante",
        "texto": "Pipeline batch diário",
        "tags": ["python"],
    }


def test_reindex_substitui_tudo(conn):
    assert store.reindex_facts(conn, [_fato(), _fato("operacao")]) == 2
    assert store.reindex_facts(conn, [_fato()]) == 1
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_reindex_com_erro_faz_rollback(conn):
    store.reindex_facts(conn, [_fato()])
    ruim = _fato("operacao")
    ruim["tipo"] = "inexistente"  # viola o CHECK
    with pytest.raises(sqlite3.IntegrityError):
        store.reindex_facts(conn, [_fato(), ruim])
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_evidencia_orfa_aparece_e_sobrevive_ao_reindex(conn):
    conn.execute(
        "INSERT INTO competencies (slug, nome, categoria, criado_em)"
        " VALUES ('python', 'Python', 'linguagem', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO evidence (competency_id, nota, block_id, forca, criado_em)"
        " VALUES (1, 'Carreira/Projetos/Mirante.md', 'sumiu', 2, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    store.reindex_facts(conn, [_fato()])
    orfas = store.orphan_evidence(conn)
    assert len(orfas) == 1 and orfas[0]["block_id"] == "sumiu"
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1


def test_record_run_grava_custo_nulo_quando_desconhecido(conn):
    status = RunStatus()
    status.record_usage(10, 5, None)
    run_id = store.record_run(conn, "index", store.utcnow(), status, "partial")
    linha = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert linha["cost_usd"] is None
    assert linha["prompt_tokens"] == 10
    assert linha["comando"] == "index"


def test_migracao_005_cria_candidaturas_e_emails(tmp_path):
    """Banco da versão 4 ganha as duas tabelas; banco novo já nasce com elas."""
    caminho = tmp_path / "v4.db"
    antigo = sqlite3.connect(caminho)
    antigo.executescript("PRAGMA user_version = 4;")
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    colunas = {r["name"] for r in conn.execute("PRAGMA table_info(candidaturas)")}
    assert {"job_id", "empresa_norm", "perfil", "cv_version_id", "origem", "enviada_em",
            "status", "teve_avanco", "respondida_em"} <= colunas
    colunas = {r["name"] for r in conn.execute("PRAGMA table_info(emails)")}
    assert {"gmail_id", "recebido_em", "final", "rotulo_manual", "empresa_extraida",
            "candidatura_id", "prob_prazo"} <= colunas
    conn.close()


def test_migracao_006_guarda_o_corpo_e_preserva_os_emails(tmp_path):
    """Banco da versão 5: e-mails ligados e rotulados, sem corpo. Tudo fica; o corpo nasce NULL."""
    caminho = tmp_path / "v5.db"
    store.connect(caminho).close()
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "DROP TABLE emails;"
        "CREATE TABLE emails (id INTEGER PRIMARY KEY AUTOINCREMENT, gmail_id TEXT NOT NULL UNIQUE,"
        " recebido_em TEXT NOT NULL, de TEXT NOT NULL, assunto TEXT NOT NULL, categoria_jev TEXT,"
        " prob_categoria REAL, prob_processo REAL, prob_prazo REAL, final TEXT NOT NULL,"
        " rotulo_manual TEXT, empresa_extraida TEXT, candidatura_id INTEGER, latencia_ms INTEGER,"
        " processado_em TEXT NOT NULL);"
        "INSERT INTO candidaturas (empresa, origem, enviada_em, atualizada_em)"
        " VALUES ('Áureo', 'email', '2026-09-23', '2026-09-23');"
        "INSERT INTO emails (gmail_id, recebido_em, de, assunto, final, rotulo_manual, candidatura_id,"
        " processado_em) VALUES ('g1', '2026-09-23', 'rh@aureo', 'Queremos te conhecer', 'avanco', 'avanco',"
        " 1, '2026-09-23');"
        "PRAGMA user_version = 5;"
    )
    antigo.close()

    conn = store.connect(caminho)
    linha = conn.execute("SELECT gmail_id, assunto, rotulo_manual, candidatura_id, corpo FROM emails").fetchone()
    assert tuple(linha) == ("g1", "Queremos te conhecer", "avanco", 1, None)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    conn.close()


def test_emails_gmail_id_e_unico(conn):
    sql = ("INSERT INTO emails (gmail_id, recebido_em, de, assunto, final, processado_em)"
           " VALUES ('a', '2026-09-01', 'x', 'y', 'outro', '2026-09-01')")
    conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


def test_migracao_010_abre_titulo_e_meta_sem_perder_a_conversa(tmp_path):
    """Banco da versão 9: `agent_sessions` sem `titulo`, `agent_messages` sem `meta`, com uma conversa."""
    caminho = tmp_path / "v9.db"
    store.connect(caminho).close()
    antigo = sqlite3.connect(caminho)
    antigo.executescript(
        "DROP TABLE agent_messages; DROP TABLE agent_sessions;"
        "CREATE TABLE agent_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,"
        " finished_at TEXT, model TEXT, cost_usd REAL, resumo TEXT);"
        "CREATE TABLE agent_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id INTEGER NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE, idx INTEGER NOT NULL,"
        " role TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')), content TEXT, tool_calls TEXT,"
        " tool_call_id TEXT, criado_em TEXT NOT NULL, UNIQUE (session_id, idx));"
        "INSERT INTO agent_sessions (started_at, model, cost_usd) VALUES ('2026-10-01', 'gpt-4o-mini', 0.01);"
        "INSERT INTO agent_messages (session_id, idx, role, content, criado_em) VALUES (1, 0, 'user', 'oi', '2026-10-01');"
        "INSERT INTO agent_messages (session_id, idx, role, content, criado_em) VALUES (1, 1, 'assistant', 'olá', '2026-10-01');"
        "INSERT INTO runs (started_at, comando, status, session_id) VALUES ('2026-10-01', 'chat', 'success', 1);"
        "PRAGMA user_version = 9;"
    )
    antigo.close()

    conn = store.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION == 10
    s = conn.execute("SELECT model, cost_usd, titulo FROM agent_sessions WHERE id = 1").fetchone()
    assert tuple(s) == ("gpt-4o-mini", 0.01, None)
    msgs = conn.execute("SELECT role, content, meta FROM agent_messages ORDER BY idx").fetchall()
    assert [tuple(m) for m in msgs] == [("user", "oi", None), ("assistant", "olá", None)]
    assert conn.execute("SELECT session_id FROM runs").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.execute("DELETE FROM agent_sessions WHERE id = 1")  # o CASCADE continua valendo
    assert conn.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0] == 0
    conn.close()


def test_escrita_nao_espera_leitura_aberta_em_outro_processo(tmp_path):
    """App e servidor MCP abrem o mesmo banco: uma leitura em curso não pode travar a gravação do outro."""
    caminho = tmp_path / "hermes.db"
    leitor = store.connect(caminho)
    escritor = store.connect(caminho)
    escritor.execute("PRAGMA busy_timeout = 200")  # sem WAL, falharia em 200 ms em vez de esperar 5 s
    leitor.execute("BEGIN")
    leitor.execute("SELECT count(*) FROM facts").fetchone()
    store.reindex_facts(escritor, [{"nota": "a.md", "block_id": "x", "tipo": "project",
                                    "entidade": "a", "texto": "t"}])
    leitor.rollback()
    assert leitor.execute("SELECT count(*) FROM facts").fetchone()[0] == 1


def test_banco_em_wal_com_espera(tmp_path):
    conn = store.connect(tmp_path / "hermes.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
