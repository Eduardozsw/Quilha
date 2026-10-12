"""Vagas anunciadas por e-mail: o "cardápio" dos alertas de vaga, separado das candidaturas.

Alerta de vaga não é candidatura: ninguém se inscreveu em nada. O Jev classifica esses e-mails como
`outro`, e aqui eles viram uma lista de vagas, uma por item, sem repetir a mesma vaga de alertas
diferentes. Só leitura e sem modelo: o texto já está no banco desde a migração 006.

Por enquanto só o LinkedIn: o alerta dele traz título, empresa, local e o link de cada vaga em texto.
O do Glassdoor perde os links quando o HTML vira texto, e vaga sem link não serve de cardápio.
"""

from __future__ import annotations

import re
import sqlite3

from hermes.domain import candidaturas

REMETENTE_LINKEDIN = "jobalerts-noreply@linkedin.com"

_VAGA = re.compile(r"Visualizar vaga:\s*(\S+)")
_ID_LINKEDIN = re.compile(r"/jobs/view/(\d+)")
_ALERTA = re.compile(r"alerta de vaga para (.+?) em: (.+?) foi criado")
# linhas do cartão que não são título, empresa nem local
_RUIDO = re.compile(
    r"^(Esta empresa está contratando|Candidate-se|Candidatura simplificada|\d+ conex|\d+ ex-|"
    r"Seu alerta|Novas vagas|Gerenci|Ver todas|Destaque seu perfil|-{3,})", re.I)


def extrair_linkedin(corpo: str) -> list[dict]:
    """Cada `Visualizar vaga: <link>` fecha um cartão; o primeiro parágrafo limpo antes dele é a vaga."""
    vagas, inicio = [], 0
    for m in _VAGA.finditer(corpo):
        trecho, inicio = corpo[inicio:m.start()], m.end()
        vaga_id = _ID_LINKEDIN.search(m.group(1))
        if not vaga_id:
            continue
        for paragrafo in re.split(r"\n\s*\n", trecho):
            linhas = [l.strip() for l in paragrafo.splitlines() if l.strip()]
            linhas = [l for l in linhas if "http" not in l and not _RUIDO.match(l)]
            if len(linhas) >= 2:
                vagas.append({
                    "id": f"linkedin:{vaga_id.group(1)}",
                    "titulo": linhas[0],
                    "empresa": linhas[1],
                    "local": linhas[2] if len(linhas) > 2 else None,
                    "url": f"https://www.linkedin.com/jobs/view/{vaga_id.group(1)}/",
                })
                break
    return vagas


def listar(conn: sqlite3.Connection) -> list[dict]:
    """Vagas dos alertas, da anunciada mais recente para a mais antiga, uma vez cada.

    `vezes` conta em quantos alertas a vaga apareceu; `ja_candidatou` diz se há candidatura (não
    cancelada) na mesma empresa, para o cardápio não oferecer de novo o que já foi enviado.
    """
    empresas = {r[0] for r in conn.execute(
        "SELECT empresa_norm FROM candidaturas WHERE status != 'cancelada' AND empresa_norm IS NOT NULL")}
    vistas: dict[str, dict] = {}
    for e in conn.execute(
        "SELECT recebido_em, assunto, corpo FROM emails WHERE de LIKE ? AND corpo IS NOT NULL"
        " ORDER BY recebido_em DESC, id DESC", (f"%{REMETENTE_LINKEDIN}%",)):
        alerta = _ALERTA.search(e["corpo"])
        for v in extrair_linkedin(e["corpo"]):
            if v["id"] in vistas:
                vistas[v["id"]]["vezes"] += 1
                continue
            vistas[v["id"]] = {
                **v,
                "fonte": "LinkedIn",
                "anunciada_em": e["recebido_em"],
                "alerta": f"{alerta.group(1)} · {alerta.group(2)}" if alerta else None,
                "vezes": 1,
                "ja_candidatou": candidaturas.normalizar_empresa(v["empresa"]) in empresas,
            }
    return list(vistas.values())
