"""Camada única de acesso ao LLM, via LiteLLM.

Todo o resto do Hermes fala com o modelo por aqui: é o único lugar que conhece nome de provedor,
retries, timeout e preço. Trocar de provedor é trocar `LLM_MODEL` no `.env`.

O `import litellm` é preguiçoso de propósito: ele custa alguns segundos, e `quilha check`,
`index`, `comp` e `stats` não chamam modelo nenhum. Quem não usa LLM não paga o import.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import os
import re
import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from hermes.run_status import RunStatus

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_NUM_RETRIES = 3
DEFAULT_TIMEOUT = 60.0  # segundos por tentativa


class FalhaLLM(RuntimeError):
    """O provedor do LLM recusou ou não respondeu (chave, cota, rede). A tela oferece "Configurar LLM"."""


# trechos com cara de chave de provedor (OpenAI, Anthropic, Groq, xAI, Google), inteiros ou ecoados com asteriscos
# prefixo + separador + 8 ou mais caracteres com pelo menos um dígito ou `*` (eco parcial): `sk-learn`,
# `pkg_resources` e `skeleton` não são chaves. As do Google não têm separador, mas têm 39 caracteres.
_CARA_DE_CHAVE = re.compile(
    r"\b(?:(?:sk-ant|sk|pk|rk|gsk|xai)[-_](?=[-_A-Za-z0-9*]*[0-9*])[-_A-Za-z0-9*]{8,}|AIza[-_A-Za-z0-9]{20,})")


def mascarar_chaves(texto: str) -> str:
    """Tira chaves de API do texto que vai para a tela e para `runs.error`: alguns provedores ecoam a chave
    (ou um pedaço dela) na mensagem de recusa."""
    for nome in ("LLM_API_KEY", "TYPESAFE_API_KEY"):
        valor = (os.getenv(nome) or "").strip()
        if len(valor) >= 8:
            texto = texto.replace(valor, "***")
    return _CARA_DE_CHAVE.sub("***", texto)


def _falha_do_provedor(e: Exception) -> FalhaLLM:
    nome = type(e).__name__
    if nome in ("AuthenticationError", "PermissionDeniedError"):
        texto = "o provedor do LLM recusou a chave; confira em Configurações → LLM"
    elif nome == "RateLimitError":
        texto = "o provedor do LLM recusou por cota ou limite de uso; confira o saldo da conta"
    elif nome in ("APIConnectionError", "Timeout", "ServiceUnavailableError"):
        texto = "sem conexão com o provedor do LLM; confira a internet e tente de novo"
    elif nome == "NotFoundError":
        texto = "o modelo configurado não existe no provedor; confira em Configurações → LLM"
    else:
        texto = "o provedor do LLM falhou"
    detalhe = mascarar_chaves((str(e).splitlines() or [""])[0])[:200]
    return FalhaLLM(f"{texto} ({detalhe})")


class Parado(Exception):
    """O usuário apertou "Parar" no meio da resposta. `parcial` é o texto que já tinha chegado."""

    def __init__(self, parcial: str):
        super().__init__("resposta parada pelo usuário")
        self.parcial = parcial


class CostLimitError(RuntimeError):
    """Teto de custo da sessão estourado. Quem chamou decide como encerrar."""


def current_model() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def _litellm():
    import litellm  # import preguiçoso: ver a docstring do módulo

    return litellm


def _base_kwargs(model: str | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model or current_model(),
        # o LiteLLM refaz a chamada com backoff em erro transitório (rate limit, 5xx, timeout)
        "num_retries": int(os.getenv("LLM_NUM_RETRIES", DEFAULT_NUM_RETRIES)),
        "timeout": float(os.getenv("LLM_TIMEOUT", DEFAULT_TIMEOUT)),
    }
    if api_base := os.getenv("LLM_API_BASE"):
        kwargs["api_base"] = api_base
    if api_key := os.getenv("LLM_API_KEY"):
        kwargs["api_key"] = api_key
    return kwargs


def _record_usage(response, status: RunStatus | None, custo_conhecido: bool = True) -> None:
    if status is None:
        return
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    cost = None
    if custo_conhecido:
        try:
            cost = float(_litellm().completion_cost(completion_response=response))
        except Exception as e:  # modelo fora da tabela de preços do LiteLLM (ex.: local)
            logger.warning("custo da chamada desconhecido: %s", e)
    status.record_usage(int(prompt), int(completion), cost)


def _aceita(parametro: str, model: str | None = None) -> bool:
    try:
        params = _litellm().get_supported_openai_params(model=model or current_model())
    except Exception as e:
        logger.warning("não deu para consultar os parâmetros do modelo: %s", e)
        return False
    return bool(params) and parametro in params


def supports_json_mode(model: str | None = None) -> bool:
    """`response_format={"type":"json_object"}` só vai para provedor que aceita."""
    return _aceita("response_format", model)


def _do_provedor(e: Exception) -> bool:
    return type(e).__module__.startswith(("litellm", "openai", "httpx"))


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    status: RunStatus | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    json_mode: bool = False,
):
    """Uma chamada ao modelo. Devolve a mensagem crua — pode trazer `tool_calls`.

    Não interpreta nada: quem decide o que fazer com `tool_calls` é o loop do agente.
    """
    kwargs = _base_kwargs(model)
    kwargs.update(messages=messages, temperature=temperature, max_tokens=max_tokens)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if json_mode and supports_json_mode(kwargs["model"]):
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = _litellm().completion(**kwargs)
    except Exception as e:  # noqa: BLE001 — só as do provedor viram FalhaLLM; o resto sobe como veio
        if _do_provedor(e):
            raise _falha_do_provedor(e) from e
        raise
    _record_usage(response, status)
    return response.choices[0].message


def chat_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    status: RunStatus | None = None,
    model: str | None = None,
    on_trecho: Callable[[str], None] | None = None,
    parar: threading.Event | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
):
    """Como `chat`, com a resposta em streaming: `on_trecho(texto)` a cada pedaço do texto.

    `tool_calls` chegam picadas (nome e argumentos em pedaços); o `stream_chunk_builder` do LiteLLM
    remonta a mensagem no mesmo formato de `chat`. Com `parar` ligado, para de ler e levanta
    `Parado` com o texto que já chegou. Sem `usage` no stream (provedor que não manda), o LiteLLM
    estima os tokens, mas o custo fica desconhecido: preço sobre estimativa seria um número inventado.
    """
    kwargs = _base_kwargs(model)
    kwargs.update(messages=messages, temperature=temperature, max_tokens=max_tokens, stream=True)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if _aceita("stream_options", kwargs["model"]):
        kwargs["stream_options"] = {"include_usage": True}

    chunks: list = []
    texto: list[str] = []
    fonte = None

    def parado() -> Parado:
        # o provedor cobra a chamada interrompida: os tokens entram na conta, com custo desconhecido (estimativa)
        _registrar_parcial(chunks, messages, status, kwargs["model"])
        return Parado("".join(texto))

    try:
        fonte = _litellm().completion(**kwargs)
        for chunk in fonte:
            if parar is not None and parar.is_set():
                raise parado()
            chunks.append(chunk)
            for escolha in getattr(chunk, "choices", None) or []:
                pedaco = getattr(getattr(escolha, "delta", None), "content", None)
                if pedaco:
                    texto.append(pedaco)
                    if on_trecho is not None:
                        on_trecho(pedaco)
    except Parado:
        raise
    except Exception as e:  # noqa: BLE001 — como em `chat`
        # a conexão caiu no meio: o texto que já apareceu na tela vai junto, para o loop gravar
        falha = _falha_do_provedor(e) if _do_provedor(e) else e
        falha.parcial = "".join(texto)
        if falha is e:
            raise
        raise falha from e
    if parar is not None and parar.is_set():
        raise parado()

    # sem `stream_options` (Anthropic, Gemini) o `CustomStreamWrapper` tira o `usage` dos chunks que entrega
    # e guarda os originais, com o `usage` do provedor, em `.chunks`: é dali que sai o custo de verdade
    originais = getattr(fonte, "chunks", None)
    if isinstance(originais, list) and originais:
        chunks = originais
    response = _litellm().stream_chunk_builder(chunks, messages=messages)
    if response is None:
        raise FalhaLLM("o provedor do LLM falhou (stream vazio)")
    com_usage = any(getattr(c, "usage", None) is not None for c in chunks)
    _record_usage(response, status, custo_conhecido=com_usage)
    return response.choices[0].message


def _registrar_parcial(chunks: list, messages: list[dict], status: RunStatus | None, model: str) -> None:
    """Tokens da chamada parada no meio: o que já chegou, remontado; parada antes do primeiro trecho, só o prompt.
    O provedor cobra a chamada interrompida, então ela entra no total com o preço da tabela sobre essa contagem
    (estimativa, mas que nunca faz o total cair). Sem preço conhecido, o custo fica desconhecido.
    Nunca derruba o "Parar"."""
    if status is None:
        return
    prompt = completion = 0
    custo = None
    try:
        resposta = _litellm().stream_chunk_builder(chunks, messages=messages) if chunks else None
        uso = getattr(resposta, "usage", None)
        if uso is not None:
            prompt, completion = uso.prompt_tokens or 0, uso.completion_tokens or 0
        else:
            prompt = _litellm().token_counter(model=model, messages=messages)
        de_prompt, de_resposta = _litellm().cost_per_token(model=model, prompt_tokens=int(prompt),
                                                           completion_tokens=int(completion))
        custo = float(de_prompt) + float(de_resposta)
    except Exception as e:  # noqa: BLE001
        logger.warning("custo da chamada parada desconhecido: %s", e)
    status.record_usage(int(prompt), int(completion), custo)


class PrecisaDeTexto(Exception):
    """Sem LLM próprio (servidor MCP): quem escreve esta resposta é o modelo do cliente.

    Levantada no lugar da chamada ao provedor, antes de qualquer gravação da tool — as quatro tools que
    usam modelo chamam `complete` antes de gravar. `chave` identifica o pedido: a resposta do cliente só
    vale para exatamente este system + entrada.
    """

    def __init__(self, system: str, user: str, chave: str, contrato=None):
        self.system, self.user, self.chave = system, user, chave
        self.contrato = contrato  # `contratos.Contrato` da resposta pedida; vai ao cliente como esquema
        super().__init__("esta etapa precisa do texto do modelo do cliente")


_externas: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("respostas_externas", default=None)


def chave_do_pedido(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\0{user}".encode("utf-8")).hexdigest()[:16]


@contextmanager
def respostas_externas(respostas: dict[str, str]):
    """Dentro do bloco, `complete` devolve a resposta guardada para o pedido ou levanta `PrecisaDeTexto`."""
    token = _externas.set(dict(respostas))
    try:
        yield
    finally:
        _externas.reset(token)


def complete(
    system: str,
    user: str,
    status: RunStatus | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    json_mode: bool = False,
    contrato=None,
) -> str:
    """Chamada de turno único, sem ferramenta. Devolve o texto."""
    externas = _externas.get()
    if externas is not None:
        chave = chave_do_pedido(system, user)
        if chave in externas:
            return externas[chave]
        raise PrecisaDeTexto(system, user, chave, contrato)
    message = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        status=status,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )
    content = getattr(message, "content", None)
    if not content:
        raise ValueError("o modelo devolveu conteúdo vazio")
    return content


def pedir_json(system: str, user: str, contrato, contexto=None, *, status: RunStatus | None = None,
               model: str | None = None, temperature: float = 0.2):
    """Uma resposta em JSON, validada pelo contrato. Vale para o LLM do usuário e para o modelo do cliente MCP."""
    from hermes.contratos import RespostaInvalida
    from hermes.json_parse import extract_json_object

    texto = complete(system, user, status=status, model=model, temperature=temperature, json_mode=True,
                     contrato=contrato)
    try:
        bruto = extract_json_object(texto, contrato.chaves)
    except ValueError:
        raise RespostaInvalida(
            f"resposta fora do formato `{contrato.nome}`: precisa ser um objeto JSON com "
            f"{', '.join(f'`{c}`' for c in contrato.chaves)}"
        ) from None
    return contrato.validar(bruto, contexto, status)


def check_cost_limit(status: RunStatus, teto_usd: float) -> None:
    """Aborta antes da próxima chamada quando a sessão já passou do teto.

    Custo desconhecido (modelo fora da tabela de preços) **não** para nada: seria travar o uso de
    modelo local. O aviso fica no `RunStatus` e a execução termina como `partial`.
    """
    gasto = status.cost_usd
    if gasto is None:
        return
    if gasto >= teto_usd:
        raise CostLimitError(
            f"teto de custo da sessão atingido: US$ {gasto:.4f} de US$ {teto_usd:.2f}"
        )
