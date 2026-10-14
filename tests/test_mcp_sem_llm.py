import json
from types import SimpleNamespace

import pytest

from hermes.config import load_config
from hermes.domain import competencias
from hermes.domain import perfil as perfil_mod
from hermes.mcp_server import Quilha

VAGA = ("Vaga de Analista de Dados na Aurora Saúde Digital. Requisitos: Python avançado para automação de "
        "pipelines, SQL com modelagem de dados, inglês intermediário para leitura. Diferencial: experiência "
        "com Airflow ou outro orquestrador. Trabalho remoto, time pequeno, foco em qualidade e testes. " * 2)


@pytest.fixture
def quilha(banco, vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setenv("HERMES_SAIDA", str(tmp_path / "out"))
    monkeypatch.delenv("LLM_MODEL", raising=False)
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    q = Quilha(load_config())
    assert q.sem_llm()
    return q


def _pedido(r):
    assert r["ok"], r
    assert r["data"]["etapa"] == "aguardando_texto", r
    return r["data"]


def test_parse_job_pede_o_texto_e_grava_so_o_que_valida(quilha, conn):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))
    assert "Aurora" in pedido["entrada"] and pedido["instrucoes"]
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0  # nada gravado ainda

    r = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": {
        "empresa": "Aurora Saúde Digital", "titulo": "Analista de Dados", "senioridade": "pleno",
        "local": "remoto",
        "requisitos": [
            {"texto": "Python avançado", "tipo": "obrigatorio", "competencia_sugerida": "python", "confianca": 0.9},
            {"texto": "Airflow", "tipo": "desejavel", "competencia_sugerida": "airflow-inventado", "confianca": 0.8},
        ],
    }})

    assert r["ok"], r
    reqs = conn.execute("SELECT texto, competency_id FROM job_requirements ORDER BY id").fetchall()
    assert len(reqs) == 2
    assert reqs[1]["competency_id"] is None  # slug inventado não vira competência
    assert conn.execute("SELECT count(*) FROM rascunhos_mcp").fetchone()[0] == 0  # rascunho usado


def test_vaga_repetida_volta_sem_pedir_texto(quilha):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))
    quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": {"requisitos": [
        {"texto": "Python", "tipo": "obrigatorio", "competencia_sugerida": "python", "confianca": 1}]}})

    r = quilha.chamar("parse_job", {"texto": VAGA})
    assert r["ok"] and r["data"].get("duplicada") is True


def test_cv_com_referencia_inventada_nao_entra(quilha, conn):
    pedido = _pedido(quilha.chamar("cv_generate", {}))
    rascunho = pedido["rascunho_id"]

    # a entrada lista cada fato selecionado como `- <referencia> :: <texto>` (curriculo._entrada_para_o_modelo)
    ref = next(linha[2:].split(" :: ")[0] for linha in pedido["entrada"].splitlines() if " :: " in linha)
    inventada = ref.split("#")[0] + "#nao-existe"

    r = quilha.chamar("submit_draft", {"rascunho_id": rascunho, "resposta": {
        "resumo": "Analista que automatiza pipelines.",
        "bullets": {ref: "Criou pipeline diário em Python", inventada: "Liderou time de 40 pessoas"},
    }})

    assert r["ok"], r
    md = r["data"]["versoes"][0]["markdown"]
    assert "Criou pipeline diário em Python" in md
    assert "40 pessoas" not in md


def test_cv_em_dois_idiomas_sao_duas_rodadas_no_mesmo_rascunho(quilha):
    primeiro = _pedido(quilha.chamar("cv_generate", {"idiomas": ["pt", "en"]}))
    segundo = _pedido(quilha.chamar("submit_draft", {"rascunho_id": primeiro["rascunho_id"],
                                                     "resposta": {"resumo": "r", "bullets": {}}}))
    assert segundo["rascunho_id"] == primeiro["rascunho_id"]

    r = quilha.chamar("submit_draft", {"rascunho_id": segundo["rascunho_id"],
                                       "resposta": {"resumo": "s", "bullets": {}}})
    assert r["ok"] and [v["idioma"] for v in r["data"]["versoes"]] == ["pt", "en"]


def test_vault_mudou_entre_as_etapas_pede_de_novo(quilha, conn):
    pedido = _pedido(quilha.chamar("cv_generate", {}))
    competencias.ligar_evidencia(conn, "python", "testes", forca=2)  # a seleção muda

    r = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"],
                                       "resposta": {"resumo": "r", "bullets": {}}})

    novo = _pedido(r)  # pedido novo, para a seleção nova; nada gravado com a resposta antiga
    assert novo["entrada"] != pedido["entrada"]
    assert conn.execute("SELECT count(*) FROM cv_versions").fetchone()[0] == 0


def test_os_quatro_pedidos_levam_esquema_e_nada_e_gravado_antes(quilha, conn):
    """Garantia dos contratos: toda tool que usa modelo pede pelo contrato, e o pedido sai antes de gravar."""
    def contagens():
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("jobs", "cv_versions", "study_plan")}

    antes = contagens()
    pedidos = [_pedido(quilha.chamar("parse_job", {"texto": VAGA})), _pedido(quilha.chamar("cv_generate", {}))]
    assert contagens() == antes

    # match e plano precisam de vaga gravada, com uma lacuna sem fato no vault (inglês): lacuna de estudo
    job = quilha.chamar("submit_draft", {"rascunho_id": pedidos[0]["rascunho_id"], "resposta": {"requisitos": [
        {"texto": "Inglês", "tipo": "obrigatorio", "competencia_sugerida": "ingles", "confianca": 1}]}})["data"]
    antes = contagens()
    pedidos += [_pedido(quilha.chamar("plan_week", {"minutos_disponiveis": 120}))]
    assert contagens() == antes
    pedidos += [_pedido(quilha.chamar("match_job", {"job_id": job["job_id"]}))]  # grava só o score

    assert [p["esquema"]["required"] for p in pedidos] == [
        ["requisitos"], ["resumo", "bullets"], ["itens"], ["lacunas", "riscos"]]


def test_formato_errado_volta_com_o_motivo_e_aceita_reenvio(quilha, conn):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))

    r = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": {"sem": "requisitos"}})
    assert r["error"]["code"] == "resposta_invalida" and "requisitos" in r["error"]["message"]

    r = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": {"requisitos": [
        {"texto": "Python", "tipo": "talvez", "competencia_sugerida": "python", "confianca": 1}]}})
    assert r["ok"], r
    assert any("tipo" in a for a in r.get("avisos", []))  # o que foi corrigido volta como aviso
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_resposta_que_nao_e_objeto_e_recusada(quilha):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))
    r = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": ["lista"]})
    assert r["error"]["code"] == "argumentos_invalidos"


def test_rascunho_usado_nao_vale_de_novo(quilha):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))
    resposta = {"requisitos": [{"texto": "Python", "tipo": "obrigatorio", "competencia_sugerida": "python",
                                "confianca": 1}]}
    quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": resposta})
    r = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": resposta})
    assert r["error"]["code"] == "rascunho_invalido"


def test_match_grava_o_score_na_primeira_etapa(quilha, conn):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))
    job = quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": {"requisitos": [
        {"texto": "Python", "tipo": "obrigatorio", "competencia_sugerida": "python", "confianca": 1},
        {"texto": "SQL", "tipo": "obrigatorio", "competencia_sugerida": "sql", "confianca": 1}]}})["data"]
    job_id = job["job_id"]

    pedido = _pedido(quilha.chamar("match_job", {"job_id": job_id}))

    assert pedido["resultado_parcial"]["score"] is not None
    assert conn.execute("SELECT count(*) FROM job_matches WHERE job_id = ?", (job_id,)).fetchone()[0] == 1


def test_plan_week_pede_o_texto_e_respeita_o_total(quilha):
    pedido = _pedido(quilha.chamar("parse_job", {"texto": VAGA}))
    quilha.chamar("submit_draft", {"rascunho_id": pedido["rascunho_id"], "resposta": {"requisitos": [
        {"texto": "Inglês", "tipo": "obrigatorio", "competencia_sugerida": "ingles", "confianca": 1}]}})

    plano = _pedido(quilha.chamar("plan_week", {"minutos_disponiveis": 120}))
    r = quilha.chamar("submit_draft", {"rascunho_id": plano["rascunho_id"], "resposta": {
        "objetivo": "Inglês", "itens": [{"competencia": "ingles", "descricao": "ler 3 artigos técnicos", "minutos": 90},
                                        {"competencia": "ingles", "descricao": "estourar", "minutos": 500}]}})
    assert r["ok"], r
    assert r["data"]["minutos_alvo"] <= 120
    assert any("cortado" in a for a in r.get("avisos", []))


def test_com_llm_proprio_nao_ha_rascunho(banco, vault, tmp_path, monkeypatch, mocker):
    import litellm

    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "chave-de-teste")
    mocker.patch.object(litellm, "completion_cost", return_value=0.0005)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["response_format"])
    mocker.patch.object(litellm, "completion", return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"requisitos": [
            {"texto": "Python", "tipo": "obrigatorio", "competencia_sugerida": "python", "confianca": 1}]}),
            tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50)))

    quilha = Quilha(load_config())
    r = quilha.chamar("parse_job", {"texto": VAGA})

    assert not quilha.sem_llm()
    assert r["ok"] and r["data"].get("etapa") is None
    assert "submit_draft" not in {t.name for t in quilha.listar()}
