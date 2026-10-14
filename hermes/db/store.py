"""Acesso ao SQLite do Hermes. sqlite3 puro, sem ORM.

`hermes/sql/schema.sql` é sempre o estado atual do banco e é idempotente. Mudança
destrutiva vira `hermes/sql/migrations/00N_descricao.sql`, aplicada quando
`PRAGMA user_version` < N.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from hermes.run_status import RunStatus

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
SCHEMA_PATH = SQL_DIR / "schema.sql"
MIGRATIONS_DIR = SQL_DIR / "migrations"
SCHEMA_VERSION = 10


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path, *, uma_thread: bool = True) -> sqlite3.Connection:
    """`uma_thread=False` para a API: o FastAPI abre a conexão numa thread e usa em outra,
    sempre em sequência dentro do mesmo request (nunca duas threads ao mesmo tempo)."""
    caminho = Path(db_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho, check_same_thread=uma_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # o SQLite não liga sozinho
    # app, CLI e servidor MCP abrem o mesmo arquivo: em WAL, leitura em curso não trava a gravação do outro
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    apply_schema(conn)
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _apply_migrations(conn)
    conn.commit()


def _apply_migrations(conn: sqlite3.Connection) -> None:
    versao = conn.execute("PRAGMA user_version").fetchone()[0]
    alvo = SCHEMA_VERSION
    if MIGRATIONS_DIR.is_dir():
        for arquivo in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
            numero = int(arquivo.name.split("_")[0])
            if numero > versao:
                conn.executescript(arquivo.read_text(encoding="utf-8"))
                versao = numero
            alvo = max(alvo, numero)
    if versao < alvo:
        versao = alvo
    # PRAGMA não aceita parâmetro; `versao` é int validado acima.
    conn.execute(f"PRAGMA user_version = {int(versao)}")


def reindex_facts(conn: sqlite3.Connection, facts: Iterable[dict]) -> int:
    """Apaga e reconstrói `facts` numa transação. Nada mais é tocado."""
    agora = utcnow()
    linhas = [
        (f["nota"], f["block_id"], f["tipo"], f["entidade"], f["texto"],
         json.dumps(f.get("tags", []), ensure_ascii=False), agora)
        for f in facts
    ]
    with conn:  # commit no sucesso, rollback na exceção
        conn.execute("DELETE FROM facts")
        conn.executemany(
            "INSERT INTO facts (nota, block_id, tipo, entidade, texto, tags, indexado_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            linhas,
        )
    return len(linhas)


ORPHAN_EVIDENCE_SQL = """
SELECT e.id, c.slug, e.nota, e.block_id, e.criado_em
FROM evidence e
JOIN competencies c ON c.id = e.competency_id
LEFT JOIN facts f ON f.nota = e.nota AND f.block_id = e.block_id
WHERE f.nota IS NULL
ORDER BY e.nota, e.block_id
"""


def orphan_evidence(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in conn.execute(ORPHAN_EVIDENCE_SQL)]


def backup(conn: sqlite3.Connection, destino: str | Path, manter: int = 10,
           sufixo: str = "") -> Path:
    """Cópia consistente do banco (API de backup do SQLite, segura com o banco aberto).

    Evidência e nível só existem aqui — o índice de fatos se reconstrói do vault, eles não.
    Guarda as `manter` cópias mais recentes em `destino` e apaga as mais antigas.
    """
    pasta = Path(destino).expanduser()
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    caminho = pasta / f"hermes-{carimbo}{'-' + sufixo if sufixo else ''}.db"
    copia = sqlite3.connect(caminho)
    try:
        conn.backup(copia)
    finally:
        copia.close()
    for antigo in sorted(pasta.glob("hermes-*.db"))[:-manter] if manter > 0 else []:
        antigo.unlink()
    return caminho


INSERT_RUN = """
INSERT INTO runs (
    started_at, finished_at, comando, status,
    llm_calls, tool_calls, tool_errors,
    prompt_tokens, completion_tokens, cost_usd,
    model, session_id, warnings, error
) VALUES (
    :started_at, :finished_at, :comando, :status,
    :llm_calls, :tool_calls, :tool_errors,
    :prompt_tokens, :completion_tokens, :cost_usd,
    :model, :session_id, :warnings, :error
)
"""


def record_run(
    conn: sqlite3.Connection,
    comando: str,
    started_at: str,
    status: RunStatus,
    run_status: str,
    model: str | None = None,
    session_id: int | None = None,
    error: str | None = None,
) -> int:
    """Uma linha por execução. Chamada no `finally`, haja erro ou não."""
    cur = conn.execute(
        INSERT_RUN,
        {
            "started_at": started_at,
            "finished_at": utcnow(),
            "comando": comando,
            "status": run_status,
            "llm_calls": status.llm_calls,
            "tool_calls": status.tool_calls,
            "tool_errors": status.tool_errors,
            "prompt_tokens": status.prompt_tokens,
            "completion_tokens": status.completion_tokens,
            "cost_usd": status.cost_usd,
            "model": model,
            "session_id": session_id,
            "warnings": json.dumps(status.warnings, ensure_ascii=False),
            "error": error,
        },
    )
    conn.commit()
    return int(cur.lastrowid)
