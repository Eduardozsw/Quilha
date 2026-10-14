import json
from types import SimpleNamespace

import pytest

from hermes.agent.registry import Registry
from hermes.config import load_config
from hermes.domain import competencias
from hermes.domain import perfil as perfil_mod


def _resposta_json(texto):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=texto, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


@pytest.fixture
def pronto(banco, vault, monkeypatch, tmp_path):
    """python em nível 2 com evidência, Perfil.md no vault e a config apontando para tudo isso."""
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setenv("HERMES_SAIDA", str(tmp_path / "out"))
    return Registry(conn=banco, cfg=load_config())


@pytest.fixture
def provedor(mocker):
    import litellm

    mocker.patch.object(litellm, "completion_cost", return_value=0.0005)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["response_format"])
    return mocker.patch.object(litellm, "completion")


def test_cv_generate_devolve_a_versao_de_cada_idioma(pronto, provedor):
    provedor.return_value = _resposta_json('{"resumo": "r", "bullets": {}}')

    r = pronto.dispatch("cv_generate", {"idiomas": ["pt", "en"]})

    assert r["ok"], r
    versoes = r["data"]["versoes"]
    assert [v["idioma"] for v in versoes] == ["pt", "en"]
    assert len({v["versao_id"] for v in versoes}) == 2
    assert all(v["markdown"].strip() for v in versoes)
    json.dumps(r["data"])  # vai para o cliente MCP: nada de Path


def test_cv_pdf_gera_o_arquivo(pronto, provedor):
    provedor.return_value = _resposta_json('{"resumo": "r", "bullets": {}}')
    versao = pronto.dispatch("cv_generate", {})["data"]["versoes"][0]["versao_id"]

    r = pronto.dispatch("cv_pdf", {"versao_id": versao})

    assert r["ok"], r
    assert r["data"]["caminho"].endswith(".pdf") and r["data"]["paginas"] >= 1


def test_cv_generate_sem_fato_e_regra_violada(banco, monkeypatch, vault):
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))
    r = Registry(conn=banco, cfg=load_config()).dispatch("cv_generate", {})
    assert r["error"]["code"] == "regra_violada"


def test_cv_profiles_sem_arquivo_e_lista_vazia(banco):
    r = Registry(conn=banco, cfg=load_config()).dispatch("cv_profiles", {})
    assert r == {"ok": True, "data": []}
