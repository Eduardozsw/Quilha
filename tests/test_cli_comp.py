import pytest
from typer.testing import CliRunner

from hermes.cli import app
from hermes.db import store

runner = CliRunner()


@pytest.fixture
def projeto(vault, seed_yaml, tmp_path):
    """Banco com o vault indexado e a taxonomia carregada, pela própria CLI."""
    db = tmp_path / "hermes.db"
    assert runner.invoke(app, ["index", "--vault", str(vault), "--db", str(db)]).exit_code == 0
    assert (
        runner.invoke(
            app, ["comp", "seed", "--arquivo", str(seed_yaml), "--db", str(db)]
        ).exit_code
        == 0
    )
    return db


def _ultimo_run(db):
    conn = store.connect(db)
    try:
        return dict(conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone())
    finally:
        conn.close()


def test_seed_e_list(projeto):
    resultado = runner.invoke(app, ["comp", "list", "--db", str(projeto)])
    assert resultado.exit_code == 0
    assert "python" in resultado.stdout
    assert _ultimo_run(projeto)["comando"] == "comp seed"


def test_list_sem_taxonomia(tmp_path):
    resultado = runner.invoke(app, ["comp", "list", "--db", str(tmp_path / "vazio.db")])
    assert resultado.exit_code == 0
    assert "comp seed" in resultado.stdout


def test_assess_sem_evidencia_e_recusado_e_vira_run_failed(projeto):
    resultado = runner.invoke(
        app, ["comp", "assess", "python", "2", "-j", "uso todo dia", "--db", str(projeto)]
    )
    assert resultado.exit_code == 1
    assert "recusado" in resultado.stdout
    run = _ultimo_run(projeto)
    assert run["comando"] == "comp assess" and run["status"] == "failed"


def test_evidencia_e_assess_completam_o_ciclo(projeto):
    ligar = runner.invoke(
        app, ["comp", "evidence", "python", "pipeline", "--db", str(projeto)]
    )
    assert ligar.exit_code == 0
    assert "ligado" in ligar.stdout

    avaliar = runner.invoke(
        app, ["comp", "assess", "python", "2", "-j", "escrevi o pipeline", "--db", str(projeto)]
    )
    assert avaliar.exit_code == 0
    assert "nível 2" in avaliar.stdout
    assert _ultimo_run(projeto)["status"] == "success"


def test_evidencia_com_block_id_inexistente(projeto):
    resultado = runner.invoke(
        app, ["comp", "evidence", "python", "nao-existe", "--db", str(projeto)]
    )
    assert resultado.exit_code == 1
    assert "quilha index" in resultado.stdout


def test_show_lista_evidencias(projeto):
    runner.invoke(app, ["comp", "evidence", "python", "operacao", "--db", str(projeto)])
    resultado = runner.invoke(app, ["comp", "show", "python", "--db", str(projeto)])
    assert resultado.exit_code == 0
    assert "operacao" in resultado.stdout


def test_show_competencia_inexistente(projeto):
    resultado = runner.invoke(app, ["comp", "show", "cobol", "--db", str(projeto)])
    assert resultado.exit_code == 1


def test_coverage_mostra_lacunas(projeto):
    runner.invoke(app, ["comp", "evidence", "python", "pipeline", "--db", str(projeto)])
    runner.invoke(
        app, ["comp", "assess", "python", "2", "-j", "escrevi o pipeline", "--db", str(projeto)]
    )
    resultado = runner.invoke(app, ["comp", "coverage", "--db", str(projeto)])
    assert resultado.exit_code == 0
    assert "1 de 3" in resultado.stdout
    assert "sql" in resultado.stdout


def test_niveis_documenta_a_escala():
    resultado = runner.invoke(app, ["comp", "niveis"])
    assert resultado.exit_code == 0
    assert "período" in resultado.stdout


def test_stats_mostra_competencias(projeto):
    resultado = runner.invoke(app, ["stats", "--db", str(projeto)])
    assert resultado.exit_code == 0
    assert "prontas para o currículo" in resultado.stdout


def test_desligar_avisa_que_o_nivel_ficou_sem_base(projeto):
    runner.invoke(app, ["comp", "evidence", "python", "pipeline", "--db", str(projeto)])
    runner.invoke(app, ["comp", "assess", "python", "2", "-j", "escrevi o pipeline", "--db", str(projeto)])
    resultado = runner.invoke(app, ["comp", "evidence", "python", "pipeline", "--remover", "--db", str(projeto)])
    assert resultado.exit_code == 0
    assert "Nível 2 fica sem evidência suficiente" in resultado.stdout
