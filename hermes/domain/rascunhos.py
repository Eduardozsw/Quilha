"""Rascunhos do servidor MCP: a tool que parou esperando o texto do modelo do cliente.

Guardam a tool, os argumentos e as respostas já dadas (por chave do pedido). `submit_draft` acrescenta a
resposta do pedido pendente e reexecuta a tool; a validação é a de sempre, do domínio.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from hermes.db import store

VALIDADE = timedelta(hours=24)


class RascunhoInvalido(Exception):
    pass


def criar(conn: sqlite3.Connection, tool: str, argumentos: dict, pendente: str, respostas: dict) -> str:
    rid = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO rascunhos_mcp (id, tool, argumentos, pendente, respostas, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
            (rid, tool, json.dumps(argumentos, ensure_ascii=False), pendente,
             json.dumps(respostas, ensure_ascii=False), store.utcnow()),
        )
    return rid


def buscar(conn: sqlite3.Connection, rid: str) -> dict:
    linha = conn.execute("SELECT * FROM rascunhos_mcp WHERE id = ?", (rid,)).fetchone()
    if linha is None:
        raise RascunhoInvalido(f"rascunho `{rid}` não existe (já usado ou apagado): chame a tool de novo")
    if datetime.fromisoformat(linha["criado_em"]) < datetime.now(timezone.utc) - VALIDADE:
        raise RascunhoInvalido(f"rascunho `{rid}` venceu (vale 24 h): chame a tool de novo")
    return {"id": linha["id"], "tool": linha["tool"], "argumentos": json.loads(linha["argumentos"]),
            "pendente": linha["pendente"], "respostas": json.loads(linha["respostas"])}


def atualizar(conn: sqlite3.Connection, rid: str, pendente: str, respostas: dict) -> None:
    with conn:
        conn.execute("UPDATE rascunhos_mcp SET pendente = ?, respostas = ? WHERE id = ?",
                     (pendente, json.dumps(respostas, ensure_ascii=False), rid))


def apagar(conn: sqlite3.Connection, rid: str) -> None:
    with conn:
        conn.execute("DELETE FROM rascunhos_mcp WHERE id = ?", (rid,))


def limpar_vencidos(conn: sqlite3.Connection) -> int:
    limite = (datetime.now(timezone.utc) - VALIDADE).isoformat(timespec="seconds")
    with conn:
        return conn.execute("DELETE FROM rascunhos_mcp WHERE criado_em < ?", (limite,)).rowcount
