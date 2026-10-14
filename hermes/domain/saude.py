"""Saúde do app para a linha de status de Configurações: o que está errado, do mais grave ao menos.

Cada problema diz em que seção se resolve. E-mail é opcional: nunca configurado não é problema.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path

from hermes.config import Config
from hermes.db import store
from hermes.domain import configuracao
from hermes.vault.check import check_curriculos, check_notes, check_orphan_evidence, load_denylist
from hermes.vault.reader import CAREER_DIR, read_notes

# mesma regra do `faltaLLM` da tela: modelo local não precisa de chave
LOCAL = re.compile(r"^(ollama|ollama_chat|lm_studio)/")


# avisos das notas por "assinatura" do que entra neles (vault, denylist, curriculos.yaml e as datas dos .md):
# a tela pede a saúde a cada campo salvo, e reler o vault inteiro toda vez pesa em vault grande
_CACHE_NOTAS: dict[tuple, list] = {}
_TRAVA_NOTAS = threading.Lock()  # o servidor atende pedidos em paralelo


def _datas(carreira: Path) -> tuple:
    """(caminho, data) de cada nota; a que some no meio da varredura simplesmente não entra."""
    datas = []
    for p in carreira.rglob("*.md"):
        try:
            datas.append((str(p), p.stat().st_mtime))
        except OSError:
            continue
    return tuple(sorted(datas))


def _assinatura(cfg: Config) -> tuple:
    def data(p) -> float | None:
        try:
            return Path(p).stat().st_mtime
        except OSError:
            return None
    carreira = Path(cfg.vault_path) / CAREER_DIR
    notas = _datas(carreira) if carreira.is_dir() else ()
    return (str(cfg.vault_path), str(cfg.denylist_path), data(cfg.denylist_path), str(cfg.perfis_cv_path),
            data(cfg.perfis_cv_path), notas)


def avisos_do_vault(conn: sqlite3.Connection, cfg: Config) -> list:
    """O que `quilha check` acusa: notas, currículos e evidência órfã (esta vem do banco, sempre lida)."""
    chave = _assinatura(cfg)
    with _TRAVA_NOTAS:
        avisos = _CACHE_NOTAS.get(chave)
        if avisos is None:
            notas = read_notes(cfg.vault_path)
            avisos = check_notes(notas, load_denylist(cfg.denylist_path)) + check_curriculos(cfg.perfis_cv_path, notas)
            _CACHE_NOTAS.clear()  # uma assinatura só: a de agora
            _CACHE_NOTAS[chave] = avisos
    return list(avisos) + check_orphan_evidence(store.orphan_evidence(conn))


def _fontes_com_erro(conn: sqlite3.Connection, cfg: Config) -> int:
    """Só as fontes que ainda estão no `fontes.yaml`: a fila guarda as que você já tirou de lá."""
    from hermes.domain import coletor

    try:
        ativas = {(f.fonte, f.board) for f in coletor.carregar_fontes(cfg.fontes_path)} if Path(cfg.fontes_path).is_file() else set()
    except Exception:  # noqa: BLE001 — fontes.yaml quebrado é a tela de Coleta que mostra
        return 0
    return sum(1 for f, b in conn.execute("SELECT fonte, board FROM fila_coleta WHERE estado = 'falhou'")
               if (f, b) in ativas)


def _falta_llm(cfg: Config) -> bool:
    if not cfg.llm_model:
        return True
    return not os.getenv("LLM_API_KEY") and not LOCAL.match(cfg.llm_model)


def _email(conn: sqlite3.Connection) -> dict | None:
    origem = (os.getenv("EMAIL_ORIGEM") or "gmail").strip().lower()
    if origem == "imap" and os.getenv("IMAP_USUARIO") and not os.getenv("IMAP_SENHA"):
        return {"tipo": "email_desconectado", "texto": "E-mail desconectado", "secao": "email", "grave": False}
    ultima = conn.execute("SELECT status FROM runs WHERE comando = 'email sync'"
                          " ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
    if ultima and ultima[0] == "failed":
        return {"tipo": "email_falhou", "texto": "Falha ao buscar e-mails", "secao": "email", "grave": False}
    return None


def _plural(n: int, um: str, varios: str) -> str:
    return f"1 {um}" if n == 1 else f"{n} {varios}"


def problemas(conn: sqlite3.Connection, cfg: Config) -> list[dict]:
    lista = []
    if _falta_llm(cfg):
        lista.append({"tipo": "llm_falta", "texto": "Falta configurar o LLM", "secao": "llm", "grave": True})
    if configuracao.chave_recusada(conn):
        lista.append({"tipo": "llm_recusada", "texto": "O provedor recusou a chave do LLM", "secao": "llm",
                      "grave": True})
    if email := _email(conn):
        lista.append(email)
    fontes = _fontes_com_erro(conn, cfg)
    if fontes:
        lista.append({"tipo": "fontes_erro", "texto": _plural(fontes, "fonte de vagas com erro",
                                                              "fontes de vagas com erro"),
                      "secao": "coleta", "grave": False})
    avisos = len(avisos_do_vault(conn, cfg)) if Path(cfg.vault_path).is_dir() else 0
    if avisos:
        lista.append({"tipo": "vault_avisos", "texto": _plural(avisos, "aviso no vault", "avisos no vault"),
                      "secao": "diagnostico", "grave": False})
    return lista


def indexado_em(conn: sqlite3.Connection) -> str | None:
    return conn.execute("SELECT MAX(indexado_em) FROM facts").fetchone()[0]
