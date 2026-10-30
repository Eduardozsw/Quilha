"""Estado da coleta para Configurações: fontes do YAML com a fila e a última coleta."""

import pytest
from fastapi.testclient import TestClient

from hermes.api.app import criar_app
from hermes.config import load_config
from hermes.db import store
from hermes.run_status import RunStatus

FONTES = """
fontes:
  - tipo: gupy
    board: maresaude
    empresa: Maré Saúde
  - tipo: lever
    board: vela
    empresa: Vela Pagamentos
    intervalo_h: 12
"""


@pytest.fixture
def fontes(monkeypatch, tmp_path):
    caminho = tmp_path / "fontes.yaml"
    monkeypatch.setenv("HERMES_FONTES", str(caminho))
    return caminho


@pytest.fixture
def api(fontes, tmp_path):
    cfg = load_config(vault_path=tmp_path / "v", db_path=tmp_path / "hermes.db")
    return TestClient(criar_app(cfg, "t"), headers={"X-Hermes-Token": "t"})


def test_sem_fontes_yaml(api, fontes):
    r = api.get("/api/coletor/estado").json()
    assert r == {"caminho": str(fontes), "existe": False, "erro": None, "fontes": [], "ultima": None}


def test_criar_a_partir_do_exemplo_uma_vez(api, fontes):
    r = api.post("/api/coletor/fontes/exemplo")
    assert r.status_code == 200 and r.json() == {"caminho": str(fontes)}
    assert "fontes:" in fontes.read_text(encoding="utf-8")
    assert api.post("/api/coletor/fontes/exemplo").status_code == 409


@pytest.mark.parametrize("conteudo,trecho", [
    ("fontes:\n  - tipo: workday\n    board: x\n", "workday"),
    ("fontes: [\n", ""),
    ("apenas texto\n", ""),
    ("- a\n- b\n", ""),
    ("fontes:\n  - {tipo: lever, board: x, intervalo_h: abc}\n", ""),
    ("filtro: oi\nfontes:\n  - {tipo: lever, board: x}\n", ""),
])
def test_fontes_yaml_invalido_vira_erro_e_nao_500(api, fontes, conteudo, trecho):
    """Review Focus 3."""
    fontes.write_text(conteudo, encoding="utf-8")
    r = api.get("/api/coletor/estado")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["existe"] is True and corpo["fontes"] == [] and trecho in corpo["erro"] and corpo["erro"]


def test_fontes_com_a_fila_e_a_ultima_coleta(api, fontes, tmp_path):
    fontes.write_text(FONTES, encoding="utf-8")
    conn = store.connect(tmp_path / "hermes.db")
    conn.execute("INSERT INTO fila_coleta (fonte, board, estado, tentativas, proximo_em, ultimo_erro, atualizado_em)"
                 " VALUES ('gupy', 'maresaude', 'falhou', 3, '2026-10-10T13:00:00+00:00', 'HTTP 404',"
                 " '2026-10-10T10:00:00+00:00')")
    inicio = "2026-10-10T07:12:00+00:00"
    store.record_run(conn, "job collect", inicio, RunStatus(), "partial")
    store.record_run(conn, "job collect", "2026-10-10T09:00:00+00:00", RunStatus(), "failed", error="x")
    for board, novas in (("maresaude", 0), ("vela", 3)):
        conn.execute("INSERT INTO coletas (execucao, fonte, board, status, vagas_novas, duracao_ms, criado_em)"
                     " VALUES (?, 'lever', ?, 'ok', ?, 10, ?)", (inicio, board, novas, inicio))
    conn.commit()
    conn.close()
    r = api.get("/api/coletor/estado").json()
    assert r["erro"] is None and r["ultima"] == {"quando": inicio, "vagas_novas": 3}
    mare, vela = r["fontes"]
    assert mare["empresa"] == "Maré Saúde" and mare["estado"] == "falhou" and mare["ultimo_erro"] == "HTTP 404"
    assert mare["tentativas"] == 3 and mare["tipo"] == "gupy"
    assert vela["estado"] == "nova" and vela["intervalo_h"] == 12


def test_fontes_yaml_em_latin1_vira_erro(api, fontes):
    """Revisão final: arquivo salvo em Latin-1 também não pode dar 500."""
    fontes.write_bytes("fontes:\n  - {tipo: gupy, board: mare, empresa: Maré}\n".encode("latin-1"))
    r = api.get("/api/coletor/estado")
    assert r.status_code == 200 and r.json()["erro"]
