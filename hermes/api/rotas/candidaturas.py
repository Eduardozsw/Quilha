"""Candidaturas — as mesmas funções de `hermes app`. Nada aqui chama o modelo."""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hermes.api.deps import conexao, config, custo, executando
from hermes.config import Config
from hermes.domain import anuncios, candidaturas, estudos, perfis_cv

router = APIRouter(prefix="/api/candidaturas", tags=["candidaturas"])


class Perfil(BaseModel):
    perfil: str


class Entrevista(BaseModel):
    quando: str | None = None
    titulo: str | None = None


class Nova(BaseModel):
    empresa: str
    titulo: str | None = None
    enviada_em: str | None = None
    perfil: str | None = None


class Reabrir(BaseModel):
    anterior: str | None = None


class Juntar(BaseModel):
    destino: int


class Enviada(BaseModel):
    quando: str | None = None


class Titulo(BaseModel):
    titulo: str | None = None


def _perfil_valido(cfg: Config, slug: str) -> str:
    """`geral` ou um slug de `curriculos.yaml`; a recusa diz quais existem."""
    if slug != candidaturas.GERAL:
        perfis_cv.buscar(perfis_cv.carregar(cfg.perfis_cv_path), slug)
    return slug


@router.get("")
def listar(status: str | None = None, conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    return candidaturas.listar(conn, status)


@router.post("")
def adicionar(corpo: Nova, conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    """Candidatura feita fora do Quilha: nasce em "Aguardando resposta" (`enviada`). Sem custo."""
    perfil = _perfil_valido(cfg, (corpo.perfil or "").strip() or candidaturas.GERAL)
    with executando(conn, "app adicionar"):
        cid = candidaturas.registrar_manual(conn, corpo.empresa.strip(), perfil,
                                            titulo=(corpo.titulo or "").strip() or None,
                                            enviada_em=corpo.enviada_em or date.today().isoformat())
    return candidaturas.detalhe(conn, cid)


@router.get("/notas")
def notas(conn: sqlite3.Connection = Depends(conexao)) -> dict:
    return candidaturas.notas_por_perfil(conn, date.today())


@router.get("/anunciadas")
def anunciadas(conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    """Vagas dos alertas de e-mail: cardápio, não candidatura. Antes de `/{id}` para não colidir."""
    return anuncios.listar(conn)


@router.get("/{candidatura_id}")
def detalhe(candidatura_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    return candidaturas.detalhe(conn, candidatura_id)


@router.put("/{candidatura_id}/perfil")
def definir_perfil(candidatura_id: int, corpo: Perfil, conn: sqlite3.Connection = Depends(conexao),
                   cfg: Config = Depends(config)) -> dict:
    with executando(conn, "app perfil"):
        candidaturas.definir_perfil(conn, candidatura_id, _perfil_valido(cfg, corpo.perfil))
    return candidaturas.detalhe(conn, candidatura_id)


@router.put("/{candidatura_id}/titulo")
def definir_titulo(candidatura_id: int, corpo: Titulo, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app titulo"):
        candidaturas.definir_titulo(conn, candidatura_id, corpo.titulo)
    return candidaturas.detalhe(conn, candidatura_id)


class Vaga(BaseModel):
    job_id: int


@router.put("/{candidatura_id}/vaga")
def ligar_vaga(candidatura_id: int, corpo: Vaga, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app vaga ligada"):
        return candidaturas.ligar_vaga(conn, candidatura_id, corpo.job_id)


@router.put("/{candidatura_id}/entrevista")
def marcar_entrevista(candidatura_id: int, corpo: Entrevista,
                      conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app entrevista"):
        return candidaturas.marcar_entrevista(conn, candidatura_id, corpo.quando, corpo.titulo)


@router.post("/{candidatura_id}/enviada")
def marcar_enviada(candidatura_id: int, corpo: Enviada, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app enviada"):
        return candidaturas.marcar_enviada(conn, candidatura_id, corpo.quando)


@router.post("/{candidatura_id}/juntar")
def juntar(candidatura_id: int, corpo: Juntar, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app juntar"):
        return candidaturas.juntar(conn, candidatura_id, corpo.destino)


@router.post("/{candidatura_id}/cancelar")
def cancelar(candidatura_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app cancelar"):
        candidaturas.cancelar(conn, candidatura_id)
    return candidaturas.detalhe(conn, candidatura_id)


@router.delete("/{candidatura_id}")
def descartar(candidatura_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """"Não vou enviar": só para a candidatura a enviar. Devolve a linha para o desfazer."""
    with executando(conn, "app descartar"):
        return {"rascunho": candidaturas.descartar_rascunho(conn, candidatura_id)}


@router.post("/rascunho")
def restaurar_rascunho(corpo: dict, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app restaurar"):
        return candidaturas.restaurar_rascunho(conn, corpo.get("rascunho") or {})


@router.post("/{candidatura_id}/reabrir")
def reabrir(candidatura_id: int, corpo: Reabrir, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """O "Desfazer" do cancelar."""
    with executando(conn, "app reabrir"):
        return candidaturas.reabrir(conn, candidatura_id, corpo.anterior)


@router.post("/{candidatura_id}/preparar")
def preparar(candidatura_id: int, conn: sqlite3.Connection = Depends(conexao),
             cfg: Config = Depends(config)) -> dict:
    with executando(conn, "interview prep") as ex:
        ex.model = cfg.llm_model
        roteiro = estudos.roteiro_entrevista(conn, candidatura_id, status=ex.status, model=cfg.llm_model)
    return {"roteiro": roteiro, "custo": custo(ex)}
