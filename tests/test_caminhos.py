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


def test_instalado_como_pacote_usa_a_pasta_de_dados_do_usuario(sem_home, monkeypatch, tmp_path):
    """`uv tool install` sem `--editable`: o código mora no venv da ferramenta, que some a cada atualização."""
    monkeypatch.setattr(caminhos, "PROJECT_ROOT", tmp_path / "site-packages")
    monkeypatch.setattr("platformdirs.user_data_dir", lambda app, appauthor=None: str(tmp_path / app))
    assert caminhos.instalado()
    assert caminhos.base() == tmp_path / "quilha"


def test_padroes_vao_dentro_do_pacote():
    """O wheel leva os padrões em `hermes/dados`, como o binário congelado, para `preparar` ter de onde copiar."""
    import tomllib

    pyproject = tomllib.loads((caminhos.PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    incluidos = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert {incluidos[nome] for nome in caminhos.PADROES} == {f"hermes/dados/{nome}" for nome in caminhos.PADROES}


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
