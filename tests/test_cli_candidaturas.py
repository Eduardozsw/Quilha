import pytest
from typer.testing import CliRunner

from hermes.cli import app
from hermes.config import load_config
from hermes.db import store
from hermes.domain import candidaturas as cand

runner = CliRunner()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    yaml_cv = tmp_path / "curriculos.yaml"
    yaml_cv.write_text("perfis:\n  - slug: engenharia-ia\n    cargo: {pt: Eng. de IA, en: AI Engineer}\n",
                       encoding="utf-8")
    monkeypatch.setenv("HERMES_CURRICULOS", str(yaml_cv))
    return load_config()


def test_app_add_e_notas_sem_dados(cfg):
    r = runner.invoke(app, ["app", "add", "--empresa", "Quartzo", "--perfil", "engenharia-ia",
                            "--data", "2026-08-01"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["app", "notas"])
    assert r.exit_code == 0
    assert "engenharia-ia" in r.output and "—" in r.output and "faltam 9" in r.output


def test_app_add_perfil_inexistente_recusa(cfg):
    r = runner.invoke(app, ["app", "add", "--empresa", "Quartzo", "--perfil", "nao-existe"])
    assert r.exit_code == 1
    assert "engenharia-ia" in r.output  # diz quais existem


def test_app_perfil_resolve_pingada(cfg):
    conn = store.connect(cfg.db_path)
    e = cand.inserir_email(conn, {"gmail_id": "g", "recebido_em": "2026-09-01T00:00:00+00:00", "de": "x",
                                  "assunto": "y", "final": "inscricao_confirmada", "empresa_extraida": "Orbital"})
    cid = cand.ligar(conn, e)
    conn.close()
    assert "Orbital" in runner.invoke(app, ["app", "list", "--pingadas"]).output
    r = runner.invoke(app, ["app", "perfil", str(cid), "geral"])
    assert r.exit_code == 0, r.output
    assert "Orbital" not in runner.invoke(app, ["app", "list", "--pingadas"]).output


def test_email_pendentes_e_corrigir(cfg):
    conn = store.connect(cfg.db_path)
    e = cand.inserir_email(conn, {"gmail_id": "g", "recebido_em": "2026-09-01T00:00:00+00:00", "de": "x",
                                  "assunto": "Próxima etapa", "final": "revisar", "empresa_extraida": "Quartzo"})
    conn.close()
    assert "Próxima etapa" in runner.invoke(app, ["email", "pendentes"]).output
    r = runner.invoke(app, ["email", "corrigir", str(e), "avanco"])
    assert r.exit_code == 0, r.output
    assert "Quartzo" in runner.invoke(app, ["app", "list"]).output
    r = runner.invoke(app, ["email", "corrigir", str(e), "qualquer"])
    assert r.exit_code == 1


def test_email_sync_com_jev_sem_chave_recusa_antes_do_gmail(cfg, monkeypatch):
    monkeypatch.setenv("EMAIL_CLASSIFICADOR", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    r = runner.invoke(app, ["email", "sync"])
    assert r.exit_code == 1
    assert "TYPESAFE_API_KEY" in r.output
