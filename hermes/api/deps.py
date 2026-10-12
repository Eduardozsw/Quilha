"""O que toda rota usa: configuração, conexão por request e registro em `runs`."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Request

from hermes import runs
from hermes.config import Config
from hermes.db import store


def config(request: Request) -> Config:
    return request.app.state.cfg


def conexao(request: Request) -> Iterator[sqlite3.Connection]:
    conn = store.connect(request.app.state.cfg.db_path, uma_thread=False)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def executando(conn: sqlite3.Connection, comando: str) -> Iterator[runs.Execucao]:
    """Escrita pela API: uma linha em `runs`, entregue se não houve exceção."""
    with runs.registrando(conn, comando) as execucao:
        yield execucao
        execucao.delivered = True


def custo(execucao: runs.Execucao) -> dict:
    """O que o front mostra depois de uma chamada que pode ter gastado crédito."""
    s = execucao.status
    return {
        "llm_calls": s.llm_calls,
        "tokens": s.prompt_tokens + s.completion_tokens,
        "custo_usd": s.cost_usd,
        "avisos": list(s.warnings),
    }
