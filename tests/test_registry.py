"""O registry: allowlist, confirmação e o contrato `{ok, data|error}` de toda tool."""

import pytest

from hermes.agent.registry import Registry, Tool
from hermes.run_status import RunStatus


@pytest.fixture
def registry(banco):
    return Registry(conn=banco)


def test_schemas_descrevem_todas_as_tools(registry):
    nomes = [s["function"]["name"] for s in registry.schemas()]
    assert set(nomes) == {
        "vault_search_facts",
        "list_competencies",
        "link_evidence",
        "assess_competency",
        "parse_job",
        "match_job",
        "log_study",
        "git_activity",
        "confirm_study_signals",
        "study_week",
        "plan_week",
        "list_jobs",
        "list_applications",
        "application_detail",
        "profile_scores",
    }
    for schema in registry.schemas():
        assert schema["type"] == "function"
        assert schema["function"]["description"]
        assert schema["function"]["parameters"]["type"] == "object"


def test_allowlist_esconde_o_resto(banco):
    registry = Registry(conn=banco, allowlist={"vault_search_facts"})
    assert [s["function"]["name"] for s in registry.schemas()] == ["vault_search_facts"]

    resultado = registry.dispatch("assess_competency", {"slug": "python"})
    assert resultado["ok"] is False
    assert resultado["error"]["code"] == "tool_desconhecida"


def test_busca_de_fatos_devolve_referencia_citavel(registry):
    resultado = registry.dispatch("vault_search_facts", '{"query": "pipeline"}')
    assert resultado["ok"] is True
    assert resultado["data"][0]["referencia"] == "Carreira/Projetos/Mirante.md#pipeline"


def test_argumentos_chegam_como_string_json(registry):
    resultado = registry.dispatch("list_competencies", '{"so_lacunas": true}')
    assert resultado["ok"] is True
    assert all(linha["lacuna"] for linha in resultado["data"])


def test_argumentos_vazios_do_provedor(registry):
    """Alguns provedores mandam "" ou null quando a tool não tem parâmetro."""
    for vazio in ("", None, "{}"):
        assert registry.dispatch("list_competencies", vazio)["ok"] is True


def test_json_quebrado_vira_erro_legivel(registry):
    resultado = registry.dispatch("list_competencies", "{nao é json")
    assert resultado["error"]["code"] == "argumentos_invalidos"


def test_parametro_inventado_nao_derruba_o_loop(registry):
    resultado = registry.dispatch("list_competencies", '{"inventado": 1}')
    assert resultado["ok"] is False
    assert resultado["error"]["code"] == "argumentos_invalidos"


def test_regra_de_negocio_volta_como_erro_e_nao_grava(registry, banco):
    """Nível 2 sem evidência é recusado — é a regra que segura o currículo."""
    resultado = registry.dispatch(
        "assess_competency", {"slug": "python", "nivel": 2, "justificativa": "acho que sim"}
    )
    assert resultado["error"]["code"] == "regra_violada"
    assert "evidência" in resultado["error"]["message"]
    assert banco.execute("SELECT COUNT(*) FROM competency_state").fetchone()[0] == 0


def test_competencia_inexistente(registry):
    resultado = registry.dispatch("link_evidence", {"slug": "cobol", "referencia": "pipeline"})
    assert resultado["error"]["code"] == "regra_violada"


def test_confirmacao_recusada_nao_grava(banco):
    registry = Registry(conn=banco, confirmar=lambda tool, args: False)
    resultado = registry.dispatch(
        "link_evidence", {"slug": "python", "referencia": "pipeline"}
    )
    assert resultado["error"]["code"] == "cancelado"
    assert banco.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0


def test_confirmacao_aceita_grava(banco):
    vistas = []
    registry = Registry(conn=banco, confirmar=lambda tool, args: vistas.append(tool.nome) or True)
    resultado = registry.dispatch("link_evidence", {"slug": "python", "referencia": "pipeline"})
    assert resultado["ok"] is True
    assert vistas == ["link_evidence"]
    assert banco.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1


def test_tool_de_leitura_nao_pede_confirmacao(banco):
    registry = Registry(conn=banco, confirmar=lambda tool, args: pytest.fail("não devia perguntar"))
    assert registry.dispatch("vault_search_facts", '{"query": "pipeline"}')["ok"] is True


def test_contadores_alimentam_a_tabela_runs(banco):
    status = RunStatus()
    registry = Registry(conn=banco, status=status)
    registry.dispatch("list_competencies", "{}")
    registry.dispatch("tool_que_nao_existe", "{}")
    assert status.tool_calls == 2
    assert status.tool_errors == 1


def test_tool_declara_se_escreve():
    from hermes.agent.registry import TOOLS

    escrevem = {t.nome for t in TOOLS if t.escreve}
    assert escrevem == {
        "link_evidence", "assess_competency", "parse_job", "match_job",
        "log_study", "git_activity", "confirm_study_signals", "plan_week",
    }
    assert all(t.pede_confirmacao for t in TOOLS if t.escreve), "toda escrita passa pelo guarda"
    assert isinstance(TOOLS[0], Tool)


# ------------------------------------------------------------------- vagas (fase 4)


def _vaga_mockada(mocker, conteudo='{"empresa": "X", "titulo": "Y", "requisitos": []}'):
    from types import SimpleNamespace

    import litellm

    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    return mocker.patch.object(
        litellm,
        "completion",
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo, tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        ),
    )


def test_parse_job_recebe_status_modelo_e_denylist_da_sessao(banco, mocker):
    completion = _vaga_mockada(mocker)
    status = RunStatus()
    registry = Registry(conn=banco, status=status, model="modelo-da-sessao")

    resultado = registry.dispatch("parse_job", {"texto": "Vaga de automação. " * 20})

    assert resultado["ok"] is True
    assert completion.call_args.kwargs["model"] == "modelo-da-sessao"
    assert status.llm_calls == 1  # o custo da tool entra no teto da sessão


def test_modelo_nao_consegue_sobrepor_o_contexto_injetado(banco, mocker):
    completion = _vaga_mockada(mocker)
    registry = Registry(conn=banco, denylist=("segredo",))

    resultado = registry.dispatch("parse_job", {"texto": "segredo " * 40, "denylist": []})

    assert resultado["error"]["code"] == "argumentos_invalidos"
    completion.assert_not_called()


def test_denylist_da_sessao_vale_para_a_vaga(banco, mocker):
    completion = _vaga_mockada(mocker)
    registry = Registry(conn=banco, denylist=("segredo",))

    resultado = registry.dispatch("parse_job", {"texto": "vaga com segredo interno " * 20})

    assert resultado["error"]["code"] == "vaga_recusada"
    completion.assert_not_called()


def test_falha_do_provedor_numa_tool_volta_como_erro(banco, mocker):
    completion = _vaga_mockada(mocker)
    completion.side_effect = RuntimeError("503 do provedor")
    registry = Registry(conn=banco)

    resultado = registry.dispatch("parse_job", {"texto": "Vaga de automação. " * 20})

    assert resultado["error"]["code"] == "falha_llm"
    assert "503" in resultado["error"]["message"]


# ----------------------------------------------------------------- estudos (fase 5)


def test_tool_isenta_grava_sem_perguntar(banco):
    perguntas = []
    registry = Registry(
        conn=banco,
        confirmar=lambda tool, args: perguntas.append(tool.nome) or False,
        sem_confirmacao=frozenset({"log_study"}),
    )
    ok = registry.dispatch("log_study", {"minutos": 30, "o_que_fez": "li a doc do httpx"})
    recusado = registry.dispatch("assess_competency", {"slug": "python", "nivel": 1, "justificativa": "x"})

    assert ok["ok"] is True
    assert recusado["error"]["code"] == "cancelado"
    assert perguntas == ["assess_competency"]


def test_regra_de_estudo_volta_como_regra_violada(banco):
    registry = Registry(conn=banco)
    r = registry.dispatch("log_study", {"minutos": 0, "o_que_fez": "nada"})
    assert r["error"]["code"] == "regra_violada"


# --- candidaturas: só leitura, sem confirmação ---------------------------------------


def _candidatura_com_email(banco, corpo):
    from hermes.domain import candidaturas as cand

    cid = cand.registrar_manual(banco, "Áureo", "geral", "Estágio Corporativo")
    eid = cand.inserir_email(banco, {"gmail_id": "g1", "recebido_em": "2026-09-23T13:02:00+00:00",
                                     "de": "rh@aureo.com.br", "assunto": "Queremos te conhecer melhor",
                                     "corpo": corpo, "final": "avanco"})
    cand.ligar_manual(banco, eid, cid)
    return cid


def test_candidaturas_respondem_sem_pedir_confirmacao(banco):
    cid = _candidatura_com_email(banco, "Olá, Fulano! " + "x" * 3000)
    registry = Registry(conn=banco, confirmar=lambda *_: pytest.fail("leitura não pede confirmação"))

    lista = registry.dispatch("list_applications", {"status": "em_processo"})
    assert lista["ok"] and [c["id"] for c in lista["data"]] == [cid]
    assert lista["data"][0]["n_emails"] == 1

    detalhe = registry.dispatch("application_detail", {"candidatura_id": cid})["data"]
    corpo = detalhe["emails"][0]["corpo"]
    assert corpo.startswith("Olá, Fulano!") and corpo.endswith("…") and len(corpo) == 1501

    notas = registry.dispatch("profile_scores", {})["data"]
    assert notas["perfis"][0]["perfil"] == "geral" and "regra" in notas


def test_candidatura_inexistente_e_status_invalido_voltam_como_erro(banco):
    registry = Registry(conn=banco)
    assert registry.dispatch("application_detail", {"candidatura_id": 99})["error"]["code"] == "regra_violada"
    assert registry.dispatch("list_applications", {"status": "aprovada"})["error"]["code"] == "valor_invalido"


def test_list_jobs_acha_o_id_e_filtra_por_status(banco):
    for empresa, status in (("Áureo", "novo"), ("Quartzo", "descartado"), ("Voa", "analisado")):
        banco.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em, status)"
            " VALUES (?, 'Engenharia de Software', 'colado', 't', ?, '2026-09-23', ?)", (empresa, empresa, status))
    banco.commit()
    registry = Registry(conn=banco, confirmar=lambda *_: pytest.fail("leitura não pede confirmação"))
    todas = registry.dispatch("list_jobs", {})["data"]
    assert {v["empresa"] for v in todas} == {"Áureo", "Quartzo", "Voa"} and all(v["score"] is None for v in todas)  # sem requisitos: sem nota
    assert {v["empresa"] for v in registry.dispatch("list_jobs", {"status": "abertas"})["data"]} == {"Áureo", "Voa"}
    abertas = registry.dispatch("list_jobs", {"status": "novo"})["data"]
    assert [v["empresa"] for v in abertas] == ["Áureo"]
    assert registry.dispatch("list_jobs", {"status": "aberta"})["error"]["code"] == "valor_invalido"
