"""Estudos: o que você declarou, o resumo da semana e o plano da semana seguinte.

Fonte confiável do estudo é você declarando (`log_study`). O plano semanal é a única parte que usa
o modelo, e mesmo nele o código decide o que entra: o modelo propõe itens a partir das lacunas das
vagas; o código recusa competência inexistente, corta o que passa do tempo disponível e liga cada
item à lacuna de vaga que o originou.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta

MAX_MINUTOS_SESSAO = 12 * 60  # mais que isso num registro é quase certamente erro de digitação
SEMANA_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


class EstudoRecusado(Exception):
    """Registro ou plano inválido. A mensagem diz o que corrigir."""


def semana_iso(dia: date | None = None) -> str:
    ano, semana, _ = (dia or date.today()).isocalendar()
    return f"{ano}-W{semana:02d}"


def proxima_semana(dia: date | None = None) -> str:
    return semana_iso((dia or date.today()) + timedelta(days=7))


def _dias_da_semana(semana: str) -> tuple[str, str]:
    if not SEMANA_RE.match(semana):
        raise EstudoRecusado(f"semana `{semana}` fora do formato ISO (ex: 2026-W39)")
    ano, num = semana.split("-W")
    inicio = date.fromisocalendar(int(ano), int(num), 1)
    return inicio.isoformat(), (inicio + timedelta(days=6)).isoformat()


def _competencia_id(conn: sqlite3.Connection, slug: str | None) -> int | None:
    if not slug:
        return None
    linha = conn.execute("SELECT id FROM competencies WHERE slug = ?", (slug,)).fetchone()
    if not linha:
        raise EstudoRecusado(f"competência `{slug}` não existe (veja `hermes comp list`)")
    return linha["id"]


# ------------------------------------------------------------------- sessões


def log_study(
    conn: sqlite3.Connection,
    minutos: int,
    o_que_fez: str,
    slug: str | None = None,
    data: str | None = None,
    dificuldade: int | None = None,
    travou_em: str | None = None,
) -> dict:
    """Registra uma sessão de estudo **declarada**. Custo zero."""
    from hermes.db import store

    if not isinstance(minutos, int) or minutos <= 0:
        raise EstudoRecusado("`minutos` precisa ser um inteiro maior que zero")
    if minutos > MAX_MINUTOS_SESSAO:
        raise EstudoRecusado(
            f"{minutos} minutos numa sessão só? Registre por sessão (máximo {MAX_MINUTOS_SESSAO})"
        )
    if not (o_que_fez or "").strip():
        raise EstudoRecusado("diga o que você fez — é isso que o plano da semana usa")
    if dificuldade is not None and not 1 <= dificuldade <= 5:
        raise EstudoRecusado("`dificuldade` vai de 1 a 5")
    dia = data or date.today().isoformat()
    try:
        quando = date.fromisoformat(dia)
    except ValueError:
        raise EstudoRecusado(f"data `{dia}` fora do formato AAAA-MM-DD") from None
    if quando > date.today():
        raise EstudoRecusado("não dá para registrar estudo no futuro")

    competency_id = _competencia_id(conn, slug)
    with conn:
        cursor = conn.execute(
            "INSERT INTO study_sessions (data, competency_id, minutos, o_que_fez, dificuldade,"
            " travou_em, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dia, competency_id, minutos, o_que_fez.strip(), dificuldade,
             (travou_em or "").strip() or None, store.utcnow()),
        )
    return {"id": cursor.lastrowid, "data": dia, "minutos": minutos, "competencia": slug,
            "o_que_fez": o_que_fez.strip()}


def resumo_semana(conn: sqlite3.Connection, semana: str | None = None) -> dict:
    """Minutos declarados na semana, por competência, contra o plano da mesma semana."""
    semana = semana or semana_iso()
    inicio, fim = _dias_da_semana(semana)
    sessoes = [
        dict(r)
        for r in conn.execute(
            "SELECT s.id, s.data, s.minutos, s.o_que_fez, s.dificuldade, s.travou_em,"
            " c.slug AS competencia"
            " FROM study_sessions s LEFT JOIN competencies c ON c.id = s.competency_id"
            " WHERE s.data BETWEEN ? AND ? ORDER BY s.data, s.id",
            (inicio, fim),
        )
    ]
    por_comp: dict[str, int] = {}
    for s in sessoes:
        chave = s["competencia"] or "(sem competência)"
        por_comp[chave] = por_comp.get(chave, 0) + s["minutos"]

    plano = conn.execute("SELECT id, objetivo FROM study_plan WHERE semana = ?", (semana,)).fetchone()
    itens = []
    if plano:
        for i in conn.execute(
            "SELECT i.id, i.descricao, i.recurso, i.minutos_alvo, i.status, c.slug AS competencia"
            " FROM plan_items i LEFT JOIN competencies c ON c.id = i.competency_id"
            " WHERE i.plan_id = ? ORDER BY i.id",
            (plano["id"],),
        ):
            item = dict(i)
            # minutos da semana na competência do item; itens da mesma competência dividem o total
            item["minutos_feitos"] = por_comp.get(item["competencia"] or "", 0)
            itens.append(item)

    sinais = conn.execute(
        "SELECT COUNT(*) FROM activity_signals"
        " WHERE estado IN ('novo', 'perguntado') AND data BETWEEN ? AND ?",
        (inicio, fim),
    ).fetchone()[0]
    return {
        "semana": semana,
        "inicio": inicio,
        "fim": fim,
        "sessoes": sessoes,
        "minutos": sum(s["minutos"] for s in sessoes),
        "por_competencia": por_comp,
        "plano": {"objetivo": plano["objetivo"], "itens": itens} if plano else None,
        "minutos_alvo": sum(i["minutos_alvo"] for i in itens),
        "sinais_pendentes": sinais,
    }


# --------------------------------------------------------------------- plano

LACUNAS_SQL = """
SELECT c.slug, c.nome, c.peso, v.nivel, r.job_id, j.titulo, j.empresa, r.tipo
FROM job_requirements r
JOIN jobs j                 ON j.id = r.job_id
JOIN competencies c         ON c.id = r.competency_id
JOIN v_competency_current v ON v.id = c.id
WHERE j.status IN ('novo', 'analisado', 'aplicado') AND COALESCE(v.nivel, 0) < 2
"""


def lacunas_de_vagas(conn: sqlite3.Connection) -> list[dict]:
    """Competências que as vagas abertas pedem e o vault ainda não sustenta (nível < 2).

    Ordem: quantas vagas pedem como obrigatório, depois quantas pedem ao todo, depois o peso.
    Requisito sem competência mapeada fica de fora: não há o que estudar sem saber o quê.
    """
    agrupado: dict[str, dict] = {}
    for r in conn.execute(LACUNAS_SQL):
        g = agrupado.setdefault(
            r["slug"],
            {"slug": r["slug"], "nome": r["nome"], "peso": r["peso"], "nivel": r["nivel"],
             "vagas": {}, "obrigatorio_em": set()},
        )
        g["vagas"][r["job_id"]] = f"{r['titulo']} — {r['empresa']}"
        if r["tipo"] == "obrigatorio":
            g["obrigatorio_em"].add(r["job_id"])
    saida = []
    for g in agrupado.values():
        saida.append({**g, "n_vagas": len(g["vagas"]), "n_obrigatorio": len(g["obrigatorio_em"]),
                      "obrigatorio_em": sorted(g["obrigatorio_em"])})
    saida.sort(key=lambda g: (-g["n_obrigatorio"], -g["n_vagas"], -g["peso"], g["slug"]))
    return saida


SYSTEM_PLANO = (
    "Você monta planos de estudo semanais curtos e realistas, no nível que as competências da pessoa mostram. "
    "Responde só com JSON. Cada item é uma tarefa concreta que termina em algo verificável."
)

INSTRUCOES_PLANO = """
Monte o plano da semana e responda SÓ com este JSON:
{
  "objetivo": "uma frase",
  "itens": [
    {"competencia": "<slug da lista>", "descricao": "tarefa concreta com entregável",
     "recurso": "link, livro ou documentação (ou null)", "minutos": 90}
  ]
}

Regras:
- Use só slugs da lista de lacunas. Priorize a ordem da lista.
- A soma de `minutos` não passa de {minutos} minutos. Prefira 2 a 5 itens.
- Tarefa que produz evidência (código num repositório, nota no vault) vale mais que leitura solta.
- Não repita o que a semana anterior já cobriu, a não ser que tenha travado.
"""


def _entrada_plano(lacunas: list[dict], anterior: dict, minutos: int) -> str:
    linhas = ["Lacunas (competência pedida por vaga aberta e ainda sem nível 2):"]
    for g in lacunas:
        nivel = "—" if g["nivel"] is None else g["nivel"]
        linhas.append(
            f"- {g['slug']} ({g['nome']}): nível {nivel}, pedida em {g['n_vagas']} vaga(s),"
            f" obrigatória em {g['n_obrigatorio']}"
        )
    linhas += ["", f"Semana anterior ({anterior['semana']}): {anterior['minutos']} minutos declarados."]
    for s in anterior["sessoes"]:
        travou = f" — travou em: {s['travou_em']}" if s["travou_em"] else ""
        linhas.append(f"- {s['competencia'] or 'sem competência'}: {s['o_que_fez']}{travou}")
    return "\n".join(linhas) + "\n" + INSTRUCOES_PLANO.replace("{minutos}", str(minutos))


PROMPT_ROTEIRO = """You help a job seeker prepare for a technical interview. Answer with one JSON object only:
{"roteiro": [{"tema": "...", "o_que_revisar": "...", "pergunta_provavel": "..."}]}
Write in Brazilian Portuguese. 3 to 5 items, one per gap, most important first. Ground every item in the
gaps given; do not invent requirements the job did not list."""


def roteiro_entrevista(conn: sqlite3.Connection, candidatura_id: int, *, status=None,
                       model: str | None = None) -> dict:
    """Roteiro de preparação para a entrevista a partir das lacunas da vaga ligada. Uma chamada ao modelo."""
    from hermes import llm
    from hermes.domain import candidaturas, vaga
    from hermes.json_parse import extract_json_object
    from hermes.run_status import RunStatus

    status = status if status is not None else RunStatus()
    c = candidaturas.detalhe(conn, candidatura_id)["candidatura"]
    if not c["job_id"]:
        raise EstudoRecusado("ligue a candidatura a uma vaga gravada para montar o roteiro")
    faltas = vaga.lacunas(vaga.cobertura(conn, c["job_id"]))
    if not faltas:
        raise EstudoRecusado("a vaga não tem lacunas: o seu vault já sustenta todos os requisitos")
    nomes = [f["texto"] for f in faltas]
    entrada = json.dumps({
        "vaga": c["titulo"], "empresa": c["empresa"],
        "lacunas": [{"requisito": f["texto"], "tipo": f["tipo"], "motivo": f["motivo"]} for f in faltas],
    }, ensure_ascii=False)
    bruto = llm.complete(PROMPT_ROTEIRO, entrada, status=status, model=model, temperature=0.3,
                         max_tokens=900, json_mode=True)
    r = extract_json_object(bruto, ("roteiro",))
    itens = [i for i in r.get("roteiro") or [] if isinstance(i, dict) and str(i.get("tema") or "").strip()][:5]
    if not itens:  # o roteiro custou LLM: uma resposta vazia nunca apaga o que já estava salvo
        tinha = conn.execute("SELECT roteiro IS NOT NULL FROM candidaturas WHERE id = ?", (candidatura_id,)).fetchone()[0]
        raise EstudoRecusado("o modelo não devolveu nenhum tema válido; "
                             + ("o roteiro anterior foi mantido. " if tinha else "") + "Tente gerar de novo")
    salvo = candidaturas.salvar_roteiro(conn, candidatura_id, itens)
    return {"candidatura_id": candidatura_id, "lacunas": nomes, "roteiro": itens, "gerado_em": salvo["gerado_em"]}


def plan_week(
    conn: sqlite3.Connection,
    minutos_disponiveis: int,
    semana: str | None = None,
    substituir: bool = False,
    *,
    status=None,
    model: str | None = None,
) -> dict:
    """Plano da semana ligado às lacunas das vagas. Uma chamada ao modelo."""
    from hermes import llm
    from hermes.db import store
    from hermes.json_parse import extract_json_object
    from hermes.run_status import RunStatus

    status = status if status is not None else RunStatus()
    semana = semana or proxima_semana()
    inicio, _ = _dias_da_semana(semana)
    if not isinstance(minutos_disponiveis, int) or not 30 <= minutos_disponiveis <= 40 * 60:
        raise EstudoRecusado("`minutos_disponiveis` vai de 30 a 2400 na semana")
    existente = conn.execute("SELECT id FROM study_plan WHERE semana = ?", (semana,)).fetchone()
    if existente and not substituir:
        raise EstudoRecusado(f"já existe plano para {semana}; peça para substituir")

    lacunas = lacunas_de_vagas(conn)
    if not lacunas:
        raise EstudoRecusado(
            "nenhuma lacuna de vaga para planejar: grave uma vaga (`hermes job add`) com "
            "requisitos mapeados a competências abaixo do nível 2"
        )
    anterior = resumo_semana(conn, semana_iso(date.fromisoformat(inicio) - timedelta(days=7)))
    ids = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM competencies")}

    # "nunca avaliada" com fato no vault que parece sustentar não é lacuna de estudo, é lacuna de
    # registro: o item é ligar a evidência e declarar o nível, não reaprender o que já foi feito
    a_declarar, a_estudar = _separar_lacunas(conn, lacunas)
    itens = [_item_declarar(g, ids) for g in a_declarar]
    total = sum(i["minutos_alvo"] for i in itens)
    if total > minutos_disponiveis:
        raise EstudoRecusado(
            f"só registrar as evidências pendentes leva {total} minutos; aumente o tempo disponível"
        )

    restante = minutos_disponiveis - total
    proposta: dict = {}
    if a_estudar and restante >= 30:
        bruto = llm.complete(
            SYSTEM_PLANO,
            _entrada_plano(a_estudar, anterior, restante),
            status=status,
            model=model,
            temperature=0.3,
            json_mode=True,
        )
        proposta = extract_json_object(bruto, ("itens",))
    elif a_estudar:
        status.add(f"sobraram {restante} minutos depois dos registros; nada de estudo nesta semana")

    por_slug = {g["slug"]: g for g in a_estudar}
    for item in proposta.get("itens") or []:
        if not isinstance(item, dict):
            continue
        slug = item.get("competencia")
        descricao = str(item.get("descricao") or "").strip()
        try:
            minutos = int(item.get("minutos"))
        except (TypeError, ValueError):
            minutos = 0
        if slug not in por_slug:
            status.add(f"item ignorado: `{slug}` não é uma lacuna de estudo das vagas")
            continue
        if not descricao or minutos <= 0:
            status.add(f"item de `{slug}` ignorado: sem descrição ou sem minutos")
            continue
        if total + minutos > minutos_disponiveis:
            status.add(f"item de `{slug}` cortado: passaria de {minutos_disponiveis} minutos")
            continue
        total += minutos
        recurso = item.get("recurso")
        itens.append({
            "competencia": slug,
            "competency_id": ids[slug],
            # a lacuna que originou o item: a vaga em que a competência é obrigatória, se houver
            "job_id": (por_slug[slug]["obrigatorio_em"] or list(por_slug[slug]["vagas"]))[0],
            "descricao": descricao,
            "recurso": str(recurso).strip() if recurso and str(recurso).lower() != "null" else None,
            "minutos_alvo": minutos,
        })
    if not itens:
        raise EstudoRecusado("o modelo não propôs nenhum item válido; nada foi gravado")

    objetivo = str(proposta.get("objetivo") or "").strip() or (
        "Registrar as evidências que já existem no vault" if a_declarar else
        "Fechar lacunas das vagas abertas"
    )
    with conn:
        if existente:
            conn.execute("DELETE FROM study_plan WHERE id = ?", (existente["id"],))
        plan_id = conn.execute(
            "INSERT INTO study_plan (semana, objetivo, criado_em) VALUES (?, ?, ?)",
            (semana, objetivo, store.utcnow()),
        ).lastrowid
        conn.executemany(
            "INSERT INTO plan_items (plan_id, competency_id, job_id, descricao, recurso,"
            " minutos_alvo) VALUES (?, ?, ?, ?, ?, ?)",
            [(plan_id, i["competency_id"], i["job_id"], i["descricao"], i["recurso"],
              i["minutos_alvo"]) for i in itens],
        )
    for i in itens:
        del i["competency_id"]
    return {"semana": semana, "objetivo": objetivo, "itens": itens, "minutos_alvo": total,
            "minutos_disponiveis": minutos_disponiveis, "usou_modelo": bool(proposta)}


MINUTOS_DECLARAR = 15


def _separar_lacunas(conn: sqlite3.Connection, lacunas: list[dict]) -> tuple[list[dict], list[dict]]:
    from hermes.domain import competencias

    a_declarar, a_estudar = [], []
    for g in lacunas:
        ligadas, candidatos = [], []
        if g["nivel"] is None:
            ligadas = [e for e in competencias.evidencias(conn, g["slug"]) if e["texto"]]
            candidatos = [] if ligadas else competencias.fatos_candidatos(conn, g["slug"])
        if ligadas or candidatos:
            a_declarar.append({**g, "ligadas": ligadas, "candidatos": candidatos})
        else:
            a_estudar.append(g)
    return a_declarar, a_estudar


def _item_declarar(g: dict, ids: dict) -> dict:
    slug = g["slug"]
    if g["ligadas"]:
        refs = ", ".join(f"^{e['block_id']}" for e in g["ligadas"])
        descricao = (
            f"Declarar o nível de `{slug}`: a evidência já está ligada ({refs}). "
            f"`hermes comp assess {slug} <nível> -j \"...\"`"
        )
    else:
        refs = ", ".join(f"^{c['block_id']}" for c in g["candidatos"])
        descricao = (
            f"Conferir {refs} e, se sustentarem, ligar a evidência "
            f"(`hermes comp evidence {slug} <ref>`) e declarar o nível (`hermes comp assess`)"
        )
    return {
        "competencia": slug,
        "competency_id": ids[slug],
        "job_id": (g["obrigatorio_em"] or list(g["vagas"]))[0],
        "descricao": descricao,
        "recurso": None,
        "minutos_alvo": MINUTOS_DECLARAR,
    }


def markdown_do_plano(plano: dict, resumo_anterior: dict | None = None) -> str:
    """Texto que vai para `Diario/<semana>.md`. Sem LLM: é o plano gravado, formatado."""
    linhas = [f"## Plano da semana {plano['semana']}", "", f"**Objetivo:** {plano['objetivo']}", ""]
    for i in plano["itens"]:
        recurso = f" — {i['recurso']}" if i.get("recurso") else ""
        linhas.append(f"- [ ] ({i['minutos_alvo']} min, `{i['competencia']}`) {i['descricao']}{recurso}")
    linhas += ["", f"Total: {plano['minutos_alvo']} de {plano['minutos_disponiveis']} minutos disponíveis."]
    if resumo_anterior is not None:
        alvo = resumo_anterior["minutos_alvo"]
        meta = f" de {alvo} planejados" if alvo else " (sem plano)"
        linhas += [
            "",
            f"### Semana anterior ({resumo_anterior['semana']})",
            "",
            f"{resumo_anterior['minutos']} minutos declarados{meta}, "
            f"{len(resumo_anterior['sessoes'])} sessão(ões).",
        ]
        for comp, minutos in sorted(resumo_anterior["por_competencia"].items()):
            linhas.append(f"- `{comp}`: {minutos} min")
    return "\n".join(linhas) + "\n"
