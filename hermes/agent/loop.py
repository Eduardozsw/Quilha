"""Loop de tool-calling: completion → tool_calls → despacho → completion.

Próprio, não de framework: o que decide o custo de uma sessão é o
que entra no contexto, e isso precisa estar visível. Tudo que corta custo está aqui — teto de
iterações, teto de gasto, truncamento de resultado e recorte do histórico.

O loop não imprime nada. Quem quiser mostrar progresso passa `on_evento`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from hermes import llm
from hermes.agent import session as sessao_mod
from hermes.agent.prompt import SYSTEM
from hermes.agent.registry import Registry
from hermes.run_status import RunStatus

MAX_ITERACOES = 8
MAX_CHARS_RESULTADO = 4_000

SYSTEM_RESUMO = (
    "Resuma a conversa abaixo em no máximo 10 linhas, preservando decisões tomadas, números "
    "citados com sua origem e referências de fatos (`nota.md#block-id`). Descarte cortesia."
)


PULADA_PELO_PARAR = {"ok": False, "error": {"code": "cancelado",
                                           "message": "o usuário parou a resposta antes desta ferramenta"}}


@dataclass
class Turno:
    resposta: str | None = None
    iteracoes: int = 0
    parou_por: str | None = None  # None = terminou normalmente
    tools_usadas: list[str] = field(default_factory=list)
    resultados: list[tuple[str, dict]] = field(default_factory=list)  # (ferramenta, resultado), para os cartões

    @property
    def completo(self) -> bool:
        return self.parou_por is None


def responder(
    sessao: sessao_mod.Session,
    registry: Registry,
    pergunta: str,
    status: RunStatus,
    teto_usd: float,
    model: str | None = None,
    system: str = SYSTEM,
    teto_tokens: int = sessao_mod.TETO_TOKENS_PADRAO,
    max_iteracoes: int = MAX_ITERACOES,
    on_evento: Callable[[str, dict], None] | None = None,
    parar: threading.Event | None = None,
) -> Turno:
    """Roda um turno inteiro: da pergunta até a resposta em texto.

    O texto da resposta sai em trechos (`trecho`) enquanto o modelo escreve. Com `parar` ligado, o
    turno termina como `parado`: o texto parcial fica no histórico, e chamada de ferramenta que o
    Parar pulou recebe resposta de cancelada (o provedor cobra uma resposta por `tool_call`).
    """
    turno = Turno()

    def evento(tipo: str, **dados) -> None:
        if on_evento is not None:
            on_evento(tipo, dados)

    # "Tentar de novo" depois de um erro: a pergunta já está no histórico, sem resposta; gravar de novo
    # deixaria duas perguntas iguais seguidas
    # ...e o parcial de um stream que caiu sai (a resposta nova fica no lugar). Turno interrompido depois de
    # ferramentas também é repetição: as ferramentas que rodaram ficam e o turno continua de onde parou
    descartar_parcial(sessao, pergunta)
    if not _repeticao(sessao.mensagens(), pergunta):
        sessao.gravar({"role": "user", "content": pergunta})
    falhas_seguidas: dict[str, int] = {}

    def parado() -> bool:
        return parar is not None and parar.is_set()

    while turno.iteracoes < max_iteracoes:
        if parado():
            if turno.iteracoes == 0:  # o turno precisa de uma `assistant` para o "Parado" ficar no histórico
                sessao.gravar({"role": "assistant", "content": ""})
            turno.parou_por = "parado"
            return turno
        turno.iteracoes += 1

        try:
            llm.check_cost_limit(status, teto_usd)
        except llm.CostLimitError as e:
            status.add(str(e))
            turno.parou_por = "teto_custo"
            evento("teto_custo", mensagem=str(e))
            return turno

        mensagens = _montar(sessao, system, teto_tokens, status, model)
        evento("chamando_modelo", iteracao=turno.iteracoes)
        try:
            msg = llm.chat_stream(
                mensagens,
                tools=registry.schemas(),
                status=status,
                model=model,
                on_trecho=lambda texto: evento("trecho", texto=texto),
                parar=parar,
            )
        except llm.Parado as p:
            # ferramenta pedida pela metade é descartada: só o texto que já apareceu fica
            sessao.gravar({"role": "assistant", "content": p.parcial})
            turno.resposta = p.parcial
            turno.parou_por = "parado"
            return turno
        except Exception as exc:
            # a conexão caiu no meio da resposta: o que já apareceu na tela fica gravado (e marcado), para
            # o histórico mostrar o mesmo e o "Tentar de novo" saber o que substituir
            if getattr(exc, "parcial", ""):
                sessao.gravar({"role": "assistant", "content": exc.parcial}, meta={"interrompido": True})
            raise
        assistente = _assistant_para_dict(msg)
        sessao.gravar(assistente)

        if not assistente.get("tool_calls"):
            turno.resposta = assistente.get("content") or ""
            return turno

        for chamada in assistente["tool_calls"]:
            nome = chamada["function"]["name"]
            if parado():
                sessao.gravar({"role": "tool", "tool_call_id": chamada["id"],
                               "content": _truncar(PULADA_PELO_PARAR)})
                continue
            turno.tools_usadas.append(nome)
            evento("tool", nome=nome, argumentos=chamada["function"]["arguments"])

            resultado = registry.dispatch(nome, chamada["function"]["arguments"])
            turno.resultados.append((nome, resultado))
            evento("tool_resultado", nome=nome, ok=resultado["ok"])

            # invariante do provedor: uma resposta `tool` por `tool_call_id`, sempre
            sessao.gravar(
                {
                    "role": "tool",
                    "tool_call_id": chamada["id"],
                    "content": _truncar(resultado),
                }
            )

            if resultado["ok"]:
                falhas_seguidas[nome] = 0
            else:
                falhas_seguidas[nome] = falhas_seguidas.get(nome, 0) + 1

        if parado():
            turno.parou_por = "parado"
            return turno

        insistente = next((n for n, q in falhas_seguidas.items() if q >= 2), None)
        if insistente:
            # duas falhas seguidas da mesma tool: insistir daqui só queima crédito
            status.add(f"`{insistente}` falhou duas vezes seguidas; turno encerrado")
            turno.parou_por = "tool_insistente"
            evento("tool_insistente", nome=insistente)
            return turno

    status.add(f"limite de {max_iteracoes} iterações atingido no turno")
    turno.parou_por = "limite_iteracoes"
    evento("limite_iteracoes", max=max_iteracoes)
    return turno


def _repeticao(historico: list[dict], pergunta: str) -> bool:
    """A mesma pergunta do último turno, que não chegou a ter resposta final (erro, stream que caiu)."""
    for m in reversed(historico):
        if m["role"] == "user":
            return m["content"] == pergunta
        if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
            return False  # o turno terminou com resposta: perguntar de novo é pergunta nova
    return False


def descartar_parcial(sessao: sessao_mod.Session, pergunta: str) -> None:
    """Repetição da mesma pergunta depois de um stream que caiu: apaga o texto parcial gravado (marcado
    `interrompido`). Quem guarda onde o turno começa (`proximo_idx`) chama isto antes, senão a resposta nova
    nasce num idx anterior ao marcado e o `meta` do turno não acha onde ficar."""
    com_meta = sessao.mensagens_com_meta()
    if (com_meta and com_meta[-1]["role"] == "assistant" and (com_meta[-1]["meta"] or {}).get("interrompido")
            and _repeticao(com_meta[:-1], pergunta)):
        sessao.apagar_ultima()


def _montar(
    sessao: sessao_mod.Session,
    system: str,
    teto_tokens: int,
    status: RunStatus,
    model: str | None,
) -> list[dict]:
    """[system, (resumo), ...histórico que cabe]. Resume o excedente uma vez só."""
    descartadas, mantidas = sessao_mod.recortar(sessao.mensagens(), teto_tokens)

    if descartadas and sessao.resumo is None:
        sessao.definir_resumo(_resumir(descartadas, status, model))

    mensagens = [{"role": "system", "content": system}]
    if sessao.resumo:
        mensagens.append(
            {"role": "system", "content": f"Resumo do que já foi conversado:\n{sessao.resumo}"}
        )
    return mensagens + mantidas


def _resumir(mensagens: list[dict], status: RunStatus, model: str | None) -> str:
    texto = "\n".join(
        f"{m['role']}: {m.get('content') or ''}" for m in mensagens if m.get("content")
    )
    try:
        return llm.complete(SYSTEM_RESUMO, texto, status=status, model=model, max_tokens=600)
    except Exception as e:  # sem resumo a conversa continua, só perde memória antiga
        status.add(f"não deu para resumir o histórico antigo: {e}")
        return "(histórico antigo perdido: o resumo falhou)"


def _truncar(resultado: dict) -> str:
    """Resultado grande entra cortado no contexto — o dado completo continua no banco.

    O corte é envelopado num JSON válido: entregar um fragmento quebrado faria o modelo gastar
    um turno tentando entender o que aconteceu.
    """
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(texto) <= MAX_CHARS_RESULTADO:
        return texto
    return json.dumps(
        {
            "ok": resultado["ok"],
            "truncado": True,
            "aviso": f"resultado cortado em {MAX_CHARS_RESULTADO} caracteres; "
            "refine a busca ou reduza o limite se precisar do resto",
            "trecho": texto[:MAX_CHARS_RESULTADO],
        },
        ensure_ascii=False,
    )


def _assistant_para_dict(msg) -> dict:
    """Normaliza a mensagem do LiteLLM (objeto do provedor) para dict serializável."""
    mensagem: dict = {"role": "assistant", "content": getattr(msg, "content", None)}
    chamadas = getattr(msg, "tool_calls", None) or []
    if chamadas:
        mensagem["tool_calls"] = [
            {
                "id": _attr(c, "id"),
                "type": "function",
                "function": {
                    "name": _attr(_attr(c, "function"), "name"),
                    "arguments": _attr(_attr(c, "function"), "arguments") or "{}",
                },
            }
            for c in chamadas
        ]
    return mensagem


def _attr(obj, nome: str):
    if isinstance(obj, dict):
        return obj.get(nome)
    return getattr(obj, nome, None)
