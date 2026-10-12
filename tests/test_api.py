"""API local do app desktop: token, leitura e escrita pelas mesmas funções da CLI."""

import pytest
from fastapi.testclient import TestClient

from hermes.api.app import criar_app
from hermes.config import load_config
from hermes.db import store
from hermes.domain import competencias
from hermes.run_status import RunStatus
from hermes.vault import indice

TOKEN = "segredo-de-teste"


@pytest.fixture
def cfg(vault, seed_yaml, tmp_path):
    config = load_config(vault_path=vault, db_path=tmp_path / "hermes.db")
    conn = store.connect(config.db_path)
    try:
        indice.reindexar(conn, vault, [], RunStatus())
        competencias.seed(conn, seed_yaml)
    finally:
        conn.close()
    return config


@pytest.fixture
def api(cfg):
    return TestClient(criar_app(cfg, TOKEN), headers={"X-Hermes-Token": TOKEN})


def _runs(cfg):
    conn = store.connect(cfg.db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT comando, status, error FROM runs ORDER BY id")]
    finally:
        conn.close()


# --- token ---------------------------------------------------------------------


def test_sem_token_e_401(cfg):
    cliente = TestClient(criar_app(cfg, TOKEN))
    assert cliente.get("/api/competencias").status_code == 401
    assert cliente.get("/api/competencias", headers={"X-Hermes-Token": "errado"}).status_code == 401


def test_saude_nao_exige_token(cfg):
    assert TestClient(criar_app(cfg, TOKEN)).get("/api/saude").json() == {"ok": True}


def test_app_sem_token_nao_sobe(cfg):
    with pytest.raises(ValueError):
        criar_app(cfg, "")


# --- competências ----------------------------------------------------------------


def test_lista_competencias(api):
    slugs = [c["slug"] for c in api.get("/api/competencias").json()]
    assert set(slugs) == {"python", "sql", "ingles"}


def test_detalhe_traz_evidencias_e_candidatos(api):
    detalhe = api.get("/api/competencias/python").json()
    assert detalhe["competencia"]["slug"] == "python"
    assert detalhe["competencia"]["situacao"] == "nunca avaliada"
    assert detalhe["competencia"]["pronta_para_cv"] is False
    assert detalhe["evidencias"] == []
    assert any(c["block_id"] == "pipeline" for c in detalhe["candidatos"])


def test_competencia_inexistente_e_422_com_a_mensagem(api):
    r = api.get("/api/competencias/cobol")
    assert r.status_code == 422
    assert "não existe" in r.json()["erro"]


def test_ligar_evidencia_e_avaliar(api, cfg):
    r = api.post("/api/competencias/python/evidencias", json={"referencia": "pipeline"})
    assert r.status_code == 200, r.text
    r = api.post("/api/competencias/python/nivel", json={"nivel": 2, "justificativa": "Mirante"})
    assert r.status_code == 200, r.text
    assert api.get("/api/competencias/python").json()["competencia"]["nivel"] == 2
    assert [x["comando"] for x in _runs(cfg)] == ["comp evidence", "comp assess"]


def test_nivel_sem_evidencia_e_recusado_e_vira_run_failed(api, cfg):
    r = api.post("/api/competencias/sql/nivel", json={"nivel": 3, "justificativa": "x"})
    assert r.status_code == 422
    assert "evidência" in r.json()["erro"]
    assert _runs(cfg)[-1]["status"] == "failed"


def test_remover_evidencia(api):
    api.post("/api/competencias/python/evidencias", json={"referencia": "pipeline"})
    r = api.request("DELETE", "/api/competencias/python/evidencias", params={"referencia": "pipeline"})
    assert r.status_code == 200, r.text
    assert api.get("/api/competencias/python").json()["evidencias"] == []


def test_detalhe_traz_recusas_por_nivel(api):
    recusas = api.get("/api/competencias/python").json()["recusas"]
    assert recusas["0"] is None and recusas["1"] is None
    assert recusas["2"] == {"titulo": "Nível 2 exige uma evidência do vault",
                            "texto": "Ligue um fato que mostre você usando Python, ou fique no nível 1."}
    assert recusas["3"]["titulo"] == "Nível 3 exige 2 evidências"
    api.post("/api/competencias/python/evidencias", json={"referencia": "pipeline"})
    assert api.get("/api/competencias/python").json()["recusas"]["2"] is None


def test_detalhe_marca_candidatos_com_metrica(api):
    candidatos = api.get("/api/competencias/python").json()["candidatos"]
    assert {c["block_id"]: c["tem_metrica"] for c in candidatos} == {"pipeline": False}


def test_detalhe_traz_os_ultimos_estudos(api, cfg):
    conn = store.connect(cfg.db_path)
    try:
        cid = competencias.buscar(conn, "python")["id"]
        with conn:
            for i, data in enumerate(["2026-10-01", "2026-10-03", "2026-10-02", "2026-10-05"]):
                conn.execute("INSERT INTO study_sessions (data, competency_id, minutos, o_que_fez, criado_em)"
                             " VALUES (?, ?, ?, ?, '2026-10-05')", (data, cid, 10 + i, f"estudo {i}"))
            conn.execute("INSERT INTO study_sessions (data, competency_id, minutos, o_que_fez, criado_em)"
                         " VALUES ('2026-10-06', NULL, 5, 'outro', '2026-10-06')")
    finally:
        conn.close()
    estudos = api.get("/api/competencias/python").json()["estudos"]
    assert estudos["total"] == 4
    assert estudos["ultimos"] == [
        {"data": "2026-10-05", "minutos": 13, "o_que_fez": "estudo 3"},
        {"data": "2026-10-03", "minutos": 11, "o_que_fez": "estudo 1"},
        {"data": "2026-10-02", "minutos": 12, "o_que_fez": "estudo 2"},
    ]


def test_todos_os_estudos_da_competencia(api, cfg):
    conn = store.connect(cfg.db_path)
    try:
        cid = competencias.buscar(conn, "python")["id"]
        with conn:
            for i, data in enumerate(["2026-10-01", "2026-10-03", "2026-10-02", "2026-10-05"]):
                conn.execute("INSERT INTO study_sessions (data, competency_id, minutos, o_que_fez, criado_em)"
                             " VALUES (?, ?, ?, ?, '2026-10-05')", (data, cid, 10 + i, f"estudo {i}"))
    finally:
        conn.close()
    todos = api.get("/api/competencias/python/estudos").json()
    assert [e["data"] for e in todos] == ["2026-10-05", "2026-10-03", "2026-10-02", "2026-10-01"]
    assert api.get("/api/competencias/cobol/estudos").status_code == 422


def test_desligar_avisa_que_o_nivel_ficou_sem_base(api):
    api.post("/api/competencias/python/evidencias", json={"referencia": "pipeline"})
    api.post("/api/competencias/python/nivel", json={"nivel": 2, "justificativa": "Mirante"})
    r = api.request("DELETE", "/api/competencias/python/evidencias", params={"referencia": "pipeline"})
    assert r.status_code == 200, r.text
    assert r.json()["nivel_sem_base"] == "Nível 2 fica sem evidência suficiente"
    assert api.get("/api/competencias/python").json()["competencia"]["nivel"] == 2


def test_categorias_com_nome_de_tela(api):
    categorias = api.get("/api/competencias/categorias").json()
    assert categorias[0] == {"id": "linguagem", "nome": "Linguagem e ferramenta"}
    assert [c["id"] for c in categorias] == list(competencias.CATEGORIAS)
    assert {"id": "soft", "nome": "Comportamental"} in categorias


def test_nova_competencia_pela_api(api, cfg):
    r = api.post("/api/competencias", json={"nome": "Inglês técnico", "categoria": "idioma", "peso": 2})
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "ingles-tecnico"
    assert "ingles-tecnico" in cfg.competencias_path.read_text(encoding="utf-8")
    assert any(c["slug"] == "ingles-tecnico" for c in api.get("/api/competencias").json())


def test_nova_competencia_duplicada_e_409(api, cfg):
    api.post("/api/competencias", json={"nome": "Inglês técnico", "categoria": "idioma", "peso": 2})
    antes = cfg.competencias_path.read_text(encoding="utf-8")
    r = api.post("/api/competencias", json={"nome": "ingles técnico", "categoria": "idioma", "peso": 1})
    assert r.status_code == 409
    assert r.json()["erro"] == "Já existe uma competência com esse nome"
    assert cfg.competencias_path.read_text(encoding="utf-8") == antes


def test_nova_competencia_categoria_invalida_e_422(api):
    r = api.post("/api/competencias", json={"nome": "Go", "categoria": "inventada", "peso": 2})
    assert r.status_code == 422


def test_remover_competencia_com_historico_pela_api(api):
    api.post("/api/competencias/python/evidencias", json={"referencia": "pipeline"})
    assert api.delete("/api/competencias/python").status_code == 422
    r = api.delete("/api/competencias/python", params={"com_historico": True})
    assert r.status_code == 200, r.text
    assert r.json()["evidencias_desligadas"] == 1


def test_exportar_escreve_no_vault(api, vault):
    assert api.post("/api/competencias/exportar").status_code == 200
    assert (vault / "Competencias.md").is_file()


def test_niveis_e_cobertura(api):
    assert api.get("/api/competencias/niveis").json()["2"] == "usei em projeto próprio que roda"
    assert api.get("/api/competencias/cobertura").json()["total"] == 3


# --- vagas, estudos, operação --------------------------------------------------


def test_vagas_vazias(api):
    assert api.get("/api/vagas").json() == []
    assert api.get("/api/vagas/99").status_code == 422


def test_semana_de_estudos_e_log(api):
    r = api.post("/api/estudos/sessoes", json={"minutos": 30, "o_que_fez": "li sobre RRF"})
    assert r.status_code == 200, r.text
    assert api.get("/api/estudos/semana").json()["minutos"] == 30


def test_sinais_pendentes_sem_ler_git(api):
    assert api.get("/api/estudos/sinais").json() == {"sinais": [], "lidos_em": None}


def _sinal(cfg, data, ref, resumo):
    conn = store.connect(cfg.db_path)
    try:
        with conn:
            conn.execute("INSERT INTO activity_signals (data, repo, ref, resumo, criado_em)"
                         " VALUES (?, 'agenda', ?, ?, '2026-10-01')", (data, ref, resumo))
    finally:
        conn.close()


def test_sinais_mais_recentes_primeiro(api, cfg):
    _sinal(cfg, "2026-10-01", "a" * 40, "antigo")
    _sinal(cfg, "2026-10-05", "b" * 40, "novo")
    _sinal(cfg, "2026-10-03", "c" * 40, "meio")
    assert [x["resumo"] for x in api.get("/api/estudos/sinais").json()["sinais"]] == ["novo", "meio", "antigo"]


@pytest.fixture
def git_falso(mocker):
    from hermes.domain import atividade

    return mocker.patch.object(atividade, "git_activity",
                               return_value={"sinais_novos": 2, "repos_lidos": ["agenda"]})


def test_git_lido_ha_pouco_nao_le_de_novo(api, git_falso):
    primeira = api.post("/api/estudos/git", json={"dias": 7, "se_mais_velho_que": 3600}).json()
    assert primeira["lido"] is True and primeira["sinais_novos"] == 2 and primeira["lidos_em"]
    segunda = api.post("/api/estudos/git", json={"dias": 7, "se_mais_velho_que": 3600}).json()
    assert segunda == {"lido": False, "lidos_em": primeira["lidos_em"]}
    assert git_falso.call_count == 1
    assert api.get("/api/estudos/sinais").json()["lidos_em"] == primeira["lidos_em"]


def test_git_lido_ha_mais_de_uma_hora_le_de_novo(api, cfg, git_falso):
    conn = store.connect(cfg.db_path)
    try:
        with conn:
            conn.execute("INSERT INTO estado_app (chave, valor) VALUES ('git_lido_em', '2020-01-01T00:00:00+00:00')")
    finally:
        conn.close()
    assert api.post("/api/estudos/git", json={"dias": 7, "se_mais_velho_que": 3600}).json()["lido"] is True
    assert git_falso.call_count == 1


def test_git_sem_limite_sempre_le(api, git_falso):
    api.post("/api/estudos/git", json={"dias": 7})
    assert api.post("/api/estudos/git", json={"dias": 7}).json()["lido"] is True
    assert git_falso.call_count == 2


def test_git_sem_repositorio_nao_e_erro(api):
    r = api.post("/api/estudos/git", json={"dias": 7, "se_mais_velho_que": 3600})
    assert r.status_code == 200, r.text
    assert r.json()["lido"] is True


# --- plano da semana: revisado na tela antes do vault ---------------------------------


@pytest.fixture
def plano_falso(api, cfg, mocker):
    """Vaga com SQL obrigatório e SQL no nível 1: lacuna de estudo. O LLM é falso."""
    from types import SimpleNamespace

    import litellm

    conn = store.connect(cfg.db_path)
    try:
        with conn:
            job = conn.execute("INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
                               " VALUES ('T', 'FDE', 'colado', 'x', 'h', '2026-10-01')").lastrowid
            conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id)"
                         " VALUES (?, 'SQL', 'obrigatorio', (SELECT id FROM competencies WHERE slug='sql'))", (job,))
        competencias.avaliar(conn, "sql", 1, "só tutorial")
    finally:
        conn.close()
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    conteudo = '{"objetivo": "SQL", "itens": [{"competencia": "sql", "descricao": "JOINs", "minutos": 60}]}'
    return mocker.patch.object(litellm, "completion", return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)))


def _diario(vault, semana):
    return vault / "Diario" / f"{semana}.md"


def test_gerar_plano_nao_escreve_no_vault(api, vault, plano_falso):
    r = api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["semana"] == "2026-W40" and corpo["inicio"] == "2026-09-28" and corpo["fim"] == "2026-10-04"
    assert corpo["ja_existia"] is False
    assert corpo["plano"]["itens"][0]["descricao"] == "JOINs"
    assert "JOINs" in corpo["markdown"]
    assert "custo" in corpo and "nota" not in corpo
    assert not _diario(vault, "2026-W40").exists()


def test_gravar_plano_no_vault_uma_vez_so(api, vault, plano_falso):
    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    primeira = api.post("/api/estudos/plano/2026-W40/vault")
    assert primeira.status_code == 200, primeira.text
    assert primeira.json()["ja_gravado"] is False
    from urllib.parse import quote
    assert primeira.json()["obsidian"] == f"obsidian://open?vault={quote(vault.name)}&file=Diario/2026-W40"
    segunda = api.post("/api/estudos/plano/2026-W40/vault").json()
    assert segunda["ja_gravado"] is True
    assert _diario(vault, "2026-W40").read_text(encoding="utf-8").count("JOINs") == 1


def test_gravar_no_vault_sem_plano_gerado_e_422(api):
    assert api.post("/api/estudos/plano/2026-W40/vault").status_code == 422


def test_ja_existia_quando_havia_plano(api, plano_falso):
    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    r = api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    assert r.json()["ja_existia"] is True


def test_plano_existente_nao_e_substituido_sem_pedir(api, plano_falso):
    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    r = api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40"})
    assert r.status_code == 409
    assert r.json()["erro"] == "Já existe um plano para essa semana"
    assert plano_falso.call_count == 1  # o LLM não foi chamado de novo


def test_descartar_apaga_o_plano(api, plano_falso):
    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    assert api.delete("/api/estudos/plano/2026-W40").status_code == 200
    assert api.get("/api/estudos/semana", params={"semana": "2026-W40"}).json()["plano"] is None
    assert api.post("/api/estudos/plano/2026-W40/vault").status_code == 422


def test_resumo_de_operacao(api):
    resumo = api.get("/api/operacao/resumo").json()
    assert resumo["fatos"][0]["tipo"] == "project"
    assert resumo["competencias"]["total"] == 3


def test_check_do_vault(api):
    problemas = api.get("/api/operacao/check").json()
    assert any("vazia" in p["mensagem"] for p in problemas)  # Acme sem fatos na fixture


def test_index_e_backup(api, cfg):
    assert api.post("/api/operacao/index").json()["fatos"] == 4
    assert api.post("/api/operacao/backup").json()["caminho"].endswith(".db")


def _esperar(api, estados, segundos=10):
    import time

    fim = time.time() + segundos
    while time.time() < fim:
        r = api.get("/api/operacao/index/progresso").json()
        if r["estado"] in estados:
            return r
        time.sleep(0.05)
    raise AssertionError(f"indexação não chegou a {estados}: {r}")


def test_indexacao_em_segundo_plano(api):
    assert api.post("/api/operacao/index/iniciar").json()["estado"] == "rodando"
    r = _esperar(api, {"pronto", "erro"})
    assert r["estado"] == "pronto" and r["resultado"]["fatos"] == 4 and r["feitas"] == r["total"] > 0


def test_index_sincrono_sem_carreira_e_422(cfg, tmp_path):
    import dataclasses

    outra = tmp_path / "vazia"
    outra.mkdir()
    cliente = TestClient(criar_app(dataclasses.replace(cfg, vault_path=outra), TOKEN), headers={"X-Hermes-Token": TOKEN})
    r = cliente.post("/api/operacao/index")
    assert r.status_code == 422 and "Carreira/" in r.json()["erro"]


def test_indexacao_em_segundo_plano_nao_fica_presa_se_o_banco_falhar(api, monkeypatch):
    from hermes.api.rotas import operacao

    def quebra(*a, **k):
        raise OSError("disco cheio")

    monkeypatch.setattr(operacao.store, "connect", quebra)
    api.post("/api/operacao/index/iniciar")
    r = _esperar(api, {"pronto", "erro", "cancelado"})
    assert r["estado"] == "erro" and "disco cheio" in r["erro"]


def test_indexacao_cancelada(api, monkeypatch):
    import time

    from hermes.vault import reader

    original = reader.parse_note
    monkeypatch.setattr(reader, "parse_note", lambda *a, **k: (time.sleep(0.3), original(*a, **k))[1])
    api.post("/api/operacao/index/iniciar")
    assert api.post("/api/operacao/index/cancelar").status_code == 200
    assert _esperar(api, {"cancelado", "pronto", "erro"})["estado"] == "cancelado"


# --- currículos ------------------------------------------------------------------


@pytest.fixture
def com_perfil(cfg, tmp_path, monkeypatch):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(
        "perfis:\n  - {slug: dados, cargo: {pt: Dados, en: Data}, competencias: {sql: 3}}\n",
        encoding="utf-8",
    )
    novo = cfg.__class__(**{**cfg.__dict__, "perfis_cv_path": caminho,
                            "saida_dir": tmp_path / "out"})
    conn = store.connect(novo.db_path)
    try:
        competencias.ligar_evidencia(conn, "sql", "sql-ddl")
        competencias.avaliar(conn, "sql", 2, "uso")
    finally:
        conn.close()
    return TestClient(criar_app(novo, TOKEN), headers={"X-Hermes-Token": TOKEN})


def test_perfis_e_galeria_vazia(com_perfil):
    assert [p["slug"] for p in com_perfil.get("/api/curriculos/perfis").json()] == ["dados"]
    grupos = com_perfil.get("/api/curriculos/galeria").json()
    assert grupos == [{"perfil": "dados", "titulo": "Melhores para vaga de Dados",
                       "cargo": {"pt": "Dados", "en": "Data"}, "foco": "", "versoes": []}]


def test_previa_nao_chama_o_modelo(com_perfil):
    fatos = com_perfil.get("/api/curriculos/previa", params={"perfil": "dados"}).json()
    assert [f["block_id"] for f in fatos] == ["sql-ddl"]


def test_perfil_inexistente_e_422(com_perfil):
    r = com_perfil.post("/api/curriculos", json={"perfil": "nada"})
    assert r.status_code == 422 and "não existe" in r.json()["erro"]


def test_gerar_por_perfil_aparece_na_galeria(com_perfil, cfg, mocker, tmp_path):
    from types import SimpleNamespace

    import litellm

    mocker.patch.object(litellm, "completion", return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"resumo": "r", "bullets": {}}', tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    ))
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    (cfg.vault_path / "Perfil.md").write_text("---\nnome: Ana\n---\n", encoding="utf-8")

    r = com_perfil.post("/api/curriculos", json={"perfil": "dados", "idiomas": ["pt"]})

    assert r.status_code == 200, r.text
    assert r.json()["custo"]["custo_usd"] == pytest.approx(0.001)
    assert (tmp_path / "out" / "dados" / "cv-pt.md").is_file()
    versoes = com_perfil.get("/api/curriculos/galeria").json()[0]["versoes"]
    assert len(versoes) == 1 and "**Dados**" in versoes[0]["conteudo"]


# --- vagas (V3) -------------------------------------------------------------------


def test_vaga_traz_sobre_avaliacao_e_nova(api, cfg):
    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Orla Tech', 'Desenvolvedor React', 'colado', 'Time de produto de pagamentos.', 'h-sobre', ?)",
            (store.utcnow(),)).lastrowid
        conn.execute("INSERT INTO job_requirements (job_id, texto, tipo) VALUES (?, 'Kafka', 'desejavel')", (job,))
    conn.close()
    d = api.get(f"/api/vagas/{job}").json()
    assert d["sobre"] == "Time de produto de pagamentos."
    assert d["avaliacao"]["requisitos"][0]["fonte"] == "sem competência ligada"
    assert "requisitos" not in d  # os requisitos vão uma vez só, dentro da avaliação
    [v] = [v for v in api.get("/api/vagas").json() if v["id"] == job]
    assert v["nova"] is True and v["score"] == 0


def test_vaga_vista_e_status_pela_api(api, cfg):
    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Vale Norte', 'Analista', 'colado', 'x', 'h-status', ?)", (store.utcnow(),)).lastrowid
    conn.close()
    assert api.post(f"/api/vagas/{job}/vista").json() == {"status": "analisado"}
    r = api.put(f"/api/vagas/{job}/status", json={"status": "descartado"})
    assert r.status_code == 200 and r.json()["anterior"] == "analisado"
    r = api.put(f"/api/vagas/{job}/status", json={"status": "arquivada"})
    assert 400 <= r.status_code < 500 and "status" in r.json()["erro"]


def test_erro_do_provedor_de_llm_vira_codigo_llm(api, cfg, mocker):
    import litellm

    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em) VALUES"
            " ('Orla Tech', 'Dev', 'colado', ?, 'h-llm', ?)", ("Vaga de desenvolvimento. " * 20, store.utcnow())).lastrowid
    conn.close()
    erro = litellm.AuthenticationError(message="Incorrect API key provided", llm_provider="openai", model="gpt-4o-mini")
    mocker.patch.object(litellm, "completion", side_effect=erro)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    r = api.post(f"/api/vagas/{job}/extrair")
    assert r.status_code == 502
    assert r.json()["codigo"] == "llm" and "chave" in r.json()["erro"]


def test_versao_de_curriculo_pela_api(api, cfg):
    import json

    conn = store.connect(cfg.db_path)
    with conn:
        vid = conn.execute(
            "INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo, estrutura) VALUES"
            " ('pt', 'out/cv-pt.md', '[]', '2026-10-01', '# CV', ?)", (json.dumps({"nome": "Ana"}),)).lastrowid
    conn.close()
    r = api.get(f"/api/curriculos/{vid}")
    assert r.status_code == 200 and r.json()["estrutura"] == {"nome": "Ana"}
    r = api.get("/api/curriculos/9999")
    assert r.status_code == 422 and "não existe" in r.json()["erro"]


def _versao_com_estrutura(cfg, tmp_path, estrutura='{"nome": "Ana"}'):
    conn = store.connect(cfg.db_path)
    with conn:
        vid = conn.execute(
            "INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo, estrutura) VALUES"
            " ('pt', ?, '[]', '2026-10-01', '# CV', ?)", (str(tmp_path / "out" / "cv-pt.md"), estrutura)).lastrowid
    conn.close()
    return vid


def test_pdf_da_versao(api, cfg, tmp_path, monkeypatch):
    from pathlib import Path

    from hermes.domain import pdf

    def falso(estrutura, destino, paginas=1):
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        Path(destino).write_bytes(b"%PDF-1.7")
        return {"paginas": 1, "entradas": []}

    monkeypatch.setattr(pdf, "compilar", falso)
    vid = _versao_com_estrutura(cfg, tmp_path)
    r = api.post(f"/api/curriculos/{vid}/pdf")
    assert r.status_code == 200 and r.json()["paginas"] == 1
    assert Path(r.json()["caminho"]).is_file() and r.json()["caminho"].endswith(f"cv-pt-v{vid}.pdf")


def test_pdf_com_typst_quebrado_e_422(api, cfg, tmp_path, monkeypatch):
    from hermes.domain import pdf

    def quebra(estrutura, destino, paginas=1):
        raise pdf.PdfFalhou("unknown variable: dados")

    monkeypatch.setattr(pdf, "compilar", quebra)
    vid = _versao_com_estrutura(cfg, tmp_path)
    r = api.post(f"/api/curriculos/{vid}/pdf")
    assert r.status_code == 422 and "não deu para montar o PDF" in r.json()["erro"]


def test_pdf_com_curriculos_yaml_quebrado_e_422(api, cfg, tmp_path):
    cfg.perfis_cv_path.write_text("perfis:\n  - slug: a\n   cargo: [", encoding="utf-8")
    vid = _versao_com_estrutura(cfg, tmp_path)
    r = api.post(f"/api/curriculos/{vid}/pdf")
    assert r.status_code == 422 and "curriculos.yaml" in r.json()["erro"]


@pytest.fixture
def versao_com_cv(cfg, tmp_path):
    import json

    from hermes.domain import curriculo as cv
    from tests.test_pdf import _estrutura

    cv._CACHE_PREVIA.clear()
    return _versao_com_estrutura(cfg, tmp_path, json.dumps(_estrutura(bullets_por_entrada=3), ensure_ascii=False))


def test_previa_da_versao(api, versao_com_cv):
    r = api.get(f"/api/curriculos/{versao_com_cv}/previa")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["paginas"][0].startswith("data:image/png;base64,")
    assert [l["ref"] for l in corpo["linhas"]] == [f"X.md#b{i}" for i in range(3)] * 2
    assert corpo["limite"] == 1 and corpo["passou"] is False
    assert corpo["largura"] > 0 and corpo["altura"] > 0
    for l in corpo["linhas"]:
        assert l["y"] + l["h"] <= corpo["altura"]


def test_previa_usa_o_cache(api, versao_com_cv, monkeypatch):
    from hermes.domain import pdf

    chamadas = []
    original = pdf.previa
    monkeypatch.setattr(pdf, "previa", lambda *a, **k: chamadas.append(1) or original(*a, **k))
    api.get(f"/api/curriculos/{versao_com_cv}/previa")
    api.get(f"/api/curriculos/{versao_com_cv}/previa")
    assert len(chamadas) == 1


def test_previa_avisa_quando_passa_do_limite(api, cfg, tmp_path):
    import json

    from hermes.domain import curriculo as cv
    from tests.test_pdf import _estrutura

    cv._CACHE_PREVIA.clear()
    vid = _versao_com_estrutura(cfg, tmp_path, json.dumps(_estrutura(bullets_por_entrada=60), ensure_ascii=False))
    corpo = api.get(f"/api/curriculos/{vid}/previa").json()
    assert len(corpo["paginas"]) > 1 and corpo["passou"] is True and corpo["limite"] == 1


def test_previa_de_versao_antiga_e_422(api, cfg, tmp_path):
    conn = store.connect(cfg.db_path)
    with conn:
        vid = conn.execute("INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo) VALUES"
                           " ('pt', 'x.md', '[]', '2026-10-01', '# CV')").lastrowid
    conn.close()
    assert api.get(f"/api/curriculos/{vid}/previa").status_code == 422


def test_pdf_salvo_como_e_baixado(api, cfg, tmp_path, monkeypatch):
    """Salvar como (app) copia para o destino escolhido; o navegador baixa o arquivo pelo GET."""
    from pathlib import Path

    from hermes.domain import pdf

    def falso(estrutura, destino, paginas=1):
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        Path(destino).write_bytes(b"%PDF-1.7 fake")
        return {"paginas": 1, "entradas": []}

    monkeypatch.setattr(pdf, "compilar", falso)
    vid = _versao_com_estrutura(cfg, tmp_path, '{"nome": "Ana Ribeiro"}')
    destino = tmp_path / "Downloads" / "Ana.pdf"
    destino.parent.mkdir()
    r = api.post(f"/api/curriculos/{vid}/pdf", json={"destino": str(destino)})
    assert r.status_code == 200 and r.json()["caminho"] == str(destino) and destino.read_bytes() == b"%PDF-1.7 fake"
    assert r.json()["nome_sugerido"] == "Ana Ribeiro.pdf"
    r = api.post(f"/api/curriculos/{vid}/pdf", json={"destino": str(tmp_path / "x.txt")})
    assert r.status_code == 422 and ".pdf" in r.json()["erro"]
    r = api.get(f"/api/curriculos/{vid}/pdf")
    assert r.status_code == 200 and r.content == b"%PDF-1.7 fake" and r.headers["content-type"] == "application/pdf"
    assert "Ana%20Ribeiro.pdf" in r.headers["content-disposition"] or "Ana Ribeiro.pdf" in r.headers["content-disposition"]


def test_pdf_acima_do_limite_diz_onde_mexer(api, cfg, tmp_path, monkeypatch):
    from hermes.domain import pdf

    def estoura(estrutura, destino, paginas=1):
        raise pdf.PaginasDemais(2, paginas, [], destino)

    monkeypatch.setattr(pdf, "compilar", estoura)
    r = api.post(f"/api/curriculos/{_versao_com_estrutura(cfg, tmp_path)}/pdf")
    assert r.status_code == 422
    assert r.json()["erro"] == "passou de 2 páginas (limite 1): tire fatos do recorte ou baixe o limite de fatos"


def test_pdf_de_versao_antiga_pede_para_redigir(api, cfg, tmp_path):
    conn = store.connect(cfg.db_path)
    with conn:
        vid = conn.execute("INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo) VALUES"
                           " ('pt', 'out/cv-pt.md', '[]', '2026-10-01', '# CV')").lastrowid
    conn.close()
    r = api.post(f"/api/curriculos/{vid}/pdf")
    assert r.status_code == 422 and "redija de novo" in r.json()["erro"]


def test_criar_recorte_pela_api(api, cfg, tmp_path, monkeypatch):
    from dataclasses import replace

    caminho = tmp_path / "curriculos-api.yaml"
    api.app.state.cfg = replace(cfg, perfis_cv_path=caminho)
    r = api.post("/api/curriculos/perfis", json={"cargo_pt": "Dados", "cargo_en": "Data", "competencias": {"sql": 2}})
    assert r.status_code == 200 and r.json()["slug"] == "dados" and caminho.is_file()
    r = api.post("/api/curriculos/perfis", json={"cargo_pt": "Dados", "cargo_en": "Data", "competencias": {"cobol": 2}})
    assert r.status_code == 422 and "taxonomia" in r.json()["erro"]


# --- início ----------------------------------------------------------------------


def test_inicio_traz_o_painel(api):
    r = api.get("/api/inicio").json()
    assert set(r) == {"agora", "numeros", "desde_ontem", "desde_visita", "candidaturas", "atividade", "indice",
                      "pede_acao", "mudancas", "etapas"}
    assert r["indice"]["notas"] >= 1  # o vault de teste foi indexado


def test_visita_marca_o_horario_do_resumo_visto(api):
    visto = "2026-01-02T03:04:05+00:00"  # o "agora" do resumo que a tela mostrou, não o da hora de sair
    assert api.post("/api/inicio/visita", json={"quando": visto}).json()["marcada"] == visto
    assert api.get("/api/inicio").json()["desde_visita"]["desde"] == visto


def test_inicio_conta_desde_a_visita_marcada(api):
    marcada = api.post("/api/inicio/visita").json()["marcada"]
    assert api.get("/api/inicio").json()["desde_visita"]["desde"] == marcada


# --- candidaturas ----------------------------------------------------------------


def test_marcar_entrevista_pela_api(api, cfg):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    conn.close()
    r = api.put(f"/api/candidaturas/{cid}/entrevista", json={"quando": "2026-10-10T14:00:00-03:00"})
    assert r.status_code == 200 and r.json()["candidatura"]["status"] == "entrevista"
    r = api.put(f"/api/candidaturas/{cid}/entrevista", json={"quando": "sexta"})
    assert r.status_code == 400 or r.status_code == 422
    r = api.put(f"/api/candidaturas/{cid}/entrevista", json={"quando": None})
    assert r.json()["candidatura"]["entrevista_em"] is None


def test_preparar_entrevista(api, cfg, mocker):
    import json
    from types import SimpleNamespace

    import litellm

    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Orla Tech', 'Desenvolvedor React', 'colado', 'x', 'h-orla', ?)", (store.utcnow(),)
        ).lastrowid
        conn.execute("INSERT INTO job_requirements (job_id, texto, tipo) VALUES (?, 'Playwright', 'obrigatorio')",
                     (job,))
    com_vaga = cand.registrar_do_cv(conn, job, None, None)
    pingada = cand.registrar_manual(conn, "Vale Norte", "geral")
    conn.close()

    resposta = {"roteiro": [{"tema": "Playwright", "o_que_revisar": "fixtures",
                             "pergunta_provavel": "Como você testa um login?"}]}
    mocker.patch.object(litellm, "completion", return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(resposta), tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)))
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])

    r = api.post(f"/api/candidaturas/{com_vaga}/preparar")
    assert r.status_code == 200
    assert r.json()["roteiro"]["roteiro"][0]["tema"] == "Playwright"
    assert r.json()["custo"]["llm_calls"] == 1
    salvo = api.get(f"/api/candidaturas/{com_vaga}").json()["roteiro"]  # decisão 6: fica salvo
    assert salvo["itens"][0]["tema"] == "Playwright" and salvo["gerado_em"]

    r = api.post(f"/api/candidaturas/{pingada}/preparar")
    assert 400 <= r.status_code < 500 and "ligue a candidatura" in r.json()["erro"]


def test_candidaturas_lista_detalhe_e_edicao(api, cfg):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    try:
        cid = cand.registrar_manual(conn, "Áureo", "geral")
    finally:
        conn.close()
    lista = api.get("/api/candidaturas").json()
    assert [c["id"] for c in lista] == [cid] and lista[0]["score"] is None

    r = api.put(f"/api/candidaturas/{cid}/titulo", json={"titulo": "Estágio Corporativo"})
    assert r.json()["candidatura"]["titulo"] == "Estágio Corporativo"
    assert api.post(f"/api/candidaturas/{cid}/cancelar").json()["candidatura"]["status"] == "cancelada"
    assert api.post(f"/api/candidaturas/{cid}/reabrir", json={}).json()["candidatura"]["status"] == "enviada"
    assert api.post(f"/api/candidaturas/{cid}/cancelar").status_code == 200
    assert [c["comando"] for c in _runs(cfg)][-4:] == ["app titulo", "app cancelar", "app reabrir", "app cancelar"]


def test_candidatura_inexistente_e_perfil_invalido_sao_422(api, cfg):
    from hermes.domain import candidaturas as cand

    assert api.get("/api/candidaturas/99").status_code == 422
    conn = store.connect(cfg.db_path)
    try:
        cid = cand.registrar_manual(conn, "Áureo", "geral")
    finally:
        conn.close()
    r = api.put(f"/api/candidaturas/{cid}/perfil", json={"perfil": "nao-existe"})
    assert r.status_code == 422


def test_marcar_enviada_pela_api(api, cfg):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Maré Digital', 'Front-end', 'colado', 'x', 'h-mare', ?)", (store.utcnow(),)).lastrowid
    cid = cand.registrar_do_cv(conn, job, None, None)
    conn.close()
    r = api.post(f"/api/candidaturas/{cid}/enviada", json={"quando": "2026-10-09"})
    assert r.status_code == 200 and r.json()["candidatura"]["status"] == "enviada"
    assert api.post(f"/api/candidaturas/{cid}/enviada", json={}).status_code == 422


def test_adicionar_candidatura_pela_api(api, com_perfil):
    r = api.post("/api/candidaturas", json={"empresa": "Orla Tech", "titulo": "Dev React", "perfil": ""})
    assert r.status_code == 200
    c = r.json()["candidatura"]
    assert (c["perfil"], c["status"], c["origem"], c["titulo"]) == ("geral", "enviada", "manual", "Dev React")
    from datetime import date
    assert c["enviada_em"][:10] == date.today().isoformat()
    assert api.post("/api/candidaturas", json={"empresa": "  "}).status_code == 422
    r = com_perfil.post("/api/candidaturas", json={"empresa": "Orla", "perfil": "nao-existe"})
    assert r.status_code == 422 and "dados" in r.json()["erro"]
    r = com_perfil.post("/api/candidaturas", json={"empresa": "Orla", "perfil": "dados", "enviada_em": "2026-10-01"})
    assert r.json()["candidatura"]["perfil"] == "dados" and r.json()["candidatura"]["enviada_em"] == "2026-10-01"


def test_entrevista_com_titulo_juntar_e_nova_candidatura_pela_api(api, cfg):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    destino = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio")
    e = cand.inserir_email(conn, {"gmail_id": "j1", "recebido_em": "2026-10-01T10:00:00+00:00", "de": "rh@x.example",
                                  "assunto": "Inscrição", "final": "pendencia", "empresa_extraida": "Grupo Tavares"})
    conn.close()
    r = api.put(f"/api/candidaturas/{destino}/entrevista", json={"quando": "2026-10-12T14:00:00-03:00", "titulo": ""})
    assert r.json()["candidatura"]["entrevista_titulo"] == "Entrevista"
    r = api.post(f"/api/emails/{e}/nova-candidatura")
    assert r.status_code == 200
    pingada = r.json()["candidatura_id"]
    assert pingada != destino
    assert [p["id"] for p in api.get(f"/api/candidaturas/{pingada}").json()["parecidas"]] == [destino]
    r = api.post(f"/api/candidaturas/{pingada}/juntar", json={"destino": destino})
    assert r.status_code == 200 and [m["id"] for m in r.json()["emails"]] == [e]
    assert api.get(f"/api/candidaturas/{pingada}").status_code == 422
    assert api.post(f"/api/candidaturas/{destino}/juntar", json={"destino": destino}).status_code == 422


def test_triar_e_restaurar_pela_api(api, cfg):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    e = cand.inserir_email(conn, {"gmail_id": "tr1", "recebido_em": "2026-10-05T10:00:00+00:00", "de": "rh@x.example",
                                  "assunto": "Oi", "final": "revisar"})
    conn.close()
    r = api.post(f"/api/emails/{e}/triar", json={"categoria": "avanco", "empresa": "Porto Digital"})
    assert r.status_code == 200 and r.json()["criada"] and r.json()["email"]["candidatura_id"] == r.json()["criada"]
    r = api.post(f"/api/emails/{e}/restaurar", json={"rotulo_manual": None, "candidatura_id": None, "empresa": None,
                                                     "apagar": r.json()["criada"]})
    assert r.status_code == 200 and r.json()["categoria"] == "revisar" and r.json()["candidatura_id"] is None
    assert api.get("/api/candidaturas").json() == []


def test_nao_vou_enviar_e_desfazer_pela_api(api, cfg):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Maré Digital', 'Front-end', 'colado', 'x', 'h-mare2', ?)", (store.utcnow(),)).lastrowid
    cid = cand.registrar_do_cv(conn, job, None, None)
    manual = cand.registrar_manual(conn, "Orla", "geral")
    conn.close()
    r = api.delete(f"/api/candidaturas/{cid}")
    assert r.status_code == 200 and api.get(f"/api/candidaturas/{cid}").status_code == 422
    r = api.post("/api/candidaturas/rascunho", json={"rascunho": r.json()["rascunho"]})
    assert r.status_code == 200 and r.json()["candidatura"]["id"] == cid and r.json()["candidatura"]["status"] == "a_enviar"
    assert api.delete(f"/api/candidaturas/{manual}").status_code == 422


def test_vagas_anunciadas_nao_colidem_com_o_id(api):
    assert api.get("/api/candidaturas/anunciadas").json() == []


# --- e-mails -----------------------------------------------------------------------


def _email_pendente(cfg, final="revisar", empresa=None):
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    try:
        return cand.inserir_email(conn, {"gmail_id": f"g-{final}", "recebido_em": "2026-10-01T10:00:00+00:00",
                                         "de": "rh@orbital.jobs", "assunto": "Acompanhe sua candidatura",
                                         "corpo": "Olá", "final": final, "empresa_extraida": empresa})
    finally:
        conn.close()


def test_emails_triagem_pela_tela(api, cfg):
    eid = _email_pendente(cfg)
    r = api.get("/api/emails").json()
    assert [e["id"] for e in r["emails"]] == [eid] and r["contagens"]["pendentes"] == 1
    assert r["ultimo_sync"] is None
    assert api.get(f"/api/emails/{eid}").json()["corpo"] == "Olá"

    # categoria certa sem empresa: continua pendente; com a empresa, vira candidatura
    assert api.post(f"/api/emails/{eid}/categoria", json={"categoria": "avanco"}).json()["candidatura_id"] is None
    ligado = api.post(f"/api/emails/{eid}/empresa", json={"empresa": "Orbital"}).json()
    assert ligado["cand_empresa"] == "Orbital" and ligado["manual"] is True
    assert api.get("/api/emails").json()["contagens"] == {"pendentes": 0, "processo": 1, "outros": 0}

    assert api.post(f"/api/emails/{eid}/categoria", json={"categoria": "talvez"}).status_code == 422
    assert api.get("/api/emails?visao=lixo").status_code == 422


def test_sync_sem_chave_do_jev_e_recusa(api, monkeypatch):
    monkeypatch.setenv("EMAIL_CLASSIFICADOR", "jev")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    r = api.post("/api/emails/sync", json={})
    assert r.status_code == 422 and "TYPESAFE_API_KEY" in r.json()["erro"]


def test_sync_usa_o_llm_do_usuario_por_padrao(api, cfg, monkeypatch, mocker):
    from types import SimpleNamespace

    import litellm

    from hermes.integracoes import gmail

    class Caixa:
        def __init__(self, pasta, rotular=False):
            pass

        def listar_ids(self, dias, maximo):
            return ["n1"]

        def ler(self, msg_id):
            return {"gmail_id": msg_id, "recebido_em": "2026-10-05T10:00:00+00:00",
                    "de": "Quartzo <quartzo@ses-mail.inhire.app>", "assunto": "Recebemos sua candidatura na Quartzo",
                    "corpo": "Olá, Fulano"}

    resposta = '{"e_processo": true, "categoria": "inscricao_confirmada", "certeza": 0.95, "tem_prazo": false}'
    mocker.patch.object(litellm, "completion", return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=resposta, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=30)))
    mocker.patch.object(litellm, "completion_cost", return_value=0.0002)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["response_format"])
    monkeypatch.setattr(gmail, "CaixaGmail", Caixa)

    r = api.post("/api/emails/sync", json={"dias": 7, "maximo": 5}).json()

    assert r["novos"] == 1 and r["ligados"] == 1
    assert r["custo"]["llm_calls"] == 1 and r["custo"]["custo_usd"] == 0.0002  # contada uma vez só
    assert litellm.completion.call_args.kwargs["response_format"] == {"type": "json_object"}


def test_sync_classifica_e_devolve_o_custo(api, cfg, monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    from hermes.integracoes import gmail

    class Caixa:
        def __init__(self, pasta, rotular=False):
            pass

        def listar_ids(self, dias, maximo):
            return ["n1"]

        def ler(self, msg_id):
            return {"gmail_id": msg_id, "recebido_em": "2026-10-05T10:00:00+00:00",
                    "de": "Quartzo <quartzo@ses-mail.inhire.app>", "assunto": "Recebemos sua candidatura na Quartzo",
                    "corpo": "Olá, Fulano"}

    class Jev:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def system_one(self, state, questions):
            return SimpleNamespace(
                choices={"categoria": SimpleNamespace(choice="inscricao_confirmada",
                                                      probabilities={"inscricao_confirmada": 0.97})},
                nouls={"e_processo": SimpleNamespace(noul=0.95), "tem_prazo": SimpleNamespace(noul=0.1)})

    sdk = ModuleType("typesafe_sdk")
    sdk.TypeSafeClient = Jev
    sdk.Choice = sdk.Noul = lambda **kw: kw  # só montam as perguntas
    monkeypatch.setitem(sys.modules, "typesafe_sdk", sdk)
    monkeypatch.setattr(gmail, "CaixaGmail", Caixa)
    monkeypatch.setenv("TYPESAFE_API_KEY", "teste")
    monkeypatch.setenv("EMAIL_CLASSIFICADOR", "jev")

    r = api.post("/api/emails/sync", json={"dias": 7, "maximo": 1}).json()
    assert r["novos"] == 1 and r["ligados"] == 1 and r["chegou_ao_maximo"] is True
    assert r["custo"]["llm_calls"] == 1
    assert api.get("/api/emails").json()["ultimo_sync"] is not None
    assert _runs(cfg)[-1]["comando"] == "email sync"


def test_desligar_pela_api(api, cfg):
    eid = _email_pendente(cfg, final="avanco", empresa="Orbital")
    from hermes.domain import candidaturas as cand

    conn = store.connect(cfg.db_path)
    try:
        cand.ligar(conn, eid)
    finally:
        conn.close()
    assert api.post(f"/api/emails/{eid}/desligar").json()["candidatura_id"] is None
    assert api.get("/api/emails").json()["contagens"]["pendentes"] == 1


def test_remover_competencia_pela_api_tira_do_seed(api, cfg):
    cfg.competencias_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.competencias_path.write_text("competencias:\n  - slug: ingles\n    nome: Inglês\n    categoria: idioma\n",
                                      encoding="utf-8")
    r = api.delete("/api/competencias/ingles").json()
    assert r["slug"] == "ingles" and r["do_seed"] is True
    assert "ingles" not in cfg.competencias_path.read_text(encoding="utf-8")
    assert "ingles" not in [c["slug"] for c in api.get("/api/competencias").json()]
    assert api.delete("/api/competencias/ingles").status_code == 422


def test_adicionar_candidatura_com_data_futura_e_422(api):
    from datetime import date, timedelta

    amanha = (date.today() + timedelta(days=1)).isoformat()
    r = api.post("/api/candidaturas", json={"empresa": "Orla", "perfil": "", "enviada_em": amanha})
    assert r.status_code == 422 and "futuro" in r.json()["erro"]


def test_ligar_vaga_pela_api(api, cfg):
    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute("INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
                           " VALUES ('Orla', 'Dev', 'colado', 't', 'h-ligar', ?)", (store.utcnow(),)).lastrowid
    conn.close()
    cid = api.post("/api/candidaturas", json={"empresa": "Orla", "perfil": ""}).json()["candidatura"]["id"]
    r = api.put(f"/api/candidaturas/{cid}/vaga", json={"job_id": job})
    assert r.status_code == 200 and r.json()["candidatura"]["job_id"] == job
    assert api.put(f"/api/candidaturas/{cid}/vaga", json={"job_id": 9999}).status_code == 422


def test_gravar_plano_no_vault_dois_pedidos_ao_mesmo_tempo_escrevem_uma_vez(api, vault, cfg, plano_falso, mocker):
    """O segundo pedido chega enquanto o primeiro escreve: ele não escreve de novo."""
    from hermes.api.rotas import estudos as rota
    from hermes.vault import writer

    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    original = writer.acrescentar
    respostas = []

    def no_meio(*a, **k):
        outra = store.connect(cfg.db_path)
        try:
            respostas.append(rota.gravar_no_vault("2026-W40", conn=outra, cfg=api.app.state.cfg))
        finally:
            outra.close()
        return original(*a, **k)

    escrever = mocker.patch.object(writer, "acrescentar", side_effect=no_meio)
    assert api.post("/api/estudos/plano/2026-W40/vault").json()["ja_gravado"] is False
    assert respostas == [{"ja_gravado": True, "nota": None}] and escrever.call_count == 1
    assert _diario(vault, "2026-W40").read_text(encoding="utf-8").count("JOINs") == 1


def test_gravar_plano_que_falha_libera_para_tentar_de_novo(api, vault, plano_falso, mocker):
    from hermes.vault import writer

    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    mocker.patch.object(writer, "acrescentar", side_effect=OSError("disco cheio"))
    with pytest.raises(OSError):
        api.post("/api/estudos/plano/2026-W40/vault")
    mocker.stopall()
    assert api.post("/api/estudos/plano/2026-W40/vault").json()["ja_gravado"] is False


def test_ligacoes_da_competencia(api, cfg):
    conn = store.connect(cfg.db_path)
    with conn:
        job = conn.execute("INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
                           " VALUES ('T', 'FDE', 'colado', 'x', 'h-lig', '2026-10-01')").lastrowid
        conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id)"
                     " VALUES (?, 'SQL', 'obrigatorio', (SELECT id FROM competencies WHERE slug='sql'))", (job,))
    conn.close()
    api.post("/api/estudos/sessoes", json={"minutos": 30, "o_que_fez": "JOINs", "comp": "sql"})
    assert api.get("/api/competencias/sql/ligacoes").json() == {"estudos": 1, "requisitos": 1}


def test_reserva_presa_do_plano_vence_e_libera_a_gravacao(api, vault, cfg, plano_falso):
    """O processo morreu entre a reserva e a escrita: depois de alguns minutos, gravar de novo vale."""
    from datetime import datetime, timedelta, timezone

    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    velha = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    conn = store.connect(cfg.db_path)
    with conn:
        conn.execute("INSERT INTO estado_app (chave, valor) VALUES ('plano_vault:2026-W40', ?)", (f"gravando:{velha}",))
    conn.close()
    r = api.post("/api/estudos/plano/2026-W40/vault").json()
    assert r["ja_gravado"] is False and _diario(vault, "2026-W40").exists()


def test_reserva_recente_do_plano_continua_valendo(api, vault, cfg, plano_falso):
    from datetime import datetime, timezone

    api.post("/api/estudos/plano", json={"minutos": 120, "semana": "2026-W40", "substituir": True})
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = store.connect(cfg.db_path)
    with conn:
        conn.execute("INSERT INTO estado_app (chave, valor) VALUES ('plano_vault:2026-W40', ?)", (f"gravando:{agora}",))
    conn.close()
    assert api.post("/api/estudos/plano/2026-W40/vault").json()["ja_gravado"] is True
    assert not _diario(vault, "2026-W40").exists()
