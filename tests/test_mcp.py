"""Cliente MCP contra um servidor stdio de verdade (tests/fixtures/mcp_servidor_falso.py).

Sem mock do protocolo: o teste sobe o processo, faz o handshake, lista e chama tools. É o mesmo
caminho que o chat usa com o Mirante, trocando só o servidor.
"""

import sys
from pathlib import Path

import pytest

from hermes.agent import mcp_client
from hermes.agent.registry import TOOLS, Registry
from hermes.run_status import RunStatus

SERVIDOR = Path(__file__).parent / "fixtures" / "mcp_servidor_falso.py"


def _servidor(tools=("news_today", "search_news"), extra=(), timeout=20.0):
    return mcp_client.Servidor(
        nome="mirante", comando=(sys.executable, str(SERVIDOR), *extra), tools=tuple(tools),
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def remotas(tmp_path_factory):
    """Descobre uma vez por módulo: cada processo leva ~1 s para subir."""
    status = RunStatus()
    log_dir = tmp_path_factory.mktemp("logs")
    tools = mcp_client.descobrir([_servidor()], log_dir, {t.nome for t in TOOLS}, status)
    return {t.nome: t for t in tools}, status, log_dir


# -------------------------------------------------------------------- config


def test_config_ausente_e_nenhum_servidor(tmp_path):
    assert mcp_client.carregar(tmp_path / "mcp.yaml") == []


@pytest.mark.parametrize("conteudo, erro", [
    ("servidores:\n  - {nome: a, comando: [x]}\n", "`tools` é obrigatório"),
    ("servidores:\n  - {nome: a, comando: 'uv run x', tools: [t]}\n", "lista"),
    ("servidores:\n  - {nome: a, comando: [x], tools: [t]}\n  - {nome: a, comando: [x], tools: [t]}\n",
     "repetido"),
])
def test_config_invalida(tmp_path, conteudo, erro):
    caminho = tmp_path / "mcp.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(mcp_client.ConfigMCPInvalida, match=erro):
        mcp_client.carregar(caminho)


def test_til_no_comando_e_expandido(tmp_path):
    caminho = tmp_path / "mcp.yaml"
    caminho.write_text("servidores:\n  - {nome: a, comando: [uv, run, --project, ~/x], tools: [t]}\n")
    (servidor,) = mcp_client.carregar(caminho)
    assert servidor.comando[3] == str(Path("~/x").expanduser())


# ------------------------------------------------------------------ descoberta


def test_so_registra_a_allowlist(remotas):
    tools, status, _ = remotas
    assert set(tools) == {"news_today", "search_news"}  # apagar_tudo e quebra ficam de fora
    assert status.warnings == []
    assert tools["news_today"].descricao.startswith("[MCP mirante]")
    assert tools["search_news"].parametros["properties"]["consulta"]["type"] == "string"


def test_stderr_do_servidor_vai_para_o_log(remotas):
    _, _, log_dir = remotas
    assert (log_dir / "mcp-mirante.log").exists()


def test_allowlist_com_tool_inexistente_e_colisao_viram_aviso(tmp_path):
    status = RunStatus()
    tools = mcp_client.descobrir(
        [_servidor(tools=("news_today", "nao_existe"))], tmp_path, {"news_today"}, status
    )
    assert tools == []
    assert any("nao_existe" in a for a in status.warnings)
    assert any("colide" in a for a in status.warnings)


def test_servidor_que_nao_sobe_nao_derruba_o_chat(tmp_path):
    status = RunStatus()
    tools = mcp_client.descobrir([_servidor(extra=("--morrer",), timeout=10)], tmp_path, set(), status)
    assert tools == []
    assert any("MCP: `mirante`" in a for a in status.warnings)


def test_comando_inexistente_vira_aviso(tmp_path):
    servidor = mcp_client.Servidor(nome="x", comando=("comando-que-nao-existe-hermes",), tools=("t",))
    status = RunStatus()
    assert mcp_client.descobrir([servidor], tmp_path, set(), status) == []
    assert status.warnings


# ------------------------------------------------------------------- chamadas


def test_chamada_pelo_registry_devolve_dado_estruturado(remotas, banco):
    tools, _, _ = remotas
    registry = Registry(conn=banco, tools=TOOLS + tuple(tools.values()))

    r = registry.dispatch("news_today", {"limite": 1})

    assert r["ok"] is True
    assert r["data"] == [{"titulo": "Selic mantida em 15%", "fonte": "Valor", "data": "2026-09-22",
                          "relevancia": 4}]


def test_argumentos_chegam_ao_servidor(remotas, banco):
    tools, _, _ = remotas
    registry = Registry(conn=banco, tools=tuple(tools.values()))
    r = registry.dispatch("search_news", '{"consulta": "saúde"}')
    assert [a["titulo"] for a in r["data"]] == ["Operadoras de saúde ampliam telemedicina"]


def test_erro_da_tool_remota_volta_como_falha_mcp(banco, tmp_path):
    (quebra,) = mcp_client.descobrir([_servidor(tools=("quebra",))], tmp_path, set(), RunStatus())
    r = Registry(conn=banco, tools=(quebra,)).dispatch("quebra", {})
    assert r["error"]["code"] == "falha_mcp"
    assert "devolveu erro" in r["error"]["message"]


def test_tool_fora_da_allowlist_nao_e_chamavel(remotas, banco):
    tools, _, _ = remotas
    r = Registry(conn=banco, tools=TOOLS + tuple(tools.values())).dispatch("apagar_tudo", {})
    assert r["error"]["code"] == "tool_desconhecida"
