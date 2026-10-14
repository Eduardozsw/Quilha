import json

import pytest

from hermes import llm
from hermes.contratos import RespostaInvalida
from hermes.domain import curriculo, estudos, vaga
from hermes.run_status import RunStatus


def _com(contrato, resposta, contexto, texto=None):
    """Passa `resposta` pelo contrato do jeito que a do modelo passa (modo externo, chave do pedido)."""
    status = RunStatus()
    chave = llm.chave_do_pedido("s", "u")
    with llm.respostas_externas({chave: texto if texto is not None else json.dumps(resposta)}):
        return llm.pedir_json("s", "u", contrato, contexto, status=status), status


def test_extracao_tolera_o_que_tolerava():
    limpo, status = _com(vaga.CONTRATO_EXTRACAO, {
        "empresa": "null", "titulo": " Analista ", "extra": "ignorado",
        "requisitos": [
            "não é objeto",
            {"texto": "  ", "tipo": "obrigatorio"},
            {"texto": "Python", "tipo": "talvez", "competencia_sugerida": "python", "confianca": "alta"},
            {"texto": "Airflow", "tipo": "desejavel", "competencia_sugerida": "airflow", "confianca": 0.7},
        ],
    }, {"python"})

    assert limpo["empresa"] is None and limpo["titulo"] == "Analista"
    assert [(r["texto"], r["tipo"], r["competencia"], r["confianca"]) for r in limpo["requisitos"]] == [
        ("Python", "obrigatorio", "python", None),
        ("Airflow", "desejavel", None, None),
    ]
    assert limpo["sugeridos_fora"] == ["airflow"]
    assert len(status.warnings) >= 2  # sem texto, tipo inválido


def test_extracao_aceita_json_com_texto_em_volta():
    texto = 'Claro! Aqui está:\n```json\n{"requisitos": [{"texto": "SQL", "tipo": "obrigatorio"}]}\n```'
    limpo, _ = _com(vaga.CONTRATO_EXTRACAO, None, {"sql"}, texto=texto)
    assert [r["texto"] for r in limpo["requisitos"]] == ["SQL"]


def test_sem_a_chave_principal_e_recusado_com_o_formato():
    with pytest.raises(RespostaInvalida, match="requisitos"):
        _com(vaga.CONTRATO_EXTRACAO, {"outra": 1}, {"python"})


def test_match_descarta_comentario_de_lacuna_que_nao_existe():
    faltas = [{"requisito_id": 7, "ligadas": [], "candidatos": []}]
    itens = [{"requisito_id": 7}, {"requisito_id": 8}]
    limpo, status = _com(vaga.CONTRATO_MATCH, {
        "lacunas": {"7": "estude SQL", "99": "inventada", "8": "  "},
        "riscos": ["vão perguntar de Airflow", "  ", 3],
    }, (itens, faltas))

    assert limpo["comentarios"] == {"7": "estude SQL"}
    assert limpo["riscos"] == ["vão perguntar de Airflow", "3"]
    assert status.warnings


def test_plano_descarta_item_fora_das_lacunas_e_o_que_estoura():
    contexto = {"por_slug": {"sql": {"obrigatorio_em": [1], "vagas": {1}}}, "ids": {"sql": 10},
                "total": 0, "minutos": 120}
    limpo, status = _com(estudos.CONTRATO_PLANO, {"objetivo": "SQL", "itens": [
        {"competencia": "sql", "descricao": "modelar 3 tabelas", "minutos": "90"},
        {"competencia": "python", "descricao": "fora", "minutos": 30},
        {"competencia": "sql", "descricao": "", "minutos": 10},
        {"competencia": "sql", "descricao": "estoura", "minutos": 60},
    ]}, contexto)

    assert [(i["competencia"], i["minutos_alvo"]) for i in limpo["itens"]] == [("sql", 90)]
    assert limpo["total"] == 90
    assert len(status.warnings) == 3


def test_redacao_descarta_referencia_inventada_e_texto_vazio():
    selecao = [{"referencia": "a.md#x", "texto": "fato x"}, {"referencia": "a.md#y", "texto": "fato y"}]
    limpo, status = _com(curriculo.CONTRATO_REDACAO, {
        "resumo": " Resumo ", "bullets": {"a.md#x": "X reescrito", "a.md#z": "inventado", "a.md#y": " "},
    }, selecao)

    assert limpo == {"resumo": "Resumo", "bullets": {"a.md#x": "X reescrito"}}
    assert len(status.warnings) == 3  # inventada, vazia, 1 fato com texto original


def test_pedido_externo_leva_o_esquema():
    with llm.respostas_externas({}):
        with pytest.raises(llm.PrecisaDeTexto) as pedido:
            llm.pedir_json("s", "u", vaga.CONTRATO_EXTRACAO, {"python"})
    assert pedido.value.contrato is vaga.CONTRATO_EXTRACAO
    assert pedido.value.contrato.esquema["required"] == ["requisitos"]
