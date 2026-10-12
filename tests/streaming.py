"""Chunks de streaming montados à mão, nos tipos do LiteLLM, para os testes nunca tocarem um provedor.

`em_chunks` converte uma resposta simulada sem streaming (o `SimpleNamespace` com `choices[0].message`
que os testes antigos usam) nos chunks que o provedor mandaria com `stream=True`: o texto, cada
`tool_call` inteira e, por último, o `usage` (como o OpenAI faz com `include_usage`).
"""

from __future__ import annotations

from litellm.types.utils import (
    ChatCompletionDeltaToolCall,
    Delta,
    Function,
    ModelResponseStream,
    StreamingChoices,
    Usage,
)


def chunk(content=None, tool_calls=None, finish=None, usage=None, model="gpt-4o-mini"):
    r = ModelResponseStream(
        id="chatcmpl-teste", model=model,
        choices=[StreamingChoices(index=0, delta=Delta(content=content, tool_calls=tool_calls),
                                  finish_reason=finish)],
    )
    if usage is not None:
        r.usage = usage
    return r


def delta_tool(index, id=None, nome=None, argumentos=None):
    return ChatCompletionDeltaToolCall(index=index, id=id, type="function" if id else None,
                                       function=Function(name=nome, arguments=argumentos or ""))


def uso(prompt=10, completion=5):
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)


def em_chunks(resposta) -> list:
    mensagem = resposta.choices[0].message
    chunks = []
    if getattr(mensagem, "content", None):
        chunks.append(chunk(mensagem.content))
    for i, c in enumerate(getattr(mensagem, "tool_calls", None) or []):
        chunks.append(chunk(tool_calls=[delta_tool(i, c.id, c.function.name, c.function.arguments)]))
    chunks.append(chunk(finish="tool_calls" if getattr(mensagem, "tool_calls", None) else "stop"))
    usage = getattr(resposta, "usage", None)
    if usage is not None:
        chunks.append(chunk(usage=uso(usage.prompt_tokens, usage.completion_tokens)))
    return chunks


def e_resposta_sem_stream(r) -> bool:
    escolhas = getattr(r, "choices", None)
    return bool(escolhas) and getattr(escolhas[0], "message", None) is not None
