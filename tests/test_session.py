"""Sessão: o histórico que volta para a API sem tradução, e o recorte que o provedor aceita."""

import pytest

from hermes.agent import session as s

CHAMADA = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "list_competencies", "arguments": "{}"},
}


def test_roundtrip_preserva_o_formato_do_provedor(conn):
    sessao = s.abrir(conn, "gpt-4o-mini")
    sessao.gravar({"role": "user", "content": "quais competências?"})
    sessao.gravar({"role": "assistant", "content": None, "tool_calls": [CHAMADA]})
    sessao.gravar({"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'})
    sessao.gravar({"role": "assistant", "content": "são 3"})

    assert sessao.mensagens() == [
        {"role": "user", "content": "quais competências?"},
        {"role": "assistant", "content": None, "tool_calls": [CHAMADA]},
        {"role": "tool", "content": '{"ok": true}', "tool_call_id": "call_1"},
        {"role": "assistant", "content": "são 3"},
    ]


def test_ordem_sobrevive_a_reabertura(conn):
    sessao = s.abrir(conn)
    for i in range(5):
        sessao.gravar({"role": "user", "content": str(i)})
    retomada = s.continuar(conn, sessao.id)
    assert [m["content"] for m in retomada.mensagens()] == ["0", "1", "2", "3", "4"]


def test_continuar_sem_id_pega_a_mais_recente(conn):
    s.abrir(conn)
    segunda = s.abrir(conn)
    assert s.continuar(conn).id == segunda.id


def test_continuar_sem_nenhuma_sessao_abre_uma(conn):
    assert s.continuar(conn).id == 1


def test_continuar_sessao_inexistente_falha(conn):
    with pytest.raises(ValueError, match="99"):
        s.continuar(conn, 99)


def test_fechar_grava_modelo_e_custo(conn):
    sessao = s.abrir(conn)
    sessao.fechar("gpt-4o-mini", 0.0123)
    linha = conn.execute(
        "SELECT finished_at, model, cost_usd FROM agent_sessions WHERE id = ?", (sessao.id,)
    ).fetchone()
    assert linha["finished_at"] and linha["model"] == "gpt-4o-mini"
    assert linha["cost_usd"] == pytest.approx(0.0123)


def test_custo_desconhecido_fica_null_nao_zero(conn):
    sessao = s.abrir(conn)
    sessao.fechar("modelo-local", None)
    assert conn.execute(
        "SELECT cost_usd FROM agent_sessions WHERE id = ?", (sessao.id,)
    ).fetchone()["cost_usd"] is None


def test_resumo_persiste(conn):
    sessao = s.abrir(conn)
    sessao.definir_resumo("falamos de SQL")
    assert s.continuar(conn, sessao.id).resumo == "falamos de SQL"


def test_historico_pequeno_nao_e_recortado():
    mensagens = [{"role": "user", "content": "oi"}]
    assert s.recortar(mensagens, 12_000) == ([], mensagens)


def test_recorte_nunca_comeca_numa_tool_orfa():
    """Começar por `tool` sem a `assistant` que a pediu é rejeitado pelo provedor."""
    turno = [
        {"role": "user", "content": "x" * 400},
        {"role": "assistant", "content": None, "tool_calls": [CHAMADA]},
        {"role": "tool", "tool_call_id": "call_1", "content": "y" * 400},
        {"role": "assistant", "content": "pronto"},
    ]
    descartadas, mantidas = s.recortar(turno * 6, teto_tokens=300)
    assert mantidas[0]["role"] == "user"
    assert descartadas
    assert len(descartadas) + len(mantidas) == 24


def test_conversa_sem_turno_que_caiba_mantem_o_ultimo():
    mensagens = [{"role": "user", "content": "x" * 10_000}]
    descartadas, mantidas = s.recortar(mensagens, teto_tokens=10)
    assert mantidas == mensagens and descartadas == []
