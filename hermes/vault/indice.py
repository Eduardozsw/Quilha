"""Reconstrução do índice de fatos a partir do vault. Sem LLM, custo zero."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hermes.db import store
from hermes.run_status import RunStatus
from hermes.vault.check import Problem, check_notes
from hermes.vault.reader import CAREER_DIR, read_notes


class IndiceBloqueado(Exception):
    """Termo da denylist no vault: nada é indexado até ele sair."""

    def __init__(self, bloqueios: list[Problem]):
        self.bloqueios = bloqueios
        super().__init__("denylist: índice não construído")


class VaultSemCarreira(Exception):
    """A pasta escolhida não tem `Carreira/` e o índice tem fatos: reindexar zeraria o índice. Nada é tocado."""


def reindexar(conn: sqlite3.Connection, vault: Path, denylist: list[str],
              status: RunStatus, progresso=None, cancelado=None) -> dict:
    """Apaga e reconstrói `facts`. Nota ou fato inválido vira aviso em `status`, não derruba.
    Cancelada no meio (`cancelado()`), o índice anterior fica como estava: a troca só acontece no fim."""
    # sem Carreira/ o índice sairia vazio: com fatos já indexados, isso é pasta errada e apagaria tudo; num
    # índice vazio (primeira abertura com o vault real, que ainda não tem Carreira/) não há o que perder
    sem_carreira = not (Path(vault).expanduser() / CAREER_DIR).is_dir()
    if sem_carreira and conn.execute("SELECT 1 FROM facts LIMIT 1").fetchone():
        raise VaultSemCarreira(
            f"não achei a pasta {CAREER_DIR}/ em {vault}, e reindexar apagaria os fatos que você já tem. Se é o"
            f" seu vault, crie a pasta {CAREER_DIR}/ dentro dele com as notas de experiência e projeto; senão,"
            " escolha a pasta raiz do vault")
    notas = read_notes(vault, progresso, cancelado)
    bloqueios = [p for p in check_notes(notas, denylist) if "denylist" in p.mensagem]
    if bloqueios:
        raise IndiceBloqueado(bloqueios)

    validos = []
    for nota in notas:
        if not nota.tipo or not nota.entidade:
            status.add(f"{nota.nota}: frontmatter incompleto, nota ignorada")
            continue
        for fato in nota.facts:
            if not fato.block_id or not fato.texto:
                status.add(f"{nota.nota}:{fato.linha}: fato sem block id, não indexado")
                continue
            validos.append({
                "nota": nota.nota,
                "block_id": fato.block_id,
                "tipo": nota.tipo,
                "entidade": nota.entidade,
                "texto": fato.texto,
                "tags": fato.tags,
            })

    total = store.reindex_facts(conn, validos)
    orfas = store.orphan_evidence(conn)
    for o in orfas:
        status.add(f"evidência órfã: {o['slug']} → {o['nota']}#{o['block_id']}")
    return {"fatos": total, "notas": len(notas), "orfas": orfas}
