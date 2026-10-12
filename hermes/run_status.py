"""Acumulador de avisos e métricas de uma execução.

O mesmo objeto atravessa todas as etapas de um comando: cada etapa relata falha
parcial sem derrubar o resto. É o que alimenta a linha da tabela `runs`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunStatus:
    warnings: list[str] = field(default_factory=list)
    llm_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _cost: float = 0.0
    cost_unknown: bool = False

    def add(self, msg: str) -> None:
        self.warnings.append(msg)

    def record_usage(
        self, prompt: int, completion: int, cost: float | None
    ) -> None:
        self.llm_calls += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        if cost is None:
            self.cost_unknown = True
        else:
            self._cost += cost

    @property
    def cost_usd(self) -> float | None:
        """None quando alguma chamada ficou sem preço conhecido — nunca 0."""
        return None if self.cost_unknown else self._cost


def final_status(status: RunStatus, crashed: bool, delivered: bool) -> str:
    if crashed or not delivered:
        return "failed"
    if status.warnings or status.tool_errors:
        return "partial"
    return "success"
