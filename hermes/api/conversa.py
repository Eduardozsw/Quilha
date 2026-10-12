"""O que a Conversa da V3 mostra além do texto: rótulos de ferramenta, confirmações legíveis e cartões.

Só leitura e sem LLM. O cartão é decidido pela ferramenta que rodou no turno, nunca pelo texto da
resposta: vaga (de `match_job` ou `parse_job`) e candidatura (de `application_detail`), um por entidade.
"""

from __future__ import annotations

import sqlite3
from urllib.parse import urlparse

from hermes.domain import vaga

# ferramenta → (verbo rodando, verbo feito, verbo no infinitivo, objeto)
_ROTULOS: dict[str, tuple[str, str, str, str]] = {
    "vault_search_facts": ("Buscando", "Buscou", "buscar", "no vault"),
    "list_competencies": ("Consultando", "Consultou", "consultar", "as competências"),
    "link_evidence": ("Ligando", "Ligou", "ligar", "a evidência"),
    "assess_competency": ("Gravando", "Gravou", "gravar", "o nível"),
    "parse_job": ("Lendo", "Leu", "ler", "a vaga"),
    "match_job": ("Avaliando", "Avaliou", "avaliar", "a vaga"),
    "log_study": ("Registrando", "Registrou", "registrar", "o estudo"),
    "git_activity": ("Lendo", "Leu", "ler", "os commits"),
    "confirm_study_signals": ("Registrando", "Registrou", "registrar", "o estudo dos commits"),
    "study_week": ("Consultando", "Consultou", "consultar", "a semana de estudo"),
    "plan_week": ("Montando", "Montou", "montar", "o plano da semana"),
    "list_jobs": ("Consultando", "Consultou", "consultar", "as vagas"),
    "list_applications": ("Consultando", "Consultou", "consultar", "as candidaturas"),
    "application_detail": ("Abrindo", "Abriu", "abrir", "a candidatura"),
    "profile_scores": ("Comparando", "Comparou", "comparar", "os currículos"),
}


def rotulo_ferramenta(nome: str) -> dict:
    """Os três estados da linha de ferramenta. `verbo` e `objeto` deixam a tela juntar chamadas seguidas
    ("Consultou as vagas e as candidaturas"). Ferramenta de servidor MCP usa o nome cru."""
    if nome in _ROTULOS:
        rodando, feito, infinitivo, objeto = _ROTULOS[nome]
    else:
        rodando, feito, infinitivo, objeto = "Usando", "Usou", "usar", f"`{nome}`"
    return {"rodando": f"{rodando} {objeto}…", "feito": f"{feito} {objeto}",
            "falhou": f"Não consegui {infinitivo} {objeto}", "verbo": feito, "objeto": objeto}


# ------------------------------------------------------------------ confirmação


def _competencia(conn: sqlite3.Connection, slug: str | None) -> str | None:
    if not slug:
        return None
    linha = conn.execute("SELECT nome FROM competencies WHERE slug = ?", (slug,)).fetchone()
    return linha["nome"] if linha else slug


def _vaga(conn: sqlite3.Connection, job_id) -> str:
    linha = conn.execute("SELECT titulo, empresa FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return f"{linha['titulo']} — {linha['empresa']}" if linha else f"vaga {job_id}"


def _duracao(minutos) -> tuple[str, str]:
    """("1 h 30 min", gênero e número para concordar "gravada")."""
    try:
        m = int(minutos)
    except (TypeError, ValueError):
        return f"{minutos} min", "mp"
    if m < 60:
        return f"{m} min", "mp"
    h, resto = divmod(m, 60)
    texto = f"{h} h" + (f" {resto} min" if resto else "")
    return texto, "fs" if h == 1 else "fp"


_GRAVADO = {"ms": "gravado", "fs": "gravada", "mp": "gravados", "fp": "gravadas"}


def _estudo(conn, args: dict, extra: list[dict] | None = None) -> dict:
    tempo, concordancia = _duracao(args.get("minutos"))
    comp = _competencia(conn, args.get("slug"))
    campos = [{"rotulo": "Tempo", "valor": tempo}, {"rotulo": "O que fez", "valor": str(args.get("o_que_fez") or "")}]
    if comp:
        campos.append({"rotulo": "Competência", "valor": comp})
    if args.get("data"):
        campos.append({"rotulo": "Data", "valor": str(args["data"])})
    if args.get("dificuldade"):
        campos.append({"rotulo": "Dificuldade", "valor": f"{args['dificuldade']} de 5"})
    if args.get("travou_em"):
        campos.append({"rotulo": "Travou em", "valor": str(args["travou_em"])})
    campos += extra or []
    # "30 min em Python" quando a competência veio; "1 h de graphql" lê melhor com slug cru
    if comp and comp != args.get("slug"):
        resumo = f"{tempo} em {comp}"
    elif comp:
        resumo = f"{tempo} de {comp}"
    else:
        resumo = f"{tempo} de estudo"
    return {"titulo": "Gravar este estudo?", "objeto": "Estudo", "genero": "ms",
            "campos": campos, "resumo": resumo, "concordancia": concordancia}


def _montar(conn, nome: str, args: dict) -> dict:
    if nome == "log_study":
        return _estudo(conn, args)
    if nome == "confirm_study_signals":
        n = len(args.get("sinais") or [])
        return _estudo(conn, args, [{"rotulo": "Commits", "valor": str(n)}])
    if nome == "assess_competency":
        comp = _competencia(conn, args.get("slug")) or "?"
        return {"titulo": "Gravar este nível?", "objeto": "Nível", "genero": "ms",
                "campos": [{"rotulo": "Competência", "valor": comp},
                           {"rotulo": "Nível", "valor": f"{args.get('nivel')} de 4"},
                           {"rotulo": "Justificativa", "valor": str(args.get("justificativa") or "")}],
                "resumo": f"{comp} nível {args.get('nivel')}", "concordancia": "ms"}
    if nome == "link_evidence":
        comp = _competencia(conn, args.get("slug")) or "?"
        forca = {1: "fraca", 2: "média", 3: "forte"}.get(args.get("forca"))
        campos = [{"rotulo": "Competência", "valor": comp}, {"rotulo": "Fato", "valor": str(args.get("referencia"))}]
        if forca:
            campos.append({"rotulo": "Força", "valor": forca})
        if args.get("observacao"):
            campos.append({"rotulo": "Observação", "valor": str(args["observacao"])})
        return {"titulo": "Ligar esta evidência?", "objeto": "Evidência", "genero": "fs",
                "campos": campos, "resumo": f"evidência de {comp}", "concordancia": "fs"}
    if nome == "parse_job":
        if args.get("url"):
            origem = str(args["url"])
            resumo = f"vaga de {urlparse(origem).netloc or origem}"
        else:
            texto = str(args.get("texto") or "")
            origem = f"texto colado ({len(texto.strip()):,} caracteres)".replace(",", ".")
            resumo = "vaga colada"
        return {"titulo": "Gravar esta vaga?", "objeto": "Vaga", "genero": "fs",
                "campos": [{"rotulo": "Origem", "valor": origem}], "resumo": resumo, "concordancia": "fs"}
    if nome == "match_job":
        alvo = _vaga(conn, args.get("job_id"))
        return {"titulo": "Avaliar esta vaga?", "objeto": "Avaliação", "genero": "fs",
                "campos": [{"rotulo": "Vaga", "valor": alvo}], "resumo": f"avaliação de {alvo}",
                "concordancia": "fs"}
    if nome == "git_activity":
        dias = int(args.get("dias") or 1)
        periodo = "último dia" if dias == 1 else f"últimos {dias} dias"
        repos = args.get("repos") or []
        return {"titulo": "Ler os commits?", "objeto": "Leitura", "genero": "fs",
                "campos": [{"rotulo": "Período", "valor": periodo},
                           {"rotulo": "Repositórios", "valor": ", ".join(repos) if repos else "todos"}],
                "resumo": f"commits do {periodo}" if dias == 1 else f"commits dos {periodo}",
                "concordancia": "mp"}
    if nome == "plan_week":
        tempo, _ = _duracao(args.get("minutos_disponiveis"))
        semana = args.get("semana")
        campos = [{"rotulo": "Tempo na semana", "valor": tempo},
                  {"rotulo": "Semana", "valor": str(semana) if semana else "a próxima"}]
        if args.get("substituir"):
            campos.append({"rotulo": "Substitui o plano atual", "valor": "sim"})
        return {"titulo": "Gravar este plano?", "objeto": "Plano", "genero": "ms", "campos": campos,
                "resumo": f"plano da semana {semana}" if semana else "plano da próxima semana",
                "concordancia": "ms"}
    campos = [{"rotulo": k, "valor": str(v)} for k, v in args.items()]
    return {"titulo": f"Gravar com `{nome}`?", "objeto": "Gravação", "genero": "fs",
            "campos": campos or [{"rotulo": "Ferramenta", "valor": nome}], "resumo": f"`{nome}`",
            "concordancia": "fs"}


def confirmacao(conn: sqlite3.Connection, nome: str, argumentos: dict) -> dict:
    """O cartão "Gravar este estudo?": título, pares rótulo/valor (só leitura) e as linhas em que ele
    encolhe depois de respondido ("✓ Estudo gravado · 30 min em Python", "Não gravado · SQL nível 3")."""
    c = _montar(conn, nome, argumentos or {})
    objeto, resumo = c["objeto"], c["resumo"]
    linhas = {
        "gravado": f"{objeto} {_GRAVADO[c['genero']]} · {resumo}",
        "recusado": f"Não gravado · {resumo}",
        "falhou": f"Não gravado · {resumo}",
        "expirou": f"Expirou · {resumo} não {_GRAVADO[c['concordancia']]}",
    }
    return {"titulo": c["titulo"], "campos": c["campos"], "resumo": resumo, "objeto": objeto, "linhas": linhas}


# ------------------------------------------------------------------ cartões

MAX_LACUNAS = 4


def _cartao_vaga(conn: sqlite3.Connection, job_id: int) -> dict | None:
    linha = conn.execute("SELECT id, titulo, empresa, senioridade, local FROM jobs WHERE id = ?",
                         (job_id,)).fetchone()
    if linha is None:
        return None
    av = vaga.avaliacao(conn, job_id)
    return {"tipo": "vaga", "job_id": linha["id"], "titulo": linha["titulo"], "empresa": linha["empresa"],
            "senioridade": linha["senioridade"], "local": linha["local"], "score": av["score"],
            "cobertos": av["cobertos"], "total": av["total"],
            "lacunas": [r["texto"] for r in av["requisitos"] if not r["coberto"]][:MAX_LACUNAS]}


def _cartao_candidatura(conn: sqlite3.Connection, cand_id: int) -> dict | None:
    linha = conn.execute("SELECT id, titulo, empresa, status FROM candidaturas WHERE id = ?",
                         (cand_id,)).fetchone()
    if linha is None:
        return None
    email = conn.execute("SELECT assunto, recebido_em FROM emails WHERE candidatura_id = ?"
                         " ORDER BY recebido_em DESC, id DESC LIMIT 1", (cand_id,)).fetchone()
    return {"tipo": "candidatura", "id": linha["id"], "titulo": linha["titulo"], "empresa": linha["empresa"],
            "status": linha["status"], "ultimo_email": dict(email) if email else None}


def _entidade(nome: str, resultado: dict) -> tuple[str, int] | None:
    if not resultado.get("ok"):
        return None
    dados = resultado.get("data") or {}
    try:
        if nome in ("match_job", "parse_job"):
            return "vaga", int(dados["job_id"])
        if nome == "application_detail":
            return "candidatura", int(dados["candidatura"]["id"])
    except (KeyError, TypeError, ValueError):
        return None
    return None


def cartoes(conn: sqlite3.Connection, resultados: list[tuple[str, dict]]) -> list[dict]:
    """Um cartão por entidade, na ordem em que apareceu no turno. Lista de vagas não vira cartão."""
    vistos: set[tuple[str, int]] = set()
    saida = []
    for nome, resultado in resultados:
        chave = _entidade(nome, resultado)
        if chave is None or chave in vistos:
            continue
        vistos.add(chave)
        tipo, ident = chave
        cartao = _cartao_vaga(conn, ident) if tipo == "vaga" else _cartao_candidatura(conn, ident)
        if cartao is not None:
            saida.append(cartao)
    return saida
