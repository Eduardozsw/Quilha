"""Busca nos fatos indexados do vault.

É a única porta do agente para o que você escreveu sobre si. Não chama modelo e não escreve:
lê a tabela `facts`, que `quilha index` reconstrói a partir do Obsidian.
"""

from __future__ import annotations

import json
import sqlite3

LIMITE_PADRAO = 10
LIMITE_MAXIMO = 50


def buscar(
    conn: sqlite3.Connection,
    query: str | None = None,
    tags: list[str] | None = None,
    tipo: str | None = None,
    limite: int = LIMITE_PADRAO,
) -> list[dict]:
    """Fatos que casam com todos os termos de `query` e com todas as `tags`.

    Busca por substring, sem ranking: o vault tem dezenas de fatos, não milhares. Quando isso
    deixar de bastar, o lugar de mudar é aqui — o contrato de retorno não muda.
    """
    sql = "SELECT nota, block_id, tipo, entidade, texto, tags FROM facts"
    onde, params = [], []

    for termo in (query or "").split():
        onde.append("texto LIKE ?")
        params.append(f"%{termo}%")
    for tag in tags or []:
        # `tags` é um array JSON gravado como TEXT; a aspa evita casar `#sql` com `#sqlite`
        onde.append("tags LIKE ?")
        params.append(f'%"{tag.lstrip("#")}"%')
    if tipo:
        onde.append("tipo = ?")
        params.append(tipo)

    if onde:
        sql += " WHERE " + " AND ".join(onde)
    sql += " ORDER BY nota, block_id LIMIT ?"
    params.append(max(1, min(int(limite), LIMITE_MAXIMO)))

    return [
        {
            "nota": r["nota"],
            "block_id": r["block_id"],
            "referencia": f"{r['nota']}#{r['block_id']}",
            "tipo": r["tipo"],
            "entidade": r["entidade"],
            "texto": r["texto"],
            "tags": json.loads(r["tags"]),
        }
        for r in conn.execute(sql, params)
    ]
