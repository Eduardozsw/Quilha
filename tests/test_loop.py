"""O loop de tool-calling, com `litellm.completion` mockado.

Nenhum teste aqui toca a rede. O que se verifica é o que custa dinheiro quando erra: quantas
chamadas o loop faz, o que ele manda no contexto e quando ele desiste.
"""

from types import SimpleNamespace

import pytest

from hermes.agent import loop, session as agent_session
from hermes.agent.registry import Registry
from hermes.run_status import RunStatus


def tool_call(nome, argumentos="{}", id="call_1"):
    return SimpleNamespace(
        id=id, type="function", function=SimpleNamespace(name=nome, arguments=argumentos)
    )


def resposta(content=None, tool_calls=None, prompt=10, completion=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


@pytest.fixture
def modelo(mocker):
    """Fila de respostas do provedor: cada chamada consome a próxima."""
    import litellm

    mock = mocker.patch.object(litellm, "completion")
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])

    def responder_com(*respostas):
        mock.side_effect = list(respostas)
        return mock

    mock.responder_com = responder_com
    return mock


@pytest.fixture
def cenario(banco, modelo):
    sessao = agent_session.abrir(banco, "gpt-4o-mini")
    status = RunStatus()
    registry = Registry(conn=banco, status=status)
    return SimpleNamespace(
        sessao=sessao, status=status, registry=registry, conn=banco, modelo=modelo
    )


def rodar(cenario, pergunta="e aí?", **kwargs):
    return loop.responder(
        cenario.sessao,
        cenario.registry,
        pergunta,
        status=cenario.status,
        teto_usd=kwargs.pop("teto_usd", 1.0),
        **kwargs,
    )


def test_resposta_direta_encerra_o_turno(cenario):
    cenario.modelo.responder_com(resposta(content="oi"))
    turno = rodar(cenario)
    assert turno.resposta == "oi"
    assert turno.iteracoes == 1
    assert turno.completo
    assert cenario.modelo.call_count == 1


def test_system_e_pergunta_vao_no_contexto(cenario):
    cenario.modelo.responder_com(resposta(content="oi"))
    rodar(cenario, pergunta="quais competências eu tenho?")
    mensagens = cenario.modelo.call_args.kwargs["messages"]
    assert mensagens[0]["role"] == "system"
    assert "vault" in mensagens[0]["content"]
    assert mensagens[-1] == {"role": "user", "content": "quais competências eu tenho?"}


def test_tool_call_e_despachada_e_a_resposta_volta_ao_modelo(cenario):
    cenario.modelo.responder_com(
        resposta(tool_calls=[tool_call("vault_search_facts", '{"query": "pipeline"}')]),
        resposta(content="você tem um pipeline em Python"),
    )
    turno = rodar(cenario)

    assert turno.tools_usadas == ["vault_search_facts"]
    assert turno.resposta == "você tem um pipeline em Python"
    assert turno.iteracoes == 2

    # a segunda chamada levou o resultado da tool
    mensagens = cenario.modelo.call_args.kwargs["messages"]
    tool_msg = [m for m in mensagens if m["role"] == "tool"]
    assert len(tool_msg) == 1
    assert tool_msg[0]["tool_call_id"] == "call_1"
    assert "pipeline" in tool_msg[0]["content"]


def test_cada_tool_call_id_tem_exatamente_uma_resposta(cenario):
    """Invariante que o provedor cobra: sem isso a chamada seguinte é rejeitada."""
    cenario.modelo.responder_com(
        resposta(
            tool_calls=[
                tool_call("list_competencies", "{}", id="a"),
                tool_call("vault_search_facts", '{"query": "sql"}', id="b"),
            ]
        ),
        resposta(content="pronto"),
    )
    rodar(cenario)
    mensagens = cenario.sessao.mensagens()
    pedidos = [c["id"] for m in mensagens if m.get("tool_calls") for c in m["tool_calls"]]
    respostas = [m["tool_call_id"] for m in mensagens if m["role"] == "tool"]
    assert sorted(pedidos) == sorted(respostas) == ["a", "b"]


def test_erro_de_tool_nao_derruba_o_loop(cenario):
    cenario.modelo.responder_com(
        resposta(tool_calls=[tool_call("assess_competency", '{"slug": "cobol", "nivel": 9}')]),
        resposta(content="não consegui, o slug não existe"),
    )
    turno = rodar(cenario)
    assert turno.completo
    assert turno.resposta.startswith("não consegui")
    assert cenario.status.tool_errors == 1
    conteudo = [m for m in cenario.sessao.mensagens() if m["role"] == "tool"][0]["content"]
    assert '"ok": false' in conteudo


def test_duas_falhas_seguidas_da_mesma_tool_encerram_o_turno(cenario):
    ruim = resposta(tool_calls=[tool_call("assess_competency", '{"slug": "cobol", "nivel": 1}')])
    cenario.modelo.responder_com(ruim, ruim, resposta(content="não devia chegar aqui"))
    turno = rodar(cenario)

    assert turno.parou_por == "tool_insistente"
    assert not turno.completo
    assert cenario.modelo.call_count == 2  # não insistiu uma terceira vez
    assert any("duas vezes seguidas" in a for a in cenario.status.warnings)


def test_acertar_a_mesma_tool_zera_o_contador_dela(cenario):
    ruim = resposta(tool_calls=[tool_call("list_competencies", '{"inventado": 1}')])
    bom = resposta(tool_calls=[tool_call("list_competencies", "{}")])
    cenario.modelo.responder_com(ruim, bom, ruim, resposta(content="fim"))
    turno = rodar(cenario)
    assert turno.completo and turno.resposta == "fim"


def test_errar_a_mesma_tool_duas_vezes_conta_mesmo_com_outra_no_meio(cenario):
    """O contador é por tool, não pela posição na sequência: insistir no mesmo erro para o turno,
    ainda que o modelo tenha feito outra coisa entre as duas tentativas."""
    ruim = resposta(tool_calls=[tool_call("assess_competency", '{"slug": "cobol", "nivel": 1}')])
    outra = resposta(tool_calls=[tool_call("list_competencies", "{}")])
    cenario.modelo.responder_com(ruim, outra, ruim, resposta(content="não devia chegar aqui"))
    turno = rodar(cenario)
    assert turno.parou_por == "tool_insistente"


def test_limite_de_iteracoes_corta_o_turno(cenario):
    pede_tool = resposta(tool_calls=[tool_call("list_competencies", "{}")])
    cenario.modelo.responder_com(*[pede_tool] * 20)
    turno = rodar(cenario)

    assert turno.parou_por == "limite_iteracoes"
    assert turno.iteracoes == loop.MAX_ITERACOES
    assert cenario.modelo.call_count == loop.MAX_ITERACOES


def test_teto_de_custo_aborta_antes_de_gastar_mais(cenario):
    pede_tool = resposta(tool_calls=[tool_call("list_competencies", "{}")])
    cenario.modelo.responder_com(*[pede_tool] * 20)
    turno = rodar(cenario, teto_usd=0.0025)  # cada chamada custa 0.001

    assert turno.parou_por == "teto_custo"
    assert cenario.modelo.call_count == 3
    assert any("teto de custo" in a for a in cenario.status.warnings)


def test_custo_desconhecido_nao_impede_a_conversa(cenario, mocker):
    """Modelo local não tem preço na tabela; travar aqui seria proibir o uso dele."""
    import litellm

    mocker.patch.object(litellm, "completion_cost", side_effect=Exception("sem preço"))
    cenario.modelo.responder_com(resposta(content="oi"))
    turno = rodar(cenario, teto_usd=0.0001)
    assert turno.completo
    assert cenario.status.cost_usd is None


def test_resultado_gigante_entra_truncado_mas_valido(cenario):
    import json

    from hermes.db import store

    store.reindex_facts(
        cenario.conn,
        [
            {
                "nota": "Carreira/Projetos/Grande.md",
                "block_id": f"fato-{i}",
                "tipo": "project",
                "entidade": "grande",
                "texto": "x" * 200,
                "tags": [],
            }
            for i in range(100)
        ],
    )
    cenario.modelo.responder_com(
        resposta(tool_calls=[tool_call("vault_search_facts", '{"query": "x", "limite": 50}')]),
        resposta(content="ok"),
    )
    rodar(cenario)
    conteudo = [m for m in cenario.sessao.mensagens() if m["role"] == "tool"][0]["content"]
    assert len(conteudo) < loop.MAX_CHARS_RESULTADO + 500
    assert json.loads(conteudo)["truncado"] is True


def test_historico_longo_vira_resumo_uma_vez_so(cenario):
    for i in range(40):
        cenario.sessao.gravar({"role": "user", "content": f"pergunta {i} " + "x" * 300})
        cenario.sessao.gravar({"role": "assistant", "content": f"resposta {i} " + "y" * 300})

    cenario.modelo.responder_com(
        resposta(content="RESUMO: falamos de carreira"),  # a chamada de resumo
        resposta(content="primeira"),
        resposta(content="segunda"),
    )
    rodar(cenario, pergunta="e agora?", teto_tokens=500)
    assert cenario.sessao.resumo == "RESUMO: falamos de carreira"

    rodar(cenario, pergunta="e depois?", teto_tokens=500)
    assert cenario.modelo.call_count == 3  # resumiu uma vez, não duas

    mensagens = cenario.modelo.call_args.kwargs["messages"]
    assert "RESUMO: falamos de carreira" in mensagens[1]["content"]


def test_falha_ao_resumir_nao_derruba_o_turno(cenario):
    for i in range(40):
        cenario.sessao.gravar({"role": "user", "content": "x" * 400})
    cenario.modelo.responder_com(Exception("provedor fora do ar"), resposta(content="segue"))
    turno = rodar(cenario, teto_tokens=200)
    assert turno.resposta == "segue"
    assert any("resumir" in a for a in cenario.status.warnings)


def test_a_pergunta_e_gravada_mesmo_quando_o_turno_e_cortado(cenario):
    pede_tool = resposta(tool_calls=[tool_call("list_competencies", "{}")])
    cenario.modelo.responder_com(*[pede_tool] * 20)
    rodar(cenario, pergunta="pergunta cara")
    assert cenario.sessao.mensagens()[0] == {"role": "user", "content": "pergunta cara"}


# --- streaming e Parar (V3) ---------------------------------------------------------


def test_texto_da_resposta_sai_em_trechos(cenario):
    cenario.modelo.responder_com(resposta(content="você tem 3"))
    eventos = []
    turno = rodar(cenario, on_evento=lambda t, d: eventos.append((t, d)))
    assert ("trecho", {"texto": "você tem 3"}) in eventos
    assert turno.resposta == "você tem 3"


def test_resultados_das_ferramentas_ficam_no_turno(cenario):
    cenario.modelo.responder_com(
        resposta(tool_calls=[tool_call("list_competencies", "{}")]), resposta(content="pronto"))
    turno = rodar(cenario)
    ((nome, resultado),) = turno.resultados
    assert nome == "list_competencies" and resultado["ok"] is True


def test_parar_no_meio_do_texto_grava_o_parcial(cenario, mocker):
    import threading

    import litellm

    from tests.streaming import chunk

    parar = threading.Event()

    def chunks():
        yield chunk("Olhando as vagas, ")
        parar.set()
        yield chunk("a da Orla.", finish="stop")

    mocker.patch.object(litellm, "completion", return_value=chunks())
    turno = rodar(cenario, parar=parar)
    assert turno.parou_por == "parado" and turno.resposta == "Olhando as vagas, "
    assert cenario.sessao.mensagens()[-1] == {"role": "assistant", "content": "Olhando as vagas, "}


def test_parar_entre_ferramentas_responde_todas_as_chamadas(cenario):
    """Review Focus 1: toda `tool_call` tem resposta `tool`, mesmo as que o Parar pulou."""
    import threading

    parar = threading.Event()
    cenario.modelo.responder_com(resposta(tool_calls=[
        tool_call("list_competencies", "{}", id="c1"), tool_call("list_jobs", "{}", id="c2")]))

    def on_evento(tipo, dados):
        if tipo == "tool_resultado":
            parar.set()

    turno = rodar(cenario, parar=parar, on_evento=on_evento)
    assert turno.parou_por == "parado"
    assert cenario.modelo.call_count == 1
    ferramentas = [m for m in cenario.sessao.mensagens() if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in ferramentas] == ["c1", "c2"]
    assert '"cancelado"' in ferramentas[1]["content"]


def test_parar_antes_da_primeira_chamada_deixa_resposta_vazia_anotavel(cenario):
    """O Parar chegou antes do modelo: o turno tem uma `assistant` vazia (onde o "Parado" fica no histórico),
    que nunca vai ao provedor."""
    import threading

    parar = threading.Event()
    parar.set()
    inicio = cenario.sessao.proximo_idx
    turno = rodar(cenario, parar=parar)
    assert turno.parou_por == "parado" and cenario.modelo.call_count == 0
    assert cenario.sessao.anotar_turno(inicio, {"parado": True}) is True
    assert cenario.sessao.mensagens() == [{"role": "user", "content": "e aí?"}]


def test_stream_que_cai_grava_o_parcial_e_tentar_de_novo_substitui(cenario, mocker):
    import litellm

    from tests.streaming import chunk

    def cai():
        yield chunk("Comparando as vagas, ")
        raise ConnectionError("conexão caiu")

    mocker.patch.object(litellm, "completion", return_value=cai())
    with pytest.raises(ConnectionError):
        rodar(cenario, pergunta="compara as vagas")
    com_meta = cenario.sessao.mensagens_com_meta()
    assert com_meta[-1]["content"] == "Comparando as vagas, " and com_meta[-1]["meta"] == {"interrompido": True}

    cenario.modelo.responder_com(resposta("Resposta inteira."))
    mocker.patch.object(litellm, "completion", cenario.modelo)
    turno = rodar(cenario, pergunta="compara as vagas")
    assert turno.resposta == "Resposta inteira."
    assert cenario.sessao.mensagens() == [{"role": "user", "content": "compara as vagas"},
                                          {"role": "assistant", "content": "Resposta inteira."}]
