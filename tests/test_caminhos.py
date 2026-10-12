import sys

import pytest

from hermes import caminhos
from hermes.config import load_config


@pytest.fixture
def sem_home(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)


def test_checkout_usa_a_raiz_do_projeto(sem_home):
    assert caminhos.base() == caminhos.PROJECT_ROOT
    assert caminhos.preparar() == []  # nunca copia nada para dentro do repositório


def test_hermes_home_vence(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_DB", raising=False)
    assert caminhos.base() == tmp_path
    assert load_config().db_path == tmp_path / "data" / "hermes.db"


def test_congelado_usa_a_pasta_de_dados_do_usuario(sem_home, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("platformdirs.user_data_dir", lambda app, appauthor=None: str(tmp_path / app))
    assert caminhos.base() == tmp_path / "quilha"


def test_env_da_base_e_lido(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_MODEL", raising=False)
    (tmp_path / ".env").write_text("LLM_MODEL=modelo-da-base\n", encoding="utf-8")
    assert load_config().llm_model == "modelo-da-base"


def test_preparar_copia_padroes_e_nao_sobrescreve(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "competencias.yaml").write_text("competencias: []\n", encoding="utf-8")

    copiados = {p.name for p in caminhos.preparar()}

    assert "competencias.yaml" not in copiados
    assert (tmp_path / "competencias.yaml").read_text(encoding="utf-8") == "competencias: []\n"
    assert {"curriculos.example.yaml", "fontes.example.yaml"} <= copiados
    assert caminhos.preparar() == []  # segunda vez não há o que copiar


def test_diagnostico_passa_sem_llm_e_sem_banco_real(monkeypatch, tmp_path):
    from hermes.domain import diagnostico

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    itens = diagnostico.rodar(load_config())
    assert all(i["ok"] for i in itens), itens
    assert not (tmp_path / "data").exists()  # o schema foi testado num banco temporário
