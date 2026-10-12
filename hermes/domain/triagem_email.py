"""Triagem de e-mails de processo seletivo: pelo LLM do usuário (padrão) ou pelo Jev (TypeSafe).

Os dois devolvem o mesmo formato; a política (limiar, o que é `outro`) fica aqui no código. O Jev dá
probabilidades calibradas; o LLM declara a própria certeza, que é menos confiável — por isso o mesmo
limiar manda o duvidoso para `revisar`. Classificador e caixa de e-mail entram por parâmetro: os
testes usam versões falsas. As colunas `*_jev` do banco guardam o resultado de qualquer um dos dois.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

from hermes import llm
from hermes.domain import candidaturas
from hermes.json_parse import extract_json_object

CATEGORIAS = {
    "avanco": (
        "The company moved the candidate forward and set a next step: an online test or coding "
        "challenge, a case, an interview to schedule or attend, a group dynamic, or a request to "
        "talk with the recruiter or send documents for the next stage."
    ),
    "pendencia": (
        "The application itself is incomplete or needs an account step: finish or complete the "
        "application, confirm the candidate account or e-mail, fill in missing registration data. "
        "It does not mean the company chose the candidate."
    ),
    "inscricao_confirmada": (
        "Confirms the candidate already applied or is registered in the process, "
        "or gives a status update, and asks for no action right now."
    ),
    "reprovado": "Tells the candidate they were not selected or the process ended for them.",
    "outro": (
        "Anything else: job alerts, newsletters, marketing, job board recommendations, "
        "or e-mails unrelated to a specific application."
    ),
}

LABELS = {
    "avanco": "Vagas/Avanço",
    "pendencia": "Vagas/Pendência",
    "inscricao_confirmada": "Vagas/Inscrito",
    "reprovado": "Vagas/Reprovado",
    "revisar": "Vagas/Revisar",
}

MAX_CORPO = 3000  # caracteres do corpo que vão ao Jev; o banco guarda o texto inteiro
LIMIAR = 0.80  # abaixo disso vai para `revisar` em vez de confiar na categoria

def perguntas() -> dict:
    """O que se pergunta ao Jev. Import aqui: só `email sync` precisa do SDK, o resto do Hermes não."""
    from typesafe_sdk import Choice, Noul

    return {
        "e_processo": Noul(
            instructions=(
                "Is this e-mail about a specific job, internship or trainee application "
                "process the recipient is taking part in (not a generic job alert or newsletter)?"
            )
        ),
        "categoria": Choice(
            instructions="What does this recruiting e-mail mean for the candidate right now?",
            criteria=CATEGORIAS,
        ),
        "tem_prazo": Noul(
            instructions="Does the e-mail state a deadline or date by which the candidate must act?"
        ),
    }


def _final(categoria: str, p_categoria: float, p_processo: float) -> str:
    if p_processo < 0.5 or categoria == "outro":
        return "outro"
    if p_categoria < LIMIAR:
        return "revisar"
    return categoria


PROMPT_LLM = """You triage e-mails from a job seeker's inbox. Answer with one JSON object only:
{"e_processo": true|false, "categoria": "<one key below>", "certeza": <0.0-1.0>, "tem_prazo": true|false,
 "entrevista_em": "<ISO 8601 with timezone offset>"|null}

e_processo: is this e-mail about a specific job, internship or trainee application process the
recipient is taking part in (not a generic job alert or newsletter)?
tem_prazo: does it state a deadline or date by which the candidate must act?
certeza: how sure you are of `categoria`. Use below 0.8 when the e-mail is ambiguous.
entrevista_em: only when the e-mail confirms an interview at one specific date AND time, that moment
(e.g. "2026-10-10T14:00:00-03:00"; use the e-mail's timezone, or the offset of `received` if none is
stated). Resolve weekdays,
"amanhã" and dates without a year from `received` (the next such day after it). Use null when the e-mail
offers options to choose from, asks for availability, or gives no time.
categoria — what the e-mail means for the candidate right now:
""" + "\n".join(f"- {k}: {v}" for k, v in CATEGORIAS.items())


def _entrevista_em(valor) -> str | None:
    """Data e hora da entrevista que o modelo extraiu, em ISO com fuso. Fora do formato vira None, sem derrubar a triagem."""
    if not isinstance(valor, str) or ":" not in valor:  # sem hora não é entrevista marcada
        return None
    try:
        quando = datetime.fromisoformat(valor.strip())
    except ValueError:
        return None
    if quando.tzinfo is None:  # o modelo esqueceu o fuso: vale o do computador de quem usa
        quando = quando.astimezone()
    return quando.isoformat(timespec="seconds")


def classificar_llm(email: dict, status=None, model: str | None = None) -> dict:
    """Classifica com o LLM configurado (`LLM_MODEL`). Resposta fora do formato vira exceção (aviso no sync)."""
    corpo = " ".join((email.get("corpo") or "").split())[:MAX_CORPO]
    pedido = {"from": email["de"], "subject": email["assunto"], "body": corpo}
    if email.get("recebido_em"):
        # no fuso de quem usa: "amanhã às 10h" num e-mail das 22h30 não pode virar o dia seguinte do UTC
        pedido["received"] = datetime.fromisoformat(email["recebido_em"]).astimezone().isoformat(timespec="seconds")
    entrada = json.dumps(pedido, ensure_ascii=False)
    t0 = time.perf_counter()
    texto = llm.complete(PROMPT_LLM, entrada, status=status, model=model, temperature=0, max_tokens=200,
                         json_mode=True)
    ms = (time.perf_counter() - t0) * 1000
    r = extract_json_object(texto, ("categoria", "certeza"))
    cat = str(r["categoria"]).strip()
    if cat not in CATEGORIAS:
        raise ValueError(f"o modelo respondeu uma categoria que não existe: {cat!r}")
    p_cat = min(max(float(r["certeza"]), 0.0), 1.0)
    p_proc = 1.0 if r.get("e_processo", True) else 0.0
    return {
        "categoria_jev": cat,
        "prob_categoria": round(p_cat, 3),
        "prob_processo": p_proc,
        "prob_prazo": 1.0 if r.get("tem_prazo") else 0.0,
        "final": _final(cat, p_cat, p_proc),
        "latencia_ms": round(ms),
        "entrevista_em": _entrevista_em(r.get("entrevista_em")),
    }


def com_jev(jev) -> Callable[[dict, object], dict]:
    """Classificador que usa um cliente do Jev. O SDK não passa pelo LiteLLM: a chamada conta aqui."""
    def classificador(email: dict, status) -> dict:
        r = classificar(jev, email)
        status.llm_calls += 1
        return r
    return classificador


def com_llm(model: str | None = None) -> Callable[[dict, object], dict]:
    return lambda email, status: classificar_llm(email, status, model)


class TriagemRecusada(Exception):
    pass


@contextmanager
def classificador_configurado() -> Iterator[tuple[Callable[[dict, object], dict], str]]:
    """O classificador de `EMAIL_CLASSIFICADOR` e o nome para `runs.model`. Padrão: o LLM do usuário."""
    escolha = os.getenv("EMAIL_CLASSIFICADOR", "llm").strip().lower() or "llm"
    if escolha == "llm":
        yield com_llm(), llm.current_model()
        return
    if escolha != "jev":
        raise TriagemRecusada(f"EMAIL_CLASSIFICADOR={escolha!r}: use `llm` ou `jev`.")
    if not os.getenv("TYPESAFE_API_KEY"):
        raise TriagemRecusada("o Jev precisa de TYPESAFE_API_KEY (console.typesafe.ai); ou use EMAIL_CLASSIFICADOR=llm.")
    from typesafe_sdk import TypeSafeClient

    with TypeSafeClient() as jev:
        yield com_jev(jev), "jev"


EMAIL_TESTE = {"de": "Quilha <teste@quilha.invalid>", "assunto": "Teste de conexão",
               "corpo": "Mensagem de teste do Quilha."}


def testar_jev(cliente=None, chave: str | None = None) -> dict:
    """Uma classificação de um e-mail fixo e curto: confere a chave antes de ligar o Jev. A falha volta como resposta."""
    from typesafe_sdk import TypeSafeAuthenticationError, TypeSafeError

    inicio = time.perf_counter()
    try:
        if cliente is not None:
            classificar(cliente, EMAIL_TESTE)
        else:
            from typesafe_sdk import TypeSafeClient

            with TypeSafeClient(api_key=chave) as jev:
                classificar(jev, EMAIL_TESTE)
    except TypeSafeAuthenticationError:
        return {"ok": False, "mensagem": "o Jev recusou a chave"}
    except TypeSafeError as exc:
        return {"ok": False, "mensagem": f"o Jev recusou: {exc}"}
    return {"ok": True, "ms": round((time.perf_counter() - inicio) * 1000)}


def classificar(jev, email: dict) -> dict:
    corpo = " ".join((email.get("corpo") or "").split())[:MAX_CORPO]
    estado = {"from": email["de"], "subject": email["assunto"], "body": corpo}
    t0 = time.perf_counter()
    r = jev.system_one(state=estado, questions=perguntas())
    ms = (time.perf_counter() - t0) * 1000

    cat = r.choices["categoria"]
    p_proc = r.nouls["e_processo"].noul
    p_cat = cat.probabilities[cat.choice]
    final = _final(cat.choice, p_cat, p_proc)
    return {
        "categoria_jev": cat.choice,
        "prob_categoria": round(p_cat, 3),
        "prob_processo": round(p_proc, 3),
        "prob_prazo": round(r.nouls["tem_prazo"].noul, 3),
        "final": final,
        "latencia_ms": round(ms),
    }


def sincronizar(conn: sqlite3.Connection, caixa, classificador, dias: int, maximo: int, status,
                rotular: bool = False) -> dict:
    """Classifica só e-mails novos, do mais antigo para o mais novo, e liga às candidaturas.

    `classificador` é `com_llm()`, `com_jev(cliente)` ou um cliente do Jev direto (embrulhado aqui).

    A ordem importa: a candidatura pingada nasce com a data do primeiro e-mail do processo.
    Erro num e-mail vira aviso e não para os outros; ele é tentado de novo no próximo sync.
    """
    if not callable(classificador):
        classificador = com_jev(classificador)
    ids = caixa.listar_ids(dias, maximo)
    vistos = {r[0] for r in conn.execute("SELECT gmail_id FROM emails")}
    novos = [i for i in ids if i not in vistos]
    emails = []
    for msg_id in novos:
        try:
            emails.append(caixa.ler(msg_id))
        except Exception as exc:  # noqa: BLE001 — um e-mail não derruba o sync
            status.tool_errors += 1
            status.add(f"e-mail {msg_id}: {exc}")
    emails.sort(key=lambda e: e["recebido_em"])

    por_categoria: Counter = Counter()
    ligados = 0
    for email in emails:
        try:
            res = classificador(email, status)
        except Exception as exc:  # noqa: BLE001
            status.tool_errors += 1
            status.add(f"e-mail {email['gmail_id']}: {exc}")
            continue
        empresa = None if res["final"] == "outro" else candidaturas.empresa_do_email(email["de"], email["assunto"])
        email_id = candidaturas.inserir_email(conn, {**email, **res, "empresa_extraida": empresa})
        try:
            if candidaturas.ligar(conn, email_id) is not None:
                ligados += 1
        except Exception as exc:  # noqa: BLE001
            # sem apagar, o gmail_id contaria como visto e o e-mail nunca seria ligado
            with conn:
                conn.execute("DELETE FROM emails WHERE id = ?", (email_id,))
            status.tool_errors += 1
            status.add(f"e-mail {email['gmail_id']}: {exc}")
            continue
        por_categoria[res["final"]] += 1
        if rotular and res["final"] in LABELS:
            try:
                caixa.rotular(email["gmail_id"], LABELS[res["final"]])
            except Exception as exc:  # noqa: BLE001
                status.add(f"label em {email['gmail_id']}: {exc}")
    return {
        "lidos": len(ids),
        "novos": sum(por_categoria.values()),
        "ja_vistos": len(ids) - len(novos),
        "por_categoria": dict(por_categoria),
        "ligados": ligados,
        "pendentes": len(candidaturas.emails_pendentes(conn)),
    }


def preencher_corpos(conn: sqlite3.Connection, caixa, status) -> dict:
    """Busca no Gmail o corpo dos e-mails gravados antes da migração 006. Não classifica: custo zero."""
    faltando = conn.execute("SELECT id, gmail_id FROM emails WHERE corpo IS NULL ORDER BY recebido_em, id").fetchall()
    preenchidos = 0
    for linha in faltando:
        try:
            corpo = caixa.ler(linha["gmail_id"])["corpo"]
        except Exception as exc:  # noqa: BLE001 — um e-mail apagado no Gmail não para os outros
            status.tool_errors += 1
            status.add(f"e-mail {linha['gmail_id']}: {exc}")
            continue
        with conn:
            conn.execute("UPDATE emails SET corpo = ? WHERE id = ?", (corpo, linha["id"]))
        preenchidos += 1
    return {"faltando": len(faltando), "preenchidos": preenchidos}


def avaliar(conn: sqlite3.Connection) -> dict:
    """Acurácia da triagem contra as correções manuais (`hermes email corrigir`)."""
    linhas = [dict(r) for r in conn.execute(
        "SELECT id, assunto, final, rotulo_manual, latencia_ms FROM emails"
        " WHERE rotulo_manual IS NOT NULL ORDER BY recebido_em")]
    decididas = [l for l in linhas if l["final"] != "revisar"]
    erros = [l for l in decididas if l["final"] != l["rotulo_manual"]]
    lat = sorted(l["latencia_ms"] for l in linhas if l["latencia_ms"] is not None)
    return {
        "rotuladas": len(linhas),
        "revisao": len(linhas) - len(decididas),
        "decididas": len(decididas),
        "certas": len(decididas) - len(erros),
        "p50": lat[len(lat) // 2] if lat else None,
        "p95": lat[min(len(lat) - 1, -(-len(lat) * 95 // 100) - 1)] if lat else None,
        "erros": erros,
    }


def resumir_avisos(avisos: list[str], maximo: int = 5, largura: int = 150) -> list[str]:
    """Avisos do sync agrupados pelo tipo do erro: 65 × "Quota exceeded" vira uma linha."""
    grupos: dict[str, list[str]] = {}
    for aviso in avisos:
        chave = re.sub(r"^(e-mail|label em) \S+: ", "", aviso)
        chave = re.sub(r"\s+", " ", chave)[:80]
        grupos.setdefault(chave, []).append(aviso)
    linhas = []
    for chave, itens in sorted(grupos.items(), key=lambda g: -len(g[1]))[:maximo]:
        exemplo = re.sub(r"\s+", " ", itens[0])
        prefixo = f"{len(itens)}× " if len(itens) > 1 else ""
        linhas.append((prefixo + exemplo)[:largura])
    if len(grupos) > maximo:
        linhas.append(f"... e mais {len(grupos) - maximo} tipo(s) de aviso")
    return linhas
