"""Chat: sessões, histórico e o turno em SSE. O único lugar da API que custa por padrão."""

from __future__ import annotations

import json
import queue
import sqlite3
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hermes.api import chat
from hermes.api.deps import conexao, config
from hermes.config import Config

router = APIRouter(prefix="/api/chat", tags=["chat"])

FINAIS = {"fim", "erro"}


class Pergunta(BaseModel):
    texto: str


class Resposta(BaseModel):
    aprovar: bool


class Titulo(BaseModel):
    titulo: str | None = None


@router.get("/sessoes")
def sessoes(conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    return chat.listar_sessoes(conn)


@router.post("/sessoes")
def nova(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    return {"id": chat.abrir_sessao(conn, cfg.llm_model)}


@router.get("/sessoes/{sessao_id}/mensagens")
def historico(sessao_id: int, conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    try:
        return chat.mensagens(conn, sessao_id)
    except chat.SessaoInexistente as exc:
        raise HTTPException(422, str(exc)) from None


@router.put("/sessoes/{sessao_id}/titulo")
def renomear(sessao_id: int, corpo: Titulo, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    try:
        return chat.renomear(conn, sessao_id, corpo.titulo)
    except chat.SessaoInexistente as exc:
        raise HTTPException(422, str(exc)) from None


@router.delete("/sessoes/{sessao_id}")
def apagar(sessao_id: int, request: Request, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    try:
        if not request.app.state.paradas.apagar_parada(sessao_id, lambda: chat.apagar(conn, sessao_id)):
            raise HTTPException(409, "a conversa ainda está respondendo; pare antes de apagar")
    except chat.SessaoInexistente as exc:
        raise HTTPException(422, str(exc)) from None
    return {"ok": True}


@router.post("/sessoes/{sessao_id}/turnos")
def turno(sessao_id: int, corpo: Pergunta, request: Request,
          conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)):
    # valida antes de abrir o stream: erro de pedido volta como 422, não no meio do SSE
    if conn.execute("SELECT 1 FROM agent_sessions WHERE id = ?", (sessao_id,)).fetchone() is None:
        raise HTTPException(422, f"sessão {sessao_id} não existe")
    if not corpo.texto.strip():
        raise HTTPException(422, "pergunta vazia")

    paradas: chat.Paradas = request.app.state.paradas
    parar = paradas.iniciar(sessao_id)
    if parar is None:
        raise HTTPException(409, "ainda estou terminando a resposta anterior desta conversa; tente de novo em instantes")
    # apagada entre a checagem acima e o registro do turno (o apagar segura a mesma trava): não começa
    if conn.execute("SELECT 1 FROM agent_sessions WHERE id = ?", (sessao_id,)).fetchone() is None:
        paradas.terminar(sessao_id, parar)
        raise HTTPException(422, f"sessão {sessao_id} não existe")
    fila: queue.Queue = queue.Queue()

    def rodar() -> None:
        try:
            chat.rodar_turno(cfg, sessao_id, corpo.texto, request.app.state.confirmacoes,
                             lambda tipo, dados: fila.put((tipo, dados)), parar)
        finally:
            paradas.terminar(sessao_id, parar)

    threading.Thread(target=rodar, daemon=True).start()

    def eventos():
        while True:
            tipo, dados = fila.get()
            yield f"event: {tipo}\ndata: {json.dumps(dados, ensure_ascii=False, default=str)}\n\n"
            if tipo in FINAIS:
                return

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.post("/sessoes/{sessao_id}/parar")
def parar(sessao_id: int, request: Request) -> dict:
    """Para o turno que está rodando; confirmação pendente vira recusa na hora."""
    parou = request.app.state.paradas.parar(sessao_id)
    request.app.state.confirmacoes.cancelar_da_sessao(sessao_id)
    return {"ok": parou}


@router.post("/confirmacoes/{chave}")
def confirmar(chave: str, corpo: Resposta, request: Request) -> dict:
    if not request.app.state.confirmacoes.responder(chave, corpo.aprovar):
        raise HTTPException(404, "pedido expirado ou já respondido")
    return {"ok": True}
