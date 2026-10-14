from typer.testing import CliRunner

from hermes.cli import app
from hermes.config import load_config
from hermes.db import store
from hermes.domain.configuracao import arquivo_env

runner = CliRunner()


def _semeia(monkeypatch, seed_yaml, tmp_path):
    monkeypatch.setenv("HERMES_COMPETENCIAS", str(seed_yaml))
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))


def test_init_cria_o_vault_de_exemplo_e_indexa(tmp_path, monkeypatch, seed_yaml):
    _semeia(monkeypatch, seed_yaml, tmp_path)
    vault = tmp_path / "meu-vault"

    resultado = runner.invoke(app, ["init", "--vault", str(vault), "--sem-llm"], input="y\n")

    assert resultado.exit_code == 0, resultado.output
    assert (vault / "Carreira" / "Projetos" / "Projeto Exemplo.md").is_file()
    conn = store.connect(tmp_path / "hermes.db")
    assert conn.execute("SELECT count(*) FROM competencies").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM facts").fetchone()[0] == 2
    assert load_config().vault_path == vault
    assert "claude mcp add quilha" in resultado.output


def test_init_num_vault_existente_nao_toca_nas_notas(tmp_path, monkeypatch, seed_yaml, vault):
    _semeia(monkeypatch, seed_yaml, tmp_path)
    antes = {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}

    for _ in range(2):  # rodar de novo não muda nada
        resultado = runner.invoke(app, ["init", "--vault", str(vault), "--sem-llm"])
        assert resultado.exit_code == 0, resultado.output

    assert {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")} == antes
    conn = store.connect(tmp_path / "hermes.db")
    assert conn.execute("SELECT count(*) FROM competencies").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM facts").fetchone()[0] == 4


def test_init_recusa_criar_vault_sem_confirmacao(tmp_path, monkeypatch, seed_yaml):
    _semeia(monkeypatch, seed_yaml, tmp_path)
    vault = tmp_path / "vazio"

    resultado = runner.invoke(app, ["init", "--vault", str(vault), "--sem-llm"], input="n\n")

    assert resultado.exit_code == 1
    assert not (vault / "Carreira").exists()


def test_init_grava_o_llm_quando_pedido(tmp_path, monkeypatch, seed_yaml, vault):
    _semeia(monkeypatch, seed_yaml, tmp_path)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    resultado = runner.invoke(app, ["init", "--vault", str(vault)], input="y\ngpt-4o-mini\nchave-falsa\n")

    assert resultado.exit_code == 0, resultado.output
    env = arquivo_env().read_text(encoding="utf-8")
    assert "LLM_MODEL=gpt-4o-mini" in env and "LLM_API_KEY=" in env
    assert "chave-falsa" not in resultado.output
