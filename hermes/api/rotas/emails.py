"""E-mails de processo — as mesmas funções de `quilha email`. Só o sync chama o Jev (e custa crédito)."""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hermes.api.deps import conexao, config, custo, executando
from hermes.config import Config
from hermes.domain import candidaturas, configuracao, triagem_email

router = APIRouter(prefix="/api/emails", tags=["emails"])


class Categoria(BaseModel):
    categoria: str


class Ligacao(BaseModel):
    candidatura_id: int


class Empresa(BaseModel):
    empresa: str


class Triar(BaseModel):
    categoria: str
    candidatura_id: int | None = None
    nova: bool = False
    empresa: str | None = None


class Restaurar(BaseModel):
    rotulo_manual: str | None = None
    candidatura_id: int | None = None
    empresa: str | None = None
    apagar: int | None = None
    candidatura_antes: dict | None = None


class PedidoSync(BaseModel):
    dias: int = Field(30, ge=1, le=365)
    maximo: int = Field(200, ge=1, le=1000)


@router.get("")
def listar(visao: str = "pendentes", conn: sqlite3.Connection = Depends(conexao)) -> dict:
    ultimo = conn.execute(
        "SELECT MAX(started_at) FROM runs WHERE comando = 'email sync' AND status != 'failed'").fetchone()[0]
    return {"emails": candidaturas.listar_emails(conn, visao), "contagens": candidaturas.contar_emails(conn),
            "ultimo_sync": ultimo}


@router.post("/sync")
def sincronizar(corpo: PedidoSync, conn: sqlite3.Connection = Depends(conexao),
                cfg: Config = Depends(config)) -> dict:
    """Lê o Gmail e classifica só os e-mails novos (LLM do usuário ou Jev), como `quilha email sync`."""
    from hermes.integracoes import caixa as caixas

    with triagem_email.classificador_configurado() as (classificador, modelo):
        with executando(conn, "email sync") as ex:
            ex.model = modelo
            try:
                caixa = caixas.abrir(cfg)
            except caixas.Indisponivel as exc:
                raise HTTPException(422, str(exc)) from None
            try:
                r = triagem_email.sincronizar(conn, caixa, classificador, corpo.dias, corpo.maximo, ex.status)
            finally:
                if hasattr(caixa, "fechar"):
                    caixa.fechar()
    configuracao.lembrar_recusa_nos_avisos(conn, ex.status.warnings)
    return {**r, "chegou_ao_maximo": r["lidos"] >= corpo.maximo,
            "custo": {**custo(ex), "avisos": triagem_email.resumir_avisos(ex.status.warnings)}}


@router.post("/testar")
def testar(cfg: Config = Depends(config)) -> dict:
    """Conecta na caixa configurada (IMAP ou Gmail) e conta os e-mails da semana. Não classifica: custo zero."""
    from hermes.integracoes import caixa as caixas

    return caixas.testar(cfg)


@router.get("/{email_id}")
def ver(email_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    return candidaturas.email(conn, email_id)


@router.post("/{email_id}/categoria")
def corrigir(email_id: int, corpo: Categoria, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "email corrigir"):
        candidaturas.corrigir(conn, email_id, corpo.categoria)
    return candidaturas.email(conn, email_id)


@router.post("/{email_id}/candidatura")
def ligar(email_id: int, corpo: Ligacao, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "email ligar"):
        candidaturas.ligar_manual(conn, email_id, corpo.candidatura_id)
    return candidaturas.email(conn, email_id)


@router.post("/{email_id}/desligar")
def desligar(email_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "email desligar"):
        candidaturas.desligar(conn, email_id)
    return candidaturas.email(conn, email_id)


@router.post("/{email_id}/empresa")
def empresa(email_id: int, corpo: Empresa, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "email empresa"):
        candidaturas.definir_empresa(conn, email_id, corpo.empresa)
    return candidaturas.email(conn, email_id)


@router.post("/{email_id}/nova-candidatura")
def nova_candidatura(email_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "email nova candidatura"):
        candidaturas.nova_do_email(conn, email_id)
    return candidaturas.email(conn, email_id)


@router.post("/{email_id}/triar")
def triar(email_id: int, corpo: Triar, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """Um passo da triagem: categoria, empresa e ligação de uma vez (sem pingada órfã no meio)."""
    with executando(conn, "email triar"):
        r = candidaturas.triar(conn, email_id, corpo.categoria, candidatura_id=corpo.candidatura_id,
                               nova=corpo.nova, empresa=corpo.empresa)
    return {**r, "email": candidaturas.email(conn, email_id)}


@router.post("/{email_id}/restaurar")
def restaurar(email_id: int, corpo: Restaurar, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """O "Desfazer" do triado."""
    with executando(conn, "email restaurar"):
        candidaturas.restaurar_email(conn, email_id, rotulo_manual=corpo.rotulo_manual,
                                     candidatura_id=corpo.candidatura_id, empresa=corpo.empresa, apagar=corpo.apagar,
                                     candidatura_antes=corpo.candidatura_antes)
    return candidaturas.email(conn, email_id)
