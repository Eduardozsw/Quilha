"""Currículos: perfis, galeria de versões e geração — as mesmas funções de `hermes cv`."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hermes.api.deps import conexao, config, custo, executando
from hermes.config import Config
from hermes.domain import curriculo, perfis_cv

router = APIRouter(prefix="/api/curriculos", tags=["curriculos"])


class PedidoCV(BaseModel):
    perfil: str | None = None
    job_id: int | None = None
    idiomas: list[str] = list(curriculo.IDIOMAS)
    forcar: bool = False


class NovoRecorte(BaseModel):
    cargo_pt: str
    cargo_en: str
    foco: str = ""
    competencias: dict[str, int]
    limite_fatos: int = curriculo.MAX_FATOS
    paginas: int = 1


def _perfis(conn: sqlite3.Connection, cfg: Config) -> list[perfis_cv.PerfilCV]:
    todos = perfis_cv.carregar(cfg.perfis_cv_path)
    perfis_cv.validar(conn, todos)
    return todos


@router.get("/perfis")
def perfis(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> list[dict]:
    return [{"slug": p.slug, "titulo": p.titulo, "cargo": p.cargo, "foco": p.foco,
             "competencias": p.competencias, "limite_fatos": p.limite_fatos}
            for p in _perfis(conn, cfg)]


@router.post("/perfis")
def criar_perfil(corpo: NovoRecorte, conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    with executando(conn, "app cv perfil"):
        p = perfis_cv.criar(cfg.perfis_cv_path, conn, cargo_pt=corpo.cargo_pt, cargo_en=corpo.cargo_en, foco=corpo.foco,
                            competencias=corpo.competencias, limite_fatos=corpo.limite_fatos, paginas=corpo.paginas)
    return {"slug": p.slug, "titulo": p.titulo, "cargo": p.cargo, "foco": p.foco,
            "competencias": p.competencias, "limite_fatos": p.limite_fatos}


@router.get("/galeria")
def galeria(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> list[dict]:
    return curriculo.galeria(conn, _perfis(conn, cfg))


@router.get("/previa")
def previa(perfil: str | None = None, job_id: int | None = None,
           conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> list[dict]:
    """Os fatos que entrariam, sem chamar o modelo. Custo zero — o que mostrar antes de gerar."""
    recorte = perfis_cv.buscar(_perfis(conn, cfg), perfil) if perfil else None
    limite = recorte.limite_fatos if recorte else curriculo.MAX_FATOS
    return curriculo.selecionar(conn, limite, job_id, recorte)


@router.post("")
def gerar(corpo: PedidoCV, conn: sqlite3.Connection = Depends(conexao),
          cfg: Config = Depends(config)) -> dict:
    recorte = perfis_cv.buscar(_perfis(conn, cfg), corpo.perfil) if corpo.perfil else None
    with executando(conn, "cv draft") as ex:
        ex.model = cfg.llm_model
        resultados = curriculo.gerar(conn, cfg.vault_path, cfg.saida_dir, ex.status,
                                     idiomas=tuple(corpo.idiomas), model=cfg.llm_model,
                                     job_id=corpo.job_id, perfil=recorte, forcar=corpo.forcar,
                                     nomes=perfis_cv.carregar_nomes(cfg.perfis_cv_path))
    return {"versoes": [{**r, "caminho": str(r["caminho"])} for r in resultados],
            "custo": custo(ex)}


@router.get("/{versao_id}")
def versao(versao_id: int, conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    return curriculo.versao(conn, versao_id, cfg.vault_path)


class PedidoPDF(BaseModel):
    destino: str | None = None  # "Salvar como…" do app: onde a pessoa escolheu gravar


@router.get("/{versao_id}/previa")
def previa(versao_id: int, conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    """A página como sai no PDF: as imagens das páginas e onde cada fato caiu (a procedência fica clicável)."""
    return curriculo.previa_da_versao(conn, versao_id, _perfis(conn, cfg))


@router.post("/{versao_id}/pdf")
def pdf(versao_id: int, corpo: PedidoPDF | None = None, conn: sqlite3.Connection = Depends(conexao),
        cfg: Config = Depends(config)) -> dict:
    with executando(conn, "cv pdf"):
        return curriculo.pdf_da_versao(conn, versao_id, _perfis(conn, cfg), corpo.destino if corpo else None)


@router.get("/{versao_id}/pdf")
def baixar_pdf(versao_id: int, conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)):
    """O arquivo em si, para o navegador baixar (fora do app não há janela de salvar do sistema)."""
    from fastapi.responses import FileResponse

    with executando(conn, "cv pdf"):
        r = curriculo.pdf_da_versao(conn, versao_id, _perfis(conn, cfg))
    return FileResponse(r["caminho"], media_type="application/pdf", filename=r["nome_sugerido"])
