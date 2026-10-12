"""Nota de competências gerada no vault e backup do banco."""

import sqlite3

import pytest
from typer.testing import CliRunner

from hermes.cli import app
from hermes.db import store
from hermes.domain import competencias
from hermes.vault import writer

runner = CliRunner()


# --- nota gerada ---------------------------------------------------------------


def test_exportar_mostra_nivel_justificativa_e_link_para_o_fato(banco):
    competencias.ligar_evidencia(banco, "python", "pipeline")
    competencias.avaliar(banco, "python", 2, "uso no Mirante")

    texto = competencias.exportar_markdown(banco)

    assert texto.startswith("---\ngerado_por: hermes comp export\n")
    assert "| python | Python | 2 | 1 | ok |" in texto
    assert "uso no Mirante" in texto
    # link do Obsidian direto para o bloco, sem a extensão .md
    assert "[[Carreira/Projetos/Mirante#^pipeline|Mirante ^pipeline]]" in texto
    # competência sem avaliação aparece como lacuna, sem link
    assert "| sql | SQL | — | 0 | nunca avaliada |" in texto


def test_exportar_marca_evidencia_orfa(banco):
    competencias.ligar_evidencia(banco, "python", "pipeline")
    banco.execute("DELETE FROM facts WHERE block_id = 'pipeline'")

    texto = competencias.exportar_markdown(banco)

    assert "fato sumiu do vault" in texto


def test_substituir_gerada_cria_e_reescreve(tmp_path):
    conteudo = "---\ngerado_por: hermes comp export\n---\n\nv1\n"
    r = writer.substituir_gerada(tmp_path, "Competencias", conteudo)
    assert r["criada"] is True

    writer.substituir_gerada(tmp_path, "Competencias", conteudo.replace("v1", "v2"))
    assert (tmp_path / "Competencias.md").read_text(encoding="utf-8").endswith("v2\n")


def test_substituir_gerada_nao_toca_nota_escrita_a_mao(tmp_path):
    (tmp_path / "Competencias.md").write_text("# minhas anotações\n", encoding="utf-8")

    with pytest.raises(writer.EscritaRecusada, match="não foi gerada pelo Hermes"):
        writer.substituir_gerada(tmp_path, "Competencias", "---\ngerado_por: hermes comp export\n---\n")

    assert (tmp_path / "Competencias.md").read_text(encoding="utf-8") == "# minhas anotações\n"


def test_substituir_gerada_exige_a_marca_no_conteudo(tmp_path):
    with pytest.raises(writer.EscritaRecusada):
        writer.substituir_gerada(tmp_path, "Competencias", "# sem marca\n")


@pytest.mark.parametrize("nome", ["../fora", "Carreira/x", ".oculta", ""])
def test_substituir_gerada_recusa_nome_invalido(tmp_path, nome):
    with pytest.raises(writer.EscritaRecusada):
        writer.substituir_gerada(tmp_path, nome, "---\ngerado_por: hermes comp export\n---\n")


# --- backup --------------------------------------------------------------------


def test_backup_copia_o_banco_e_mantem_so_os_ultimos(banco, tmp_path):
    competencias.ligar_evidencia(banco, "python", "pipeline")
    destino = tmp_path / "backups"

    caminhos = [store.backup(banco, destino, manter=2, sufixo=str(i)) for i in range(3)]

    restantes = sorted(p.name for p in destino.glob("hermes-*.db"))
    assert restantes == sorted(p.name for p in caminhos[1:])
    copia = sqlite3.connect(caminhos[-1])
    try:
        assert copia.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    finally:
        copia.close()


# --- CLI -----------------------------------------------------------------------


@pytest.fixture
def projeto(vault, seed_yaml, tmp_path):
    db = tmp_path / "hermes.db"
    assert runner.invoke(app, ["index", "--vault", str(vault), "--db", str(db)]).exit_code == 0
    assert runner.invoke(
        app, ["comp", "seed", "--arquivo", str(seed_yaml), "--db", str(db)]
    ).exit_code == 0
    return db


def test_cli_comp_export_escreve_no_vault(projeto, vault):
    resultado = runner.invoke(
        app, ["comp", "export", "--vault", str(vault), "--db", str(projeto)]
    )
    assert resultado.exit_code == 0, resultado.stdout
    assert "gerado_por: hermes" in (vault / "Competencias.md").read_text(encoding="utf-8")


def test_cli_assess_atualiza_a_nota_se_ela_ja_existe(projeto, vault, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(vault))
    runner.invoke(app, ["comp", "export", "--db", str(projeto)])
    runner.invoke(app, ["comp", "evidence", "python", "pipeline", "--db", str(projeto)])

    resultado = runner.invoke(
        app, ["comp", "assess", "python", "2", "-j", "uso no Mirante", "--db", str(projeto)]
    )

    assert resultado.exit_code == 0, resultado.stdout
    assert "uso no Mirante" in (vault / "Competencias.md").read_text(encoding="utf-8")


def test_cli_assess_nao_cria_a_nota_sozinho(projeto, vault, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(vault))
    runner.invoke(app, ["comp", "evidence", "python", "pipeline", "--db", str(projeto)])
    runner.invoke(app, ["comp", "assess", "python", "2", "-j", "x", "--db", str(projeto)])

    assert not (vault / "Competencias.md").exists()


def test_cli_backup(projeto, tmp_path):
    destino = tmp_path / "copias"
    resultado = runner.invoke(app, ["backup", "--db", str(projeto), "--destino", str(destino)])
    assert resultado.exit_code == 0, resultado.stdout
    assert len(list(destino.glob("hermes-*.db"))) == 1
