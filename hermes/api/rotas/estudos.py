"""Estudos — as mesmas funções de `hermes study`. Você declara; commit só pergunta."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hermes.api.deps import conexao, config, custo, executando
from hermes.config import Config
from hermes.domain import atividade, estudos
from hermes.vault import writer

router = APIRouter(prefix="/api/estudos", tags=["estudos"])


class NovaSessao(BaseModel):
    minutos: int
    o_que_fez: str
    comp: str | None = None
    data: str | None = None
    dificuldade: int | None = None
    travou: str | None = None


class LeituraGit(BaseModel):
    dias: int = 1
    se_mais_velho_que: int | None = None  # segundos; a tela lê sozinha no máximo uma vez por hora


class Confirmacao(BaseModel):
    ids: list[int]
    minutos: int
    o_que_fez: str
    comp: str | None = None
    dificuldade: int | None = None


class Ignorar(BaseModel):
    ids: list[int]


class PedidoPlano(BaseModel):
    minutos: int
    semana: str | None = None
    substituir: bool = False


@router.get("/semana")
def semana(semana: str | None = None, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    return estudos.resumo_semana(conn, semana)


@router.post("/sessoes")
def registrar(corpo: NovaSessao, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "study log"):
        return estudos.log_study(conn, corpo.minutos, corpo.o_que_fez, slug=corpo.comp,
                                 data=corpo.data, dificuldade=corpo.dificuldade,
                                 travou_em=corpo.travou)


def _estado(conn: sqlite3.Connection, chave: str) -> str | None:
    linha = conn.execute("SELECT valor FROM estado_app WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else None


def _gravar_estado(conn: sqlite3.Connection, chave: str, valor: str) -> None:
    with conn:
        conn.execute("INSERT INTO estado_app (chave, valor) VALUES (?, ?)"
                     " ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (chave, valor))


@router.get("/sinais")
def sinais(conn: sqlite3.Connection = Depends(conexao)) -> dict:
    """Commits esperando resposta, mais recentes primeiro, sem ler o git de novo."""
    return {
        "sinais": [dict(r) for r in conn.execute(
            "SELECT id, data, repo, substr(ref, 1, 7) AS sha, resumo, estado FROM activity_signals"
            " WHERE estado IN ('novo', 'perguntado') ORDER BY data DESC, id DESC"
        )],
        "lidos_em": _estado(conn, "git_lido_em"),
    }


@router.post("/git")
def ler_git(corpo: LeituraGit, conn: sqlite3.Connection = Depends(conexao),
            cfg: Config = Depends(config)) -> dict:
    """Lê os commits. Com `se_mais_velho_que`, só lê se a última leitura passou desse tanto de segundos."""
    lidos_em = _estado(conn, "git_lido_em")
    agora = datetime.now(timezone.utc)
    if corpo.se_mais_velho_que is not None and lidos_em:
        try:
            recente = agora - datetime.fromisoformat(lidos_em) < timedelta(seconds=corpo.se_mais_velho_que)
        except ValueError:
            recente = False
        if recente:
            return {"lido": False, "lidos_em": lidos_em}
    with executando(conn, "study git") as ex:
        r = atividade.git_activity(
            conn, corpo.dias, repos_conhecidos=tuple(atividade.descobrir_repos(cfg.repos_dir)),
            status=ex.status,
        )
    lidos_em = agora.isoformat(timespec="seconds")
    _gravar_estado(conn, "git_lido_em", lidos_em)
    return {**r, "lido": True, "lidos_em": lidos_em, "avisos": list(ex.status.warnings)}


@router.post("/sinais/confirmar")
def confirmar(corpo: Confirmacao, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "study confirm"):
        return atividade.confirmar(conn, corpo.ids, corpo.minutos, corpo.o_que_fez,
                                   slug=corpo.comp, dificuldade=corpo.dificuldade)


@router.post("/sinais/ignorar")
def ignorar(corpo: Ignorar, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "study ignore"):
        return atividade.ignorar(conn, corpo.ids)


RESERVA_VENCE = timedelta(minutes=5)


def _chave_md(semana: str) -> str:
    return f"plano_md:{semana}"


@router.post("/plano")
def planejar(corpo: PedidoPlano, conn: sqlite3.Connection = Depends(conexao),
             cfg: Config = Depends(config)) -> dict:
    """Gera e grava o plano no banco, nunca no vault: a tela mostra, e só "Gravar no vault" escreve."""
    semana = corpo.semana or estudos.proxima_semana()
    ja_existia = conn.execute("SELECT 1 FROM study_plan WHERE semana = ?", (semana,)).fetchone() is not None
    if ja_existia and not corpo.substituir:
        # a tela pergunta antes de trocar um plano que já existe (e antes de gastar crédito)
        raise HTTPException(409, "Já existe um plano para essa semana")
    with executando(conn, "study plan") as ex:
        ex.model = cfg.llm_model
        plano = estudos.plan_week(conn, corpo.minutos, semana, corpo.substituir,
                                  status=ex.status, model=cfg.llm_model)
        inicio = date.fromisocalendar(*map(int, plano["semana"].split("-W")), 1)
        anterior = estudos.resumo_semana(conn, estudos.semana_iso(inicio - timedelta(days=7)))
        trecho = estudos.markdown_do_plano(plano, anterior)
    # o vault recebe exatamente o que você revisou; um plano novo pode ir ao vault de novo
    _gravar_estado(conn, _chave_md(plano["semana"]), trecho)
    with conn:
        conn.execute("DELETE FROM estado_app WHERE chave = ?", (f"plano_vault:{plano['semana']}",))
    return {"plano": plano, "markdown": trecho, "custo": custo(ex), "semana": plano["semana"],
            "inicio": inicio.isoformat(), "fim": (inicio + timedelta(days=6)).isoformat(),
            "ja_existia": ja_existia}


@router.post("/plano/{semana}/vault")
def gravar_no_vault(semana: str, conn: sqlite3.Connection = Depends(conexao),
                    cfg: Config = Depends(config)) -> dict:
    """Acrescenta o plano revisado no Diário, uma vez só por plano gerado."""
    trecho = _estado(conn, _chave_md(semana))
    if trecho is None or not conn.execute("SELECT 1 FROM study_plan WHERE semana = ?", (semana,)).fetchone():
        raise estudos.EstudoRecusado(f"nenhum plano gerado para {semana}; gere o plano antes de gravar no vault")
    gravado = f"plano_vault:{semana}"
    # reserva antes de escrever, num INSERT só: dois pedidos juntos (duplo clique, duas janelas) não escrevem
    # o plano duas vezes no Diário; se a escrita falha, a reserva sai e dá para tentar de novo
    agora = datetime.now(timezone.utc)
    with conn:
        reservou = conn.execute("INSERT INTO estado_app (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO NOTHING",
                                (gravado, f"gravando:{agora.isoformat(timespec='seconds')}")).rowcount
        if not reservou:
            # reserva de um pedido que morreu no meio (processo fechado): depois de alguns minutos, vence
            valor = _estado(conn, gravado) or ""
            if valor.startswith("gravando:") and agora - datetime.fromisoformat(valor[9:]) > RESERVA_VENCE:
                reservou = conn.execute("UPDATE estado_app SET valor = ? WHERE chave = ? AND valor = ?",
                                        (f"gravando:{agora.isoformat(timespec='seconds')}", gravado, valor)).rowcount
    if not reservou:
        return {"ja_gravado": True, "nota": None}
    try:
        with executando(conn, "study plan vault"):
            nota = writer.acrescentar(cfg.vault_path, "Diario", semana, trecho, titulo=f"Semana {semana}")
    except BaseException:
        with conn:
            conn.execute("DELETE FROM estado_app WHERE chave = ?", (gravado,))
        raise
    _gravar_estado(conn, gravado, nota["caminho"])
    nome_vault = quote(Path(cfg.vault_path).expanduser().name)
    return {"ja_gravado": False, "nota": nota,
            "obsidian": f"obsidian://open?vault={nome_vault}&file={quote(f'Diario/{semana}')}"}


@router.delete("/plano/{semana}")
def descartar(semana: str, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    with executando(conn, "study plan discard"), conn:
        apagados = conn.execute("DELETE FROM study_plan WHERE semana = ?", (semana,)).rowcount
        conn.execute("DELETE FROM estado_app WHERE chave IN (?, ?)", (_chave_md(semana), f"plano_vault:{semana}"))
    return {"semana": semana, "apagado": bool(apagados)}
