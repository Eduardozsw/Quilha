"""O modelo raramente devolve JSON limpo. Estes são os casos reais que já quebraram o parse."""

import pytest

from hermes.json_parse import extract_json_list, extract_json_object


def test_lista_limpa():
    assert extract_json_list('[{"a": 1}, {"a": 2}]', dict) == [{"a": 1}, {"a": 2}]


def test_ignora_texto_e_cerca_de_markdown():
    texto = 'Claro! Aqui está:\n```json\n[{"slug": "python"}]\n```\nEspero ter ajudado.'
    assert extract_json_list(texto, dict) == [{"slug": "python"}]


def test_lista_cortada_no_max_tokens_devolve_os_itens_completos():
    texto = '[{"texto": "um"}, {"texto": "dois"}, {"texto": "tr'
    assert extract_json_list(texto, dict) == [{"texto": "um"}, {"texto": "dois"}]


def test_sem_colchete_externo():
    assert extract_json_list('{"a": 1}, {"a": 2}', dict) == [{"a": 1}, {"a": 2}]


def test_ignora_lista_vazia_e_pega_a_seguinte():
    assert extract_json_list('[] depois [{"a": 1}]', dict) == [{"a": 1}]


def test_lista_do_tipo_errado_nao_conta():
    with pytest.raises(ValueError, match="dict"):
        extract_json_list("[1, 2, 3]", dict)


def test_objeto_exige_as_chaves_pedidas():
    texto = 'Exemplo de formato: {"empresa": "..."}\nResposta: {"empresa": "Aurora Saúde Digital", "titulo": "RPA"}'
    assert extract_json_object(texto, ("empresa", "titulo")) == {
        "empresa": "Aurora Saúde Digital",
        "titulo": "RPA",
    }


def test_objeto_sem_as_chaves_falha():
    with pytest.raises(ValueError, match="empresa"):
        extract_json_object('{"outra": 1}', ("empresa",))
