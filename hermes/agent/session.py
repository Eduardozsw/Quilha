"""Histórico da conversa no SQLite: é o que permite `hermes chat --continue`.

As mensagens são gravadas no formato que o provedor espera, para o histórico voltar à API sem
tradução. Invariante que o provedor cobra: toda `assistant` com `tool_calls` é seguida por uma
mensagem `tool` por chamada, com o mesmo `tool_call_id`. O recorte de contexto respeita isso.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from hermes.db import store

# ~4 caracteres por token. Aproximação deliberada: o tokenizer certo depende do provedor, e
# errar para mais aqui custa um recorte antecipado, não uma chamada rejeitada.
CHARS_POR_TOKEN = 4
TETO_TOKENS_PADRAO = 12_000


@dataclass
class Session:
    conn: sqlite3.Connection
    id: int
    resumo: str | None = None

    @property
    def proximo_idx(self) -> int:
        linha = self.conn.execute(
            "SELECT COALESCE(MAX(idx), -1) + 1 AS proximo FROM agent_messages WHERE session_id = ?",
            (self.id,),
        ).fetchone()
        return int(linha["proximo"])

    def gravar(self, mensagem: dict, meta: dict | None = None) -> None:
        """`meta` é da tela (custo, cartões, confirmações), nunca volta ao provedor."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO agent_messages"
                " (session_id, idx, role, content, tool_calls, tool_call_id, criado_em, meta)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.id,
                    self.proximo_idx,
                    mensagem["role"],
                    mensagem.get("content"),
                    json.dumps(mensagem["tool_calls"], ensure_ascii=False)
                    if mensagem.get("tool_calls")
                    else None,
                    mensagem.get("tool_call_id"),
                    store.utcnow(),
                    json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                ),
            )

    def mensagens(self) -> list[dict]:
        """O histórico como o provedor espera, sem o `meta` da tela. A `assistant` vazia (turno parado antes do
        modelo responder) só existe para a tela: o provedor recusa mensagem sem conteúdo."""
        return [{k: v for k, v in m.items() if k != "meta"} for m in self.mensagens_com_meta()
                if not (m["role"] == "assistant" and not m["content"] and not m.get("tool_calls"))]

    def mensagens_com_meta(self) -> list[dict]:
        linhas = self.conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, meta FROM agent_messages"
            " WHERE session_id = ? ORDER BY idx",
            (self.id,),
        )
        historico = []
        for r in linhas:
            msg: dict = {"role": r["role"], "content": r["content"]}
            if r["tool_calls"]:
                msg["tool_calls"] = json.loads(r["tool_calls"])
            if r["tool_call_id"]:
                msg["tool_call_id"] = r["tool_call_id"]
            msg["meta"] = json.loads(r["meta"]) if r["meta"] else None
            historico.append(msg)
        return historico

    def anotar_turno(self, desde_idx: int, meta: dict) -> bool:
        """Grava o `meta` na última `assistant` do turno que começou em `desde_idx`. False quando o
        turno não chegou a ter resposta (erro antes da primeira chamada ao modelo)."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE agent_messages SET meta = ? WHERE id = (SELECT id FROM agent_messages"
                " WHERE session_id = ? AND role = 'assistant' AND idx >= ? ORDER BY idx DESC LIMIT 1)",
                (json.dumps(meta, ensure_ascii=False), self.id, desde_idx),
            )
        return cur.rowcount > 0

    def apagar_ultima(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM agent_messages WHERE id = (SELECT id FROM agent_messages"
                              " WHERE session_id = ? ORDER BY idx DESC LIMIT 1)", (self.id,))

    def definir_resumo(self, texto: str) -> None:
        self.resumo = texto
        with self.conn:
            self.conn.execute(
                "UPDATE agent_sessions SET resumo = ? WHERE id = ?", (texto, self.id)
            )

    def apagar(self) -> None:
        """Descarta uma sessão que não chegou a ter mensagem. `runs` referencia sessão por FK,
        então quem chama precisa esquecer o id antes de gravar a execução."""
        with self.conn:
            self.conn.execute("DELETE FROM agent_sessions WHERE id = ?", (self.id,))

    def fechar(self, model: str | None, cost_usd: float | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE agent_sessions SET finished_at = ?, model = ?, cost_usd = ? WHERE id = ?",
                (store.utcnow(), model, cost_usd, self.id),
            )


def abrir(conn: sqlite3.Connection, model: str | None = None) -> Session:
    with conn:
        cur = conn.execute(
            "INSERT INTO agent_sessions (started_at, model) VALUES (?, ?)",
            (store.utcnow(), model),
        )
    return Session(conn=conn, id=int(cur.lastrowid))


def continuar(conn: sqlite3.Connection, session_id: int | None = None) -> Session:
    """Retoma uma sessão. Sem id, retoma a mais recente. Sem nenhuma, abre uma nova."""
    if session_id is not None:
        linha = conn.execute(
            "SELECT id, resumo FROM agent_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if linha is None:
            raise ValueError(f"sessão {session_id} não existe")
    else:
        linha = conn.execute(
            "SELECT id, resumo FROM agent_sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if linha is None:
            return abrir(conn)
    sessao = Session(conn=conn, id=int(linha["id"]), resumo=linha["resumo"])
    with conn:
        conn.execute("UPDATE agent_sessions SET finished_at = NULL WHERE id = ?", (sessao.id,))
    return sessao


def estimar_tokens(mensagens: list[dict]) -> int:
    chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in mensagens)
    return chars // CHARS_POR_TOKEN


def recortar(
    mensagens: list[dict], teto_tokens: int = TETO_TOKENS_PADRAO
) -> tuple[list[dict], list[dict]]:
    """Divide o histórico em (descartadas, mantidas) para caber no teto.

    O corte cai sempre numa mensagem `user`: começar por uma `tool` órfã, ou por uma `assistant`
    cujas tool calls ficaram para trás, é rejeitado pelo provedor.
    """
    if estimar_tokens(mensagens) <= teto_tokens:
        return [], mensagens

    inicios = [i for i, m in enumerate(mensagens) if m["role"] == "user"]
    for corte in inicios:
        if estimar_tokens(mensagens[corte:]) <= teto_tokens:
            return mensagens[:corte], mensagens[corte:]

    # nem o último turno cabe: mantém ele mesmo assim e deixa o provedor decidir
    ultimo = inicios[-1] if inicios else 0
    return mensagens[:ultimo], mensagens[ultimo:]
