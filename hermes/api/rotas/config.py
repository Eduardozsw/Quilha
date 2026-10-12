"""Configuração pelo app: vault, modelo e chaves, sem abrir o `.env`. A chave nunca volta para a tela."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from hermes.api.deps import conexao, config, executando
from hermes.config import Config
from hermes.db import store
from hermes.domain import configuracao, saude, triagem_email
from hermes.llm import FalhaLLM

router = APIRouter(prefix="/api", tags=["config"])


class Mudancas(BaseModel):
    """Campo ausente não muda; string vazia apaga."""
    vault_path: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    email_classificador: Optional[str] = None
    typesafe_api_key: Optional[str] = None
    email_origem: Optional[str] = None
    imap_host: Optional[str] = None
    imap_usuario: Optional[str] = None
    imap_senha: Optional[str] = None
    hermes_max_cost_usd: Optional[str] = None
    email_dias: Optional[str] = None


class Destino(BaseModel):
    caminho: str


@router.get("/config")
def ver(cfg: Config = Depends(config)) -> dict:
    return configuracao.estado(cfg)


class ChaveLLM(BaseModel):
    llm_api_key: str


@router.put("/config")
def gravar(mudancas: Mudancas, request: Request, cfg: Config = Depends(config),
           conn: sqlite3.Connection = Depends(conexao)) -> dict:
    novo = configuracao.gravar(cfg, {k.upper(): v for k, v in mudancas.model_dump().items()})
    request.app.state.cfg = novo
    if mudancas.llm_api_key or mudancas.llm_model:
        configuracao.limpar_recusa(conn)
    return configuracao.estado(novo)


def _testar(conn: sqlite3.Connection, cfg: Config) -> dict:
    """Uma chamada mínima ao modelo configurado; a falha volta como resposta, não como erro HTTP."""
    inicio = time.monotonic()
    try:
        with executando(conn, "llm teste") as ex:
            ex.model = cfg.llm_model
            configuracao._chamada_minima(ex.status)
    except FalhaLLM as exc:
        if str(exc).startswith(configuracao.PREFIXO_RECUSA):
            configuracao.marcar_recusa(conn, store.utcnow())
        return {"ok": False, "mensagem": str(exc)}
    configuracao.limpar_recusa(conn)
    return {"ok": True, "ms": round((time.monotonic() - inicio) * 1000), "modelo": cfg.llm_model}


@router.post("/config/llm/testar")
def testar_llm(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    return _testar(conn, cfg)


@router.post("/config/llm/salvar-e-testar")
def salvar_e_testar(chave: ChaveLLM, request: Request, cfg: Config = Depends(config),
                    conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """O botão "Salvar e testar": nunca apaga a chave (string vazia é recusa; para apagar, só o `.env`)."""
    if not chave.llm_api_key.strip():
        raise configuracao.ConfiguracaoRecusada("Cole a chave antes de salvar")
    novo = configuracao.gravar(cfg, {"LLM_API_KEY": chave.llm_api_key.strip()})
    request.app.state.cfg = novo
    configuracao.limpar_recusa(conn)
    return {"estado": configuracao.estado(novo), "teste": _testar(conn, novo)}


class ChaveJev(BaseModel):
    typesafe_api_key: str


@router.post("/config/jev/testar")
def testar_jev() -> dict:
    return triagem_email.testar_jev()


@router.post("/config/jev/salvar-e-testar")
def salvar_e_testar_jev(chave: ChaveJev, request: Request, cfg: Config = Depends(config)) -> dict:
    """Testa a chave nova antes de gravar: recusada, nada muda e o Jev continua como estava."""
    nova = chave.typesafe_api_key.strip()
    if not nova:
        raise configuracao.ConfiguracaoRecusada("Cole a chave do Jev antes de salvar")
    teste = triagem_email.testar_jev(chave=nova)
    if teste["ok"]:
        cfg = configuracao.gravar(cfg, {"TYPESAFE_API_KEY": nova, "EMAIL_CLASSIFICADOR": "jev"})
        request.app.state.cfg = cfg
    return {"estado": configuracao.estado(cfg), "teste": teste}


@router.get("/config/saude")
def ver_saude(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    return {"problemas": saude.problemas(conn, cfg), "indexado_em": saude.indexado_em(conn)}


@router.post("/vault/exemplo")
def vault_exemplo(destino: Destino) -> dict:
    """Pela tela, o exemplo só nasce em pasta nova ou vazia: misturar notas fictícias nas suas não tem volta."""
    raiz = Path(destino.caminho).expanduser()
    if raiz.is_dir() and any(raiz.iterdir()):
        raise configuracao.ConfiguracaoRecusada(
            f"{raiz} já tem arquivos: escolha uma pasta nova ou vazia para o vault de exemplo")
    return {"criados": configuracao.criar_vault_exemplo(raiz)}
