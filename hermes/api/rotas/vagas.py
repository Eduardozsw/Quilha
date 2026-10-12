"""Vagas e coletor — as mesmas funções de `hermes job`. Extrair e redigir o match gastam crédito."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hermes import caminhos, runs
from hermes.api.deps import conexao, config, custo, executando
from hermes.config import Config
from hermes.domain import coletor, vaga
from hermes.vault.check import load_denylist

router = APIRouter(tags=["vagas"])


class NovaVaga(BaseModel):
    texto: str | None = None
    url: str | None = None
    empresa: str | None = None
    titulo: str | None = None


class Mapeamento(BaseModel):
    slug: str | None = None


class PedidoMatch(BaseModel):
    redigir: bool = True


class NovoStatus(BaseModel):
    status: str


class PedidoColeta(BaseModel):
    forcar: bool = False


def _ultimo_match(conn: sqlite3.Connection, job_id: int) -> dict | None:
    linha = conn.execute(
        "SELECT * FROM job_matches WHERE job_id = ? ORDER BY criado_em DESC, id DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if linha is None:
        return None
    m = dict(linha)
    for campo in ("cobertura", "lacunas", "riscos"):
        m[campo] = json.loads(m[campo])
    return m


@router.get("/api/vagas")
def listar(status: str | None = None, conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    return vaga.listar(conn, status)


@router.post("/api/vagas")
def gravar(corpo: NovaVaga, conn: sqlite3.Connection = Depends(conexao),
           cfg: Config = Depends(config)) -> dict:
    if not corpo.url and not (corpo.texto or "").strip():
        raise vaga.VagaRecusada("cole o texto da vaga ou informe a URL")
    with executando(conn, "job add") as ex:
        ex.model = cfg.llm_model
        r = vaga.parse_job(conn, texto=corpo.texto, url=corpo.url, empresa=corpo.empresa,
                           titulo=corpo.titulo, status=ex.status, model=cfg.llm_model,
                           denylist=tuple(load_denylist(cfg.denylist_path)))
    return {**r, "custo": custo(ex)}


@router.get("/api/vagas/{job_id}")
def detalhe(job_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    v = vaga.buscar(conn, job_id)
    sobre = conn.execute("SELECT texto_bruto FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
    # os requisitos vão uma vez só, dentro da avaliação (com a fonte de cada um)
    return {"vaga": v, "sobre": sobre, "avaliacao": vaga.avaliacao(conn, job_id), "match": _ultimo_match(conn, job_id)}


@router.post("/api/vagas/{job_id}/vista")
def vista(job_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app vaga vista"):
        return {"status": vaga.marcar_vista(conn, job_id)}


@router.put("/api/vagas/{job_id}/status")
def definir_status(job_id: int, corpo: NovoStatus, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "app vaga status"):
        return vaga.definir_status(conn, job_id, corpo.status)


@router.post("/api/vagas/{job_id}/extrair")
def extrair(job_id: int, conn: sqlite3.Connection = Depends(conexao),
            cfg: Config = Depends(config)) -> dict:
    with executando(conn, "job extrair") as ex:
        ex.model = cfg.llm_model
        r = vaga.extrair_requisitos(conn, job_id, status=ex.status, model=cfg.llm_model,
                                    denylist=tuple(load_denylist(cfg.denylist_path)))
    return {**r, "custo": custo(ex)}


@router.post("/api/vagas/{job_id}/match")
def match(job_id: int, corpo: PedidoMatch, conn: sqlite3.Connection = Depends(conexao),
          cfg: Config = Depends(config)) -> dict:
    with executando(conn, "job match") as ex:
        if corpo.redigir:
            ex.model = cfg.llm_model
        r = vaga.match_job(conn, job_id, redigir=corpo.redigir, status=ex.status,
                           model=cfg.llm_model)
    return {**r, "custo": custo(ex)}


@router.put("/api/requisitos/{requisito_id}")
def mapear(requisito_id: int, corpo: Mapeamento,
           conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "job map"):
        return vaga.mapear(conn, requisito_id, corpo.slug)


@router.get("/api/coletor/fila")
def fila(conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    return coletor.fila(conn)


@router.get("/api/coletor/estado")
def estado_coleta(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    """Configurações → Coleta: cada fonte do `fontes.yaml` com o que a fila sabe dela, e a última coleta.
    YAML quebrado ou fonte inválida vira `erro` (a tela mostra e oferece abrir o arquivo), nunca 500."""
    caminho = Path(cfg.fontes_path)
    estado = {"caminho": str(caminho), "existe": caminho.is_file(), "erro": None, "fontes": [], "ultima": None}
    ultima = conn.execute("SELECT started_at FROM runs WHERE comando = 'job collect' AND status != 'failed'"
                          " ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
    if ultima:
        novas = conn.execute("SELECT COALESCE(SUM(vagas_novas), 0) FROM coletas WHERE execucao = ?",
                             (ultima[0],)).fetchone()[0]
        estado["ultima"] = {"quando": ultima[0], "vagas_novas": novas}
    if not estado["existe"]:
        return estado
    try:
        fontes = coletor.carregar_fontes(caminho)
    # YAML válido com forma errada (texto solto, lista, `intervalo_h: abc`) e arquivo fora de UTF-8 também
    except (coletor.ColetaRecusada, yaml.YAMLError, ValueError, TypeError, AttributeError) as exc:
        return {**estado, "erro": str(exc).strip() or "fontes.yaml não pôde ser lido"}
    na_fila = {(f["fonte"], f["board"]): f for f in coletor.fila(conn)}
    for f in fontes:
        linha = na_fila.get((f.fonte, f.board), {})
        estado["fontes"].append({
            "tipo": f.fonte, "board": f.board, "empresa": f.empresa, "intervalo_h": f.intervalo_h,
            "estado": linha.get("estado", "nova"), "tentativas": linha.get("tentativas", 0),
            "proximo_em": linha.get("proximo_em"), "ultima_ok_em": linha.get("ultima_ok_em"),
            "ultimo_erro": linha.get("ultimo_erro"),
        })
    return estado


@router.post("/api/coletor/fontes/exemplo")
def fontes_exemplo(cfg: Config = Depends(config)) -> dict:
    """"Criar a partir do exemplo": copia o `fontes.example.yaml` embutido. Nunca escreve por cima."""
    destino = Path(cfg.fontes_path)
    if destino.exists():
        raise HTTPException(409, f"{destino.name} já existe")
    origem = caminhos.EMBUTIDOS if caminhos.EMBUTIDOS.is_dir() else caminhos.PROJECT_ROOT
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem / "fontes.example.yaml", destino)
    return {"caminho": str(destino)}


@router.post("/api/coletor/coletar")
def coletar(corpo: PedidoColeta, conn: sqlite3.Connection = Depends(conexao),
            cfg: Config = Depends(config)) -> dict:
    """Coleta sem extrair: custo zero. Extrair as vagas novas é um clique por vaga."""
    fontes = coletor.carregar_fontes(cfg.fontes_path)
    with runs.registrando(conn, "job collect") as ex:
        r = coletor.coletar(conn, fontes, ex.started_at, ex.status, forcar=corpo.forcar)
        # mesmo critério da CLI: falha parcial vira aviso, não derruba a coleta
        ex.delivered = r["processadas"] == 0 or r["ok"] > 0
    return {**r, "avisos": list(ex.status.warnings)}

