"""Uma linha em `runs` por execução — da CLI ou da API.

O registro é gravado no `finally`, haja erro ou não. Este módulo não conhece terminal nem HTTP:
a CLI decide como mostrar a falha, a API decide o código de resposta.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from hermes.db import store
from hermes.run_status import RunStatus, final_status


class Execucao:
    """Estado de uma execução: o que vira a linha da tabela `runs`."""

    def __init__(self, conn: sqlite3.Connection, comando: str):
        self.conn = conn
        self.comando = comando
        self.status = RunStatus()
        self.started_at = store.utcnow()
        self.delivered = False
        self.crashed = False
        self.erro: str | None = None
        self.model: str | None = None
        self.session_id: int | None = None


def gravar(execucao: Execucao) -> None:
    run_status = final_status(execucao.status, execucao.crashed, execucao.delivered)
    store.record_run(execucao.conn, execucao.comando, execucao.started_at, execucao.status,
                     run_status, model=execucao.model, session_id=execucao.session_id,
                     error=execucao.erro)


@contextmanager
def registrando(conn: sqlite3.Connection, comando: str) -> Iterator[Execucao]:
    """Registra a execução e deixa a exceção seguir para quem chamou."""
    execucao = Execucao(conn, comando)
    try:
        yield execucao
    except Exception as exc:
        execucao.crashed = True
        execucao.erro = str(exc)
        raise
    finally:
        gravar(execucao)
