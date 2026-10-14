from datetime import datetime, timedelta, timezone

import pytest

from hermes.domain import rascunhos


def test_criar_buscar_atualizar_apagar(conn):
    rid = rascunhos.criar(conn, "parse_job", {"texto": "x"}, "abc", {})
    r = rascunhos.buscar(conn, rid)
    assert (r["tool"], r["argumentos"], r["pendente"], r["respostas"]) == ("parse_job", {"texto": "x"}, "abc", {})

    rascunhos.atualizar(conn, rid, "def", {"abc": "{}"})
    assert rascunhos.buscar(conn, rid)["respostas"] == {"abc": "{}"}

    rascunhos.apagar(conn, rid)
    with pytest.raises(rascunhos.RascunhoInvalido, match="não existe"):
        rascunhos.buscar(conn, rid)


def test_rascunho_vencido_e_recusado_e_limpo(conn):
    rid = rascunhos.criar(conn, "parse_job", {}, "abc", {})
    velho = (datetime.now(timezone.utc) - rascunhos.VALIDADE - timedelta(minutes=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE rascunhos_mcp SET criado_em = ? WHERE id = ?", (velho, rid))
    conn.commit()

    with pytest.raises(rascunhos.RascunhoInvalido, match="venceu"):
        rascunhos.buscar(conn, rid)
    assert rascunhos.limpar_vencidos(conn) == 1
