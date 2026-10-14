"""Contrato de cada resposta que um modelo escreve para o Quilha: o formato (esquema JSON) e as regras.

Toda resposta em JSON passa por `llm.pedir_json`, que exige um contrato — a do LLM do usuário e a do modelo
do cliente MCP, pelo mesmo caminho. O formato é tolerante como sempre foi: item ruim é descartado com aviso,
campo extra é ignorado. Só a resposta inutilizável no todo é recusada (`RespostaInvalida`). O esquema
orienta quem escreve (vai ao cliente MCP no pedido); quem decide o que entra são as regras de `validar`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class RespostaInvalida(ValueError):
    """Resposta sem o formato mínimo do contrato: não é um objeto JSON ou falta a chave principal."""


@dataclass(frozen=True)
class Contrato:
    nome: str
    esquema: dict
    chaves: tuple[str, ...]  # o que o objeto precisa ter para ser a resposta (e não um exemplo aninhado)
    validar: Callable[[dict, Any, Any], Any]  # (bruto, contexto, status) -> resposta limpa
