import asyncio
import json

import pytest
from mcp import Client

from hermes.config import load_config
from hermes.mcp_server import Quilha, criar_servidor


@pytest.fixture
def cfg(banco, vault, tmp_path, monkeypatch):
    """O servidor abre o mesmo arquivo que a fixture `banco` (como app + MCP juntos)."""
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.delenv("LLM_MODEL", raising=False)
    return load_config()


def _com_cliente(cfg, operacao):
    async def rodar():
        async with Client(criar_servidor(cfg)) as cliente:
            return await operacao(cliente)
    return asyncio.run(rodar())


def test_lista_as_tools_com_leitura_e_escrita_marcadas(cfg):
    tools = {t.name: t for t in _com_cliente(cfg, lambda c: c.list_tools()).tools}  # noqa: E731

    assert {"vault_search_facts", "parse_job", "cv_generate", "cv_pdf", "submit_draft"} <= set(tools)
    assert tools["vault_search_facts"].annotations.read_only_hint is True
    assert tools["link_evidence"].annotations.read_only_hint is False
    assert tools["link_evidence"].annotations.destructive_hint is False


def test_instrucoes_vao_no_handshake(cfg):
    async def operacao(c):
        return c.instructions
    assert "referencia" in (_com_cliente(cfg, operacao) or "")


def test_leitura_de_ponta_a_ponta(cfg):
    r = _com_cliente(cfg, lambda c: c.call_tool("vault_search_facts", {"query": "pipeline"}))
    assert not r.is_error
    assert any("pipeline" in json.dumps(f) for f in json.loads(r.content[0].text))


def test_escrita_recusada_pela_regra_volta_como_erro(cfg):
    r = _com_cliente(cfg, lambda c: c.call_tool(
        "assess_competency", {"slug": "python", "nivel": 3, "justificativa": "sem prova"}))
    assert r.is_error
    assert json.loads(r.content[0].text)["code"] == "regra_violada"


def test_bug_numa_tool_vira_erro_interno_e_o_servidor_segue(cfg, monkeypatch):
    from hermes import mcp_server
    from hermes.agent.registry import TOOLS, Tool

    def quebra(conn):
        raise KeyError("quebrou")

    monkeypatch.setattr(mcp_server, "TOOLS", TOOLS + (Tool(nome="quebra", descricao="d",
                        parametros={"type": "object", "properties": {}}, funcao=quebra),))
    quilha = Quilha(cfg)
    assert quilha.chamar("quebra", {})["error"]["code"] == "erro_interno"
    assert quilha.chamar("list_competencies", {})["ok"]


def test_sem_competencias_pede_init(cfg, conn):
    conn.execute("DELETE FROM competencies")
    conn.commit()
    r = Quilha(cfg).chamar("list_competencies", {})
    assert r["error"]["code"] == "nao_configurado"
    assert "quilha init" in r["error"]["message"]


def test_nota_editada_entre_chamadas_aparece(cfg, vault):
    quilha = Quilha(cfg)
    assert not quilha.chamar("vault_search_facts", {"query": "kubernetes"})["data"]

    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    texto = nota.read_text(encoding="utf-8")  # o fato entra na seção ## Fatos, antes de ## Limitações
    nota.write_text(texto.replace("## Limitações", "- Cluster kubernetes de teste #devops ^k8s\n\n## Limitações"),
                    encoding="utf-8")

    assert quilha.chamar("vault_search_facts", {"query": "kubernetes"})["data"]


def test_termo_da_denylist_no_vault_vira_aviso_e_mantem_o_indice(cfg, vault, monkeypatch, tmp_path):
    deny = tmp_path / "denylist.yaml"
    deny.write_text("termos: [ClienteSecreto]\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_DENYLIST", str(deny))
    quilha = Quilha(load_config())
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    texto = nota.read_text(encoding="utf-8")
    nota.write_text(texto.replace("## Limitações", "- Projeto para o ClienteSecreto ^segredo\n\n## Limitações"),
                    encoding="utf-8")

    r = quilha.chamar("vault_search_facts", {"query": "pipeline"})

    assert r["ok"] and r["data"]  # índice anterior continua
    assert any("denylist" in a for a in r.get("avisos", []))


def test_teto_de_custo_vale_para_o_servidor_inteiro(cfg, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "chave-de-teste")
    monkeypatch.setenv("HERMES_MAX_COST_USD", "0.50")
    quilha = Quilha(load_config())
    quilha.gasto = 0.51  # chamadas anteriores deste processo

    assert quilha.chamar("parse_job", {"texto": "x" * 300})["error"]["code"] == "teto_de_custo"
    assert quilha.chamar("list_competencies", {})["ok"]  # tool sem modelo não é barrada


def test_cada_chamada_grava_uma_execucao(cfg, conn):
    Quilha(cfg).chamar("list_competencies", {})
    assert conn.execute("SELECT comando FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "mcp list_competencies"
