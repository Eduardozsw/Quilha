"""Painel da tela Início: os números do dia, o que andou desde ontem e a atividade recente.

Só leitura e sem modelo. Tudo sai das mesmas tabelas que a CLI grava; nada aqui é estimado.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from hermes.domain import candidaturas, estudos, vaga

SCORE_BOM = vaga.SCORE_BOM  # "vaga boa": o mesmo corte em toda a V3
ATIVAS = ("enviada", "em_processo", "entrevista")
ABERTAS = ("novo", "analisado")
# vaga que ainda vale olhar: nem descartada, nem aplicada, nem já virou candidatura (alias `j` de `jobs`)
VAGA_ABERTA = "j.status IN (?, ?) AND NOT EXISTS (SELECT 1 FROM candidaturas c WHERE c.job_id = j.id)"


def _iso(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def _inicio_do_dia(agora: datetime) -> datetime:
    """Meia-noite local: "hoje" para quem olha a tela, não para o UTC do banco."""
    local = agora.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _numeros(conn: sqlite3.Connection, hoje: str, semana: dict, pendentes: list[dict]) -> dict:
    vagas = conn.execute(
        "SELECT COUNT(*) AS abertas, COALESCE(SUM(j.coletado_em >= ?), 0) AS novas_hoje"
        f" FROM jobs j WHERE {VAGA_ABERTA}", (hoje, *ABERTAS)).fetchone()
    cands = conn.execute(
        "SELECT COUNT(*) AS ativas, COALESCE(SUM(status IN ('em_processo', 'entrevista')), 0) AS em_processo"
        " FROM candidaturas WHERE status IN (?, ?, ?)", ATIVAS).fetchone()
    return {
        "vagas_abertas": vagas["abertas"],
        "vagas_novas_hoje": vagas["novas_hoje"],
        "candidaturas_ativas": cands["ativas"],
        "candidaturas_em_processo": cands["em_processo"],
        "emails_a_triar": len(pendentes),
        "vagas_com_requisitos": conn.execute("SELECT COUNT(DISTINCT job_id) FROM job_requirements").fetchone()[0],
        "estudo_minutos": semana["minutos"],
        "estudo_minutos_alvo": semana["minutos_alvo"] or None,  # sem plano: sem meta
    }


def _vagas_boas(vagas: list[dict], abertas: set[int], desde: datetime) -> list[dict]:
    """Vagas abertas com score bom pela fórmula, coletadas desde `desde`: a mesma conta no resumo e nas mudanças."""
    return [v for v in vagas if v["id"] in abertas and v["n_requisitos"] and v["score"] >= SCORE_BOM
            and _quando(v["coletado_em"]) >= desde]


def _desde(conn: sqlite3.Connection, desde: str, vagas: list[dict], abertas: set[int]) -> dict:
    triados = conn.execute("SELECT COUNT(*) FROM emails WHERE processado_em >= ?", (desde,)).fetchone()[0]
    boas = len(_vagas_boas(vagas, abertas, _quando(desde)))
    avancos = conn.execute(
        "SELECT COUNT(DISTINCT candidatura_id) FROM emails WHERE recebido_em >= ?"
        " AND candidatura_id IS NOT NULL AND COALESCE(rotulo_manual, final) = 'avanco'",
        (desde,)).fetchone()[0]
    return {"emails_triados": triados, "vagas_boas": boas, "avancos": avancos, "score_bom": SCORE_BOM}


def _em_andamento(conn: sqlite3.Connection, limite: int) -> list[dict]:
    linhas = conn.execute(
        "SELECT c.id, c.empresa, c.titulo, c.perfil, c.status, c.enviada_em, c.entrevista_em, c.job_id,"
        " (SELECT m.score FROM job_matches m WHERE m.job_id = c.job_id"
        "  ORDER BY m.criado_em DESC, m.id DESC LIMIT 1) AS score,"
        " (SELECT MAX(e.recebido_em) FROM emails e WHERE e.candidatura_id = c.id) AS ultimo_email_em"
        " FROM candidaturas c WHERE c.status IN (?, ?, ?)"
        " ORDER BY c.status = 'entrevista' DESC, c.status = 'em_processo' DESC, COALESCE(ultimo_email_em, c.enviada_em) DESC, c.id DESC"
        " LIMIT ?", (*ATIVAS, limite)).fetchall()
    itens = []
    for l in linhas:
        item = dict(l)
        ultimo = conn.execute(
            "SELECT assunto, COALESCE(rotulo_manual, final) AS categoria FROM emails"
            " WHERE candidatura_id = ? ORDER BY recebido_em DESC, id DESC LIMIT 1", (l["id"],)).fetchone()
        item["ultimo_email"] = dict(ultimo) if ultimo else None
        itens.append(item)
    return itens


def _atividade(conn: sqlite3.Connection, limite: int) -> list[dict]:
    """O que aconteceu por último, de várias fontes, na mesma forma: quando, tipo, título, detalhe."""
    eventos: list[dict] = []
    for e in conn.execute(
        "SELECT recebido_em, de, assunto, COALESCE(rotulo_manual, final) AS categoria,"
        " rotulo_manual IS NOT NULL AS manual FROM emails WHERE COALESCE(rotulo_manual, final) != 'outro'"
        " ORDER BY recebido_em DESC LIMIT ?", (limite,)):
        eventos.append({"quando": e["recebido_em"], "tipo": "email", "titulo": e["assunto"],
                        "detalhe": e["de"], "categoria": e["categoria"], "manual": bool(e["manual"])})
    for v in conn.execute(
        "SELECT v.criado_em, v.perfil, v.idioma, v.palavras, v.fatos, j.empresa, j.titulo"
        " FROM cv_versions v LEFT JOIN jobs j ON j.id = v.job_id ORDER BY v.criado_em DESC LIMIT ?",
        (limite,)):
        eventos.append({"quando": v["criado_em"], "tipo": "curriculo",
                        "titulo": f"Currículo gerado para {v['empresa']}" if v["empresa"] else "Currículo base gerado",
                        "detalhe": v["titulo"], "perfil": v["perfil"], "idioma": v["idioma"],
                        "palavras": v["palavras"], "fatos": len(json.loads(v["fatos"] or "[]"))})
    for m in conn.execute(
        "SELECT m.criado_em, m.score, j.empresa, j.titulo FROM job_matches m JOIN jobs j ON j.id = m.job_id"
        " ORDER BY m.criado_em DESC LIMIT ?", (limite,)):
        eventos.append({"quando": m["criado_em"], "tipo": "match", "titulo": f"{m['titulo']} — {m['empresa']}",
                        "detalhe": None, "score": m["score"]})
    for s in conn.execute(
        "SELECT s.criado_em, s.minutos, s.o_que_fez, c.nome AS competencia FROM study_sessions s"
        " LEFT JOIN competencies c ON c.id = s.competency_id ORDER BY s.criado_em DESC LIMIT ?", (limite,)):
        eventos.append({"quando": s["criado_em"], "tipo": "estudo", "titulo": s["o_que_fez"],
                        "detalhe": s["competencia"], "minutos": s["minutos"]})
    eventos.sort(key=lambda e: e["quando"], reverse=True)
    return eventos[:limite]


def _abertas(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute(f"SELECT j.id FROM jobs j WHERE {VAGA_ABERTA}", ABERTAS)}


def _quando(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _quando_entrevista(iso: str) -> datetime:
    """Entrevista sem fuso (gravada antes de a triagem e a folha sempre mandarem o fuso) é hora local, não UTC."""
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.astimezone()


def _pede_acao(conn: sqlite3.Connection, agora: datetime, vagas: list[dict], pendentes: list[dict]) -> list[dict]:
    """Os cartões de "Pede ação", na ordem do PM: entrevista nas próximas 48 h, currículo pronto e não enviado,
    a melhor vaga nova acima do corte, e-mails a triar (agregados). O primeiro é o primário na tela."""
    cartoes: list[dict] = []
    entrevistas = []
    for c in conn.execute("SELECT id, empresa, titulo, entrevista_em FROM candidaturas"
                          " WHERE status = 'entrevista' AND entrevista_em IS NOT NULL"):
        try:
            quando = _quando_entrevista(c["entrevista_em"])
        except ValueError:
            continue
        if agora <= quando <= agora + timedelta(hours=48):
            entrevistas.append((quando, c))
    for _, c in sorted(entrevistas, key=lambda x: x[0]):
        cartoes.append({"tipo": "entrevista", "candidatura_id": c["id"], "empresa": c["empresa"],
                        "titulo": c["titulo"], "entrevista_em": c["entrevista_em"]})
    # currículo pronto e não enviado (PM, 10/10): depois da entrevista em 48 h, antes da vaga nova
    rascunhos = conn.execute("SELECT id, empresa, titulo, enviada_em FROM candidaturas WHERE status = 'a_enviar'"
                             " ORDER BY enviada_em DESC, id DESC").fetchall()
    if rascunhos:
        r = rascunhos[0]
        cartoes.append({"tipo": "a_enviar", "candidatura_id": r["id"], "empresa": r["empresa"], "titulo": r["titulo"],
                        "gerado_em": r["enviada_em"], "outras": len(rascunhos) - 1})
    abertas = _abertas(conn)
    boas = sorted((v for v in vagas if v["id"] in abertas and v["nova"] and v["n_requisitos"] and v["score"] >= SCORE_BOM),
                  key=lambda v: (v["score"], _quando(v["coletado_em"])), reverse=True)
    if boas:
        v = boas[0]
        cartoes.append({"tipo": "vaga", "job_id": v["id"], "empresa": v["empresa"], "titulo": v["titulo"],
                        "score": v["score"], "coletado_em": v["coletado_em"], "outras": len(boas) - 1})
    if pendentes:
        e = pendentes[-1]  # o mais recente
        cartoes.append({"tipo": "emails", "quantos": len(pendentes),
                        "primeiro": {"email_id": e["id"], "assunto": e["assunto"], "de": e["de"],
                                     "empresa": e["empresa_extraida"], "recebido_em": e["recebido_em"]}})
    return cartoes


def _mudancas(conn: sqlite3.Connection, corte: str, vagas: list[dict], limite: int = 5) -> list[dict]:
    """O que mudou desde a última visita, só o que o dado sustenta: nada de "mudou de etapa", que não tem
    histórico. Vagas boas viram um item agregado; PT e EN da mesma geração, um item só."""
    corte_dt = _quando(corte)
    # pré-filtro no SQL com folga de um dia (texto com fusos diferentes não compara exato); o corte exato é aqui
    folga = _iso(corte_dt - timedelta(days=1))
    itens: list[dict] = []
    boas = _vagas_boas(vagas, _abertas(conn), corte_dt)
    if boas:
        itens.append({"tipo": "vagas_boas", "quantas": len(boas), "quando": max(v["coletado_em"] for v in boas)})
    for e in conn.execute(
            "SELECT e.recebido_em, COALESCE(e.rotulo_manual, e.final) AS cat, c.id, c.empresa FROM emails e"
            " JOIN candidaturas c ON c.id = e.candidatura_id WHERE COALESCE(e.rotulo_manual, e.final) IN"
            " ('avanco', 'reprovado') AND e.recebido_em >= ?", (folga,)):
        if _quando(e["recebido_em"]) >= corte_dt:
            itens.append({"tipo": e["cat"], "candidatura_id": e["id"], "empresa": e["empresa"], "quando": e["recebido_em"]})
    vistos: list[tuple] = []
    for v in conn.execute("SELECT v.criado_em, v.job_id, v.perfil, v.fatos, j.empresa FROM cv_versions v"
                          " LEFT JOIN jobs j ON j.id = v.job_id WHERE v.criado_em >= ? ORDER BY v.criado_em", (folga,)):
        quando = _quando(v["criado_em"])
        if quando < corte_dt:
            continue
        chave = (v["job_id"], v["perfil"], v["fatos"])
        if any(c == chave and abs((quando - t).total_seconds()) <= 1800 for c, t in vistos):
            continue  # o outro idioma da mesma geração
        vistos.append((chave, quando))
        itens.append({"tipo": "curriculo", "empresa": v["empresa"], "fatos": len(json.loads(v["fatos"] or "[]")),
                      "quando": v["criado_em"]})
    niveis = []
    for s in conn.execute(
            "SELECT s.criado_em, s.nivel, c.nome, (SELECT p.nivel FROM competency_state p WHERE p.competency_id ="
            " s.competency_id AND (p.criado_em < s.criado_em OR (p.criado_em = s.criado_em AND p.id < s.id))"
            " ORDER BY p.criado_em DESC, p.id DESC LIMIT 1) AS antes"
            " FROM competency_state s JOIN competencies c ON c.id = s.competency_id WHERE s.criado_em >= ?", (folga,)):
        if _quando(s["criado_em"]) >= corte_dt and s["nivel"] > (s["antes"] or 0):
            niveis.append({"tipo": "nivel", "competencia": s["nome"], "nivel": s["nivel"], "quando": s["criado_em"]})
    itens.extend(_agrupar_niveis(niveis))
    itens.sort(key=lambda i: _quando(i["quando"]), reverse=True)
    return itens[:limite]


def _agrupar_niveis(niveis: list[dict], janela_min: int = 15, minimo: int = 3) -> list[dict]:
    """Níveis declarados numa mesma rodada (cada um a menos de `janela_min` do anterior) viram um item só,
    "Você declarou N níveis", a partir de `minimo`; menos que isso, cada um com o nome."""
    saida, rodada = [], []
    for n in sorted(niveis, key=lambda n: _quando(n["quando"])):
        if rodada and (_quando(n["quando"]) - _quando(rodada[-1]["quando"])).total_seconds() > janela_min * 60:
            saida.extend(_fechar_rodada(rodada, minimo))
            rodada = []
        rodada.append(n)
    saida.extend(_fechar_rodada(rodada, minimo))
    return saida


def _fechar_rodada(rodada: list[dict], minimo: int) -> list[dict]:
    if len(rodada) < minimo:
        return rodada
    return [{"tipo": "niveis", "quantos": len(rodada), "quando": rodada[-1]["quando"]}]


def _etapas(conn: sqlite3.Connection, limite: int = 3) -> dict:
    """Candidaturas por etapa, da mais recente para a mais antiga (último e-mail ou envio); "A enviar" primeiro."""
    saida = {}
    for status in ("a_enviar", "entrevista", "em_processo", "enviada"):
        linhas = conn.execute(
            "SELECT c.id, c.empresa, c.titulo, COALESCE((SELECT MAX(e.recebido_em) FROM emails e"
            " WHERE e.candidatura_id = c.id), c.enviada_em) AS quando FROM candidaturas c WHERE c.status = ?",
            (status,)).fetchall()
        # pelo instante, não pelo texto: datas com fusos diferentes não se ordenam como string
        linhas.sort(key=lambda l: (_quando(l["quando"]), l["id"]), reverse=True)
        saida[status] = {"total": len(linhas), "itens": [dict(l) for l in linhas[:limite]]}
    return saida


def ultima_visita(conn: sqlite3.Connection) -> str | None:
    r = conn.execute("SELECT valor FROM estado_app WHERE chave = 'ultima_visita'").fetchone()
    return r[0] if r else None


def marcar_visita(conn: sqlite3.Connection, quando: str) -> None:
    """Grava o horário do resumo que a pessoa viu. Só avança: uma marca mais antiga não apaga uma mais nova."""
    atual = ultima_visita(conn)
    if atual is not None and _quando(atual) >= _quando(quando):
        return
    with conn:
        conn.execute("INSERT INTO estado_app (chave, valor) VALUES ('ultima_visita', ?)"
                     " ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (quando,))


def resumo(conn: sqlite3.Connection, agora: datetime | None = None, limite: int = 6,
           desde: str | None = None) -> dict:
    """`desde` é a última visita; sem ela (primeira abertura), "desde a sua última visita" vale as últimas 24 h."""
    agora = agora or datetime.now(timezone.utc)
    ontem = _iso(agora - timedelta(days=1))
    corte = desde or ontem
    semana = estudos.resumo_semana(conn, estudos.semana_iso(agora.astimezone().date()))
    indice = conn.execute("SELECT COUNT(DISTINCT nota) AS notas, MAX(indexado_em) AS indexado_em FROM facts").fetchone()
    vagas = vaga.listar(conn)
    abertas = _abertas(conn)
    pendentes = candidaturas.emails_pendentes(conn)
    return {
        "agora": _iso(agora),
        "numeros": _numeros(conn, _iso(_inicio_do_dia(agora)), semana, pendentes),
        "desde_ontem": _desde(conn, ontem, vagas, abertas),
        "desde_visita": {"desde": corte, **_desde(conn, corte, vagas, abertas)},
        "pede_acao": _pede_acao(conn, agora, vagas, pendentes),
        "mudancas": _mudancas(conn, corte, vagas),
        "etapas": _etapas(conn),
        "candidaturas": _em_andamento(conn, limite),
        "atividade": _atividade(conn, limite),
        "indice": dict(indice),
    }
