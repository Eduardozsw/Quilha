"""Leitura tolerante do JSON devolvido pelo modelo.

O prompt pede "responda só com o JSON", mas o modelo às vezes escreve texto em volta, usa cerca
de markdown, esquece o colchete externo ou é cortado no `max_tokens`. `json.loads` quebra em
todos esses casos ("Extra data", "Expecting value"). Aqui a resposta é varrida à procura do
primeiro valor que decodifica e tem o formato esperado.
"""

from __future__ import annotations

import json
import re

_DECODER = json.JSONDecoder()
_VALUE_START = re.compile(r"[\[{]")
_SEPARATOR = re.compile(r"\s*,\s*")


def _decode_at(text: str, pos: int):
    try:
        return _DECODER.raw_decode(text, pos)
    except json.JSONDecodeError:
        return None, None


def _loose_items(text: str, pos: int, item_type: type) -> list:
    """Lê `item, item, ...` a partir de `pos` até o primeiro valor que não seja `item_type`."""
    items: list = []
    while True:
        value, end = _decode_at(text, pos)
        if not isinstance(value, item_type):
            return items
        items.append(value)
        sep = _SEPARATOR.match(text, end)
        if sep is None:
            return items
        pos = sep.end()


def extract_json_list(text: str, item_type: type) -> list:
    """Devolve a lista de `item_type` contida na resposta do modelo.

    1. A primeira lista JSON não vazia cujos itens são todos `item_type`; o que vier antes ou
       depois dela é ignorado.
    2. Senão, itens `item_type` soltos a partir do primeiro que decodificar: `[0, 3], [1]` sem
       colchete externo, ou os objetos completos de uma lista cortada no meio.
    """
    starts = [m.start() for m in _VALUE_START.finditer(text)]

    for pos in starts:
        value, _ = _decode_at(text, pos)
        if isinstance(value, list) and value and all(isinstance(v, item_type) for v in value):
            return value

    for pos in starts:
        items = _loose_items(text, pos, item_type)
        if items:
            return items

    raise ValueError(f"nenhuma lista JSON de {item_type.__name__} na resposta")


def extract_json_object(text: str, chaves: tuple[str, ...] = ()) -> dict:
    """Devolve o primeiro objeto JSON da resposta.

    `chaves` exige que o objeto contenha todas elas — evita pegar um objeto aninhado ou um
    exemplo que o modelo escreveu antes da resposta de verdade. Sem `chaves`, vale o primeiro
    objeto que decodificar.
    """
    for m in re.finditer(r"\{", text):
        value, _ = _decode_at(text, m.start())
        if isinstance(value, dict) and all(k in value for k in chaves):
            return value

    esperado = f" com {', '.join(chaves)}" if chaves else ""
    raise ValueError(f"nenhum objeto JSON{esperado} na resposta")
