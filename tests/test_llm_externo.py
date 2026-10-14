import pytest

from hermes import llm
from hermes.agent.registry import Registry, Tool


def test_sem_resposta_pede_o_texto_sem_chamar_o_provedor():
    with llm.respostas_externas({}):
        with pytest.raises(llm.PrecisaDeTexto) as pedido:
            llm.complete("sistema", "entrada")
    assert pedido.value.system == "sistema"
    assert pedido.value.user == "entrada"
    assert pedido.value.chave == llm.chave_do_pedido("sistema", "entrada")


def test_com_resposta_devolve_ela_no_lugar_do_provedor():
    chave = llm.chave_do_pedido("s", "u")
    with llm.respostas_externas({chave: '{"ok": 1}'}):
        assert llm.complete("s", "u", json_mode=True) == '{"ok": 1}'


def test_pedido_diferente_nao_usa_resposta_de_outro():
    with llm.respostas_externas({llm.chave_do_pedido("s", "u"): "x"}):
        with pytest.raises(llm.PrecisaDeTexto):
            llm.complete("s", "outra entrada")


def test_fora_do_modo_externo_chama_o_provedor():
    """O conftest troca `litellm.completion` por um que falha: prova que o caminho normal não mudou."""
    with pytest.raises(Exception, match="LLM de verdade"):
        llm.complete("s", "u")


def test_registry_deixa_o_pedido_subir(conn):
    def usa_modelo(conn, status=None, model=None):
        return llm.complete("s", "u")

    tool = Tool(nome="t", descricao="d", parametros={"type": "object", "properties": {}},
                funcao=usa_modelo, injeta=("status", "model"))
    registry = Registry(conn=conn, tools=(tool,))
    with llm.respostas_externas({}):
        with pytest.raises(llm.PrecisaDeTexto):
            registry.dispatch("t", {})


def test_litellm_nao_imprime_ajuda_no_stdout():
    """`mcp serve` usa o stdout para o protocolo: o print de "Give Feedback / Get Help" do LiteLLM o quebraria.
    Em subprocesso porque o conftest troca `_litellm` por um falso."""
    import subprocess
    import sys

    saida = subprocess.run([sys.executable, "-c", "from hermes import llm; print(llm._litellm().suppress_debug_info)"],
                           capture_output=True, text=True, check=True).stdout
    assert saida.strip().splitlines()[-1] == "True"
