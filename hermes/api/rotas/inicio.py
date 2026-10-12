"""Início: o painel do dia (sem modelo) e a marca da última visita."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hermes.api.deps import conexao
from hermes.domain import painel

router = APIRouter(prefix="/api", tags=["inicio"])


@router.get("/inicio")
def inicio(conn: sqlite3.Connection = Depends(conexao)) -> dict:
    return painel.resumo(conn, desde=painel.ultima_visita(conn))


class Visita(BaseModel):
    # o `agora` do resumo que a tela mostrou: o que chegou depois dele ainda conta como novidade
    quando: str | None = None


@router.post("/inicio/visita")
def visita(corpo: Visita | None = None, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    quando = (corpo.quando if corpo else None) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    painel.marcar_visita(conn, quando)
    return {"marcada": painel.ultima_visita(conn)}
