"""Operação: o que `hermes stats`, `check`, `index` e `backup` mostram e fazem."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from hermes.api.deps import conexao, config, executando
from hermes.config import Config
from hermes.db import store
from hermes.domain import competencias, perfil, saude
from hermes.vault import indice
from hermes.vault.check import load_denylist

router = APIRouter(prefix="/api", tags=["operacao"])


@router.get("/operacao/resumo")
def resumo(conn: sqlite3.Connection = Depends(conexao)) -> dict:
    fatos = [dict(r) for r in conn.execute(
        "SELECT tipo, COUNT(DISTINCT nota) AS notas, COUNT(*) AS fatos,"
        " MAX(indexado_em) AS indexado_em FROM facts GROUP BY tipo ORDER BY tipo"
    )]
    runs = [dict(r) for r in conn.execute(
        "SELECT id, started_at, finished_at, comando, status, llm_calls, cost_usd, model, error"
        " FROM runs ORDER BY started_at DESC, id DESC LIMIT 30"
    )]
    gasto = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS chamadas FROM runs"
        " WHERE llm_calls > 0 AND started_at >= datetime('now', '-30 days')"
    ).fetchone()
    return {
        "fatos": fatos,
        "competencias": {k: v for k, v in competencias.cobertura(conn).items() if k != "lacunas"},
        "runs": runs,
        "gasto_30d": dict(gasto),
    }


@router.get("/operacao/check")
def check(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> list[dict]:
    return [asdict(p) for p in saude.avisos_do_vault(conn, cfg)]


@router.post("/operacao/index")
def reindexar(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    with executando(conn, "index") as ex:
        r = indice.reindexar(conn, cfg.vault_path, load_denylist(cfg.denylist_path), ex.status)
    return {**r, "avisos": list(ex.status.warnings)}


class _Indexacao:
    """A indexação da primeira abertura, em segundo plano: a tela mostra o progresso e pode cancelar."""

    def __init__(self):
        import threading

        self.trava = threading.Lock()
        self.estado: dict = {"estado": "parado", "feitas": 0, "total": 0}
        self.cancelar = threading.Event()

    def foto(self) -> dict:
        with self.trava:
            return dict(self.estado)

    def iniciar(self, cfg: Config) -> dict:
        import threading

        with self.trava:
            if self.estado["estado"] == "rodando":
                return dict(self.estado)
            self.estado = {"estado": "rodando", "feitas": 0, "total": 0}
            self.cancelar.clear()
        threading.Thread(target=self._rodar, args=(cfg,), daemon=True).start()
        return {"estado": "rodando"}

    def _progresso(self, feitas: int, total: int) -> None:
        with self.trava:
            self.estado.update(feitas=feitas, total=total)

    def _rodar(self, cfg: Config) -> None:
        from hermes.vault.reader import IndexacaoCancelada

        conn = None
        try:
            conn = store.connect(cfg.db_path)
            with executando(conn, "index") as ex:
                r = indice.reindexar(conn, cfg.vault_path, load_denylist(cfg.denylist_path), ex.status,
                                     progresso=self._progresso, cancelado=self.cancelar.is_set)
            final = {"estado": "pronto", "resultado": {**r, "avisos": list(ex.status.warnings)}}
        except IndexacaoCancelada:
            final = {"estado": "cancelado"}
        except Exception as exc:  # noqa: BLE001 — a tela mostra o motivo, o servidor segue de pé
            final = {"estado": "erro", "erro": str(exc)}
        finally:
            if conn is not None:
                conn.close()
        with self.trava:
            self.estado.update(final)


def _indexacao(request: Request) -> _Indexacao:
    if not hasattr(request.app.state, "indexacao"):
        request.app.state.indexacao = _Indexacao()
    return request.app.state.indexacao


@router.post("/operacao/index/iniciar")
def iniciar_indexacao(request: Request, cfg: Config = Depends(config)) -> dict:
    return _indexacao(request).iniciar(cfg)


@router.get("/operacao/index/progresso")
def progresso_indexacao(request: Request) -> dict:
    return _indexacao(request).foto()


@router.post("/operacao/index/cancelar")
def cancelar_indexacao(request: Request) -> dict:
    ix = _indexacao(request)
    ix.cancelar.set()
    return ix.foto()


@router.post("/operacao/backup")
def backup(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    with executando(conn, "backup"):
        caminho = store.backup(conn, cfg.backup_dir)
    return {"caminho": str(caminho)}


@router.get("/perfil")
def ver_perfil(cfg: Config = Depends(config)) -> dict:
    return perfil.carregar(cfg.vault_path)
