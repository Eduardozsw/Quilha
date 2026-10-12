"""Competências: taxonomia, evidência e nível — as mesmas regras de `hermes comp`."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hermes.api.deps import conexao, config, executando
from hermes.config import Config
from hermes.domain import competencias
from hermes.vault import writer

router = APIRouter(prefix="/api/competencias", tags=["competencias"])


class NovaEvidencia(BaseModel):
    referencia: str
    forca: int = 2
    obs: str | None = None
    metrica: bool | None = None
    # o "Desfazer" de um desligar: religa mesmo se o fato saiu do vault
    restaurar: bool = False


class NovaCompetencia(BaseModel):
    nome: str
    categoria: str
    peso: int = 2


class NovoNivel(BaseModel):
    nivel: int
    justificativa: str


def _espelha(conn: sqlite3.Connection, cfg: Config) -> str | None:
    """Mantém `Competencias.md` em dia. Falhar no espelho não desfaz a gravação: vira aviso."""
    try:
        competencias.atualizar_nota_exportada(conn, cfg.vault_path)
    except (OSError, writer.EscritaRecusada) as exc:
        return f"{competencias.NOTA_EXPORTADA}.md não foi atualizada — {exc}"
    return None


@router.get("")
def listar(categoria: str | None = None, lacunas: bool = False,
           conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    return competencias.listar(conn, categoria=categoria, so_lacunas=lacunas)


@router.post("")
def nova(corpo: NovaCompetencia, conn: sqlite3.Connection = Depends(conexao),
         cfg: Config = Depends(config)) -> dict:
    """Grava no `competencias.yaml` (sem regravar o resto do arquivo) e no banco."""
    try:
        with executando(conn, "comp new"):
            linha = competencias.nova(cfg.competencias_path, conn, corpo.nome, corpo.categoria, corpo.peso)
    except competencias.CompetenciaDuplicada as exc:
        raise HTTPException(409, str(exc)) from None
    return {**linha, "aviso": _espelha(conn, cfg)}


@router.get("/categorias")
def categorias() -> list[dict]:
    return [{"id": c, "nome": competencias.NOMES_CATEGORIAS[c]} for c in competencias.CATEGORIAS]


@router.get("/niveis")
def niveis() -> dict[int, str]:
    return competencias.NIVEIS


@router.get("/cobertura")
def cobertura(conn: sqlite3.Connection = Depends(conexao)) -> dict:
    return competencias.cobertura(conn)


@router.post("/exportar")
def exportar(conn: sqlite3.Connection = Depends(conexao), cfg: Config = Depends(config)) -> dict:
    with executando(conn, "comp export"):
        r = writer.substituir_gerada(cfg.vault_path, competencias.NOTA_EXPORTADA,
                                     competencias.exportar_markdown(conn))
    return r


@router.get("/{slug}")
def detalhe(slug: str, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    competencias.buscar(conn, slug)  # recusa slug inexistente com a mensagem do domínio
    # `listar` é quem calcula situação e prontidão; o detalhe mostra o mesmo que a lista
    linha = next(c for c in competencias.listar(conn) if c["slug"] == slug)
    provas = competencias.evidencias(conn, slug)
    estudos = conn.execute(
        "SELECT data, minutos, o_que_fez FROM study_sessions WHERE competency_id = ?"
        " ORDER BY data DESC, id DESC", (linha["id"],)).fetchall()
    return {
        "competencia": linha,
        "evidencias": provas,
        "candidatos": competencias.fatos_candidatos(conn, slug, limite=5),
        # a folha de nível mostra a recusa antes de gravar, com a mesma regra da gravação
        "recusas": {str(n): competencias.recusa_nivel(slug, n, provas, nome=linha["nome"])
                    for n in competencias.NIVEIS},
        "estudos": {"ultimos": [dict(e) for e in estudos[:3]], "total": len(estudos)},
    }


@router.get("/{slug}/estudos")
def estudos(slug: str, conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
    """Todos os estudos registrados na competência, do mais recente ao mais antigo ("Ver todos" do histórico)."""
    c = competencias.buscar(conn, slug)
    return [dict(r) for r in conn.execute(
        "SELECT data, minutos, o_que_fez FROM study_sessions WHERE competency_id = ? ORDER BY data DESC, id DESC",
        (c["id"],))]


@router.post("/{slug}/evidencias")
def ligar(slug: str, corpo: NovaEvidencia, conn: sqlite3.Connection = Depends(conexao),
          cfg: Config = Depends(config)) -> dict:
    with executando(conn, "comp evidence"):
        r = competencias.ligar_evidencia(conn, slug, corpo.referencia, forca=corpo.forca,
                                         tem_metrica=corpo.metrica, observacao=corpo.obs, restaurar=corpo.restaurar)
    return {**r, "aviso": _espelha(conn, cfg)}


@router.delete("/{slug}/evidencias")
def desligar(slug: str, referencia: str, conn: sqlite3.Connection = Depends(conexao),
             cfg: Config = Depends(config)) -> dict:
    with executando(conn, "comp evidence"):
        r = competencias.remover_evidencia(conn, slug, referencia)
    return {**r, "aviso": _espelha(conn, cfg)}


@router.get("/{slug}/ligacoes")
def ligacoes(slug: str, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """O que perde a ligação se a competência sair: a confirmação de "Remover" diz antes."""
    return competencias.ligacoes(conn, slug)


@router.delete("/{slug}")
def remover(slug: str, com_historico: bool = False, conn: sqlite3.Connection = Depends(conexao),
            cfg: Config = Depends(config)) -> dict:
    """Sai do banco e do YAML da taxonomia, senão o próximo `comp seed` traz de volta. `com_historico` vem da
    confirmação da tela: as ligações de evidência e os níveis vão junto."""
    with executando(conn, "comp remove"):
        r = competencias.remover(conn, slug, com_historico=com_historico)
    return {**r, "do_seed": competencias.tirar_do_seed(cfg.competencias_path, slug), "aviso": _espelha(conn, cfg)}


@router.post("/{slug}/nivel")
def avaliar(slug: str, corpo: NovoNivel, conn: sqlite3.Connection = Depends(conexao),
            cfg: Config = Depends(config)) -> dict:
    with executando(conn, "comp assess"):
        r = competencias.avaliar(conn, slug, corpo.nivel, corpo.justificativa)
    return {**r, "aviso": _espelha(conn, cfg)}
