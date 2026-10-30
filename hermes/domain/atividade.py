"""Commits como **sinal** de estudo — nunca como estudo.

Um commit diz que você mexeu num repositório, não o que aprendeu nem quanto tempo levou. Por isso
ele vira uma linha em `activity_signals`, que serve para o agente **perguntar** ("vi 4 commits no
doc-qa-agent, conta como estudo de quê?"). Só a sua resposta cria uma `study_session`, e aí o
sinal guarda o `session_id` — a trilha fica auditável nos dois sentidos.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

GIT_TIMEOUT = 10.0  # segundos por repositório
SEPARADOR = "\x1f"


class AtividadeRecusada(Exception):
    """A operação sobre um sinal não pode ser feita. A mensagem diz o porquê."""


def descobrir_repos(raiz: Path) -> list[Path]:
    """Repositórios git no primeiro nível de `raiz` (ex.: `~/Projetos/*`)."""
    raiz = Path(raiz).expanduser()
    if not raiz.is_dir():
        return []
    return sorted(p for p in raiz.iterdir() if (p / ".git").exists())


def _git(repo: Path, *args: str) -> str:
    resultado = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",  # git fala UTF-8; o padrão do Windows (cp1252) embaralha acento em commit
        errors="replace",
        timeout=GIT_TIMEOUT,
        check=False,
    )
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip() or f"git {args[0]} falhou")
    return resultado.stdout


def commits(repo: Path, dias: int = 1) -> list[dict]:
    """Commits seus nos últimos `dias` dias, do mais novo para o mais velho.

    "Seus" = autor igual ao `user.email` do repositório. Commit de outra pessoa (merge de PR,
    dependabot) não é sinal de que você estudou.
    """
    try:
        email = _git(repo, "config", "user.email").strip()
    except RuntimeError:
        email = ""
    args = [
        "log",
        f"--since={dias} days ago",
        "--no-merges",
        f"--format=%H{SEPARADOR}%ad{SEPARADOR}%s",
        "--date=short",
    ]
    if email:
        args.append(f"--author={email}")
    try:
        saida = _git(repo, *args)
    except RuntimeError as e:
        if "does not have any commits" in str(e):
            return []
        raise
    linhas = []
    for linha in saida.splitlines():
        sha, data, resumo = (linha.split(SEPARADOR, 2) + ["", ""])[:3]
        if sha:
            linhas.append({"ref": sha, "data": data, "resumo": resumo.strip() or "(sem mensagem)"})
    return linhas


def git_activity(
    conn: sqlite3.Connection,
    dias: int = 1,
    repos: list[str] | None = None,
    *,
    repos_conhecidos: tuple[Path, ...] = (),
    status=None,
) -> dict:
    """Lê os commits recentes e grava os que ainda não viraram sinal.

    Devolve os sinais pendentes (`novo` ou `perguntado`) do período, agrupados por repositório,
    e marca os `novo` como `perguntado`: a partir daqui o agente já os mostrou a você.
    `repos` filtra pelo nome da pasta; repositório que falha vira aviso, não derruba o resto.
    """
    from hermes.db import store
    from hermes.run_status import RunStatus

    status = status if status is not None else RunStatus()
    if dias < 1 or dias > 31:
        raise AtividadeRecusada("`dias` vai de 1 a 31")
    alvo = list(repos_conhecidos)
    if repos:
        pedidos = set(repos)
        alvo = [r for r in alvo if r.name in pedidos]
        desconhecidos = pedidos - {r.name for r in alvo}
        if desconhecidos:
            status.add(f"repositório(s) não encontrados: {', '.join(sorted(desconhecidos))}")

    novos = 0
    agora = store.utcnow()
    for repo in alvo:
        try:
            achados = commits(repo, dias)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
            status.add(f"{repo.name}: git log falhou ({e})")
            continue
        with conn:
            # do mais velho para o mais novo: o id do sinal segue a ordem dos commits
            for c in reversed(achados):
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO activity_signals (data, repo, ref, resumo, criado_em)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (c["data"], repo.name, c["ref"], c["resumo"], agora),
                )
                novos += cursor.rowcount

    pendentes = [
        dict(r)
        for r in conn.execute(
            "SELECT id, data, repo, substr(ref, 1, 7) AS sha, resumo, estado"
            " FROM activity_signals"
            " WHERE estado IN ('novo', 'perguntado') AND data >= date('now', 'localtime', ?)"
            " ORDER BY repo, data DESC, id DESC",
            (f"-{dias} days",),
        )
    ]
    with conn:
        conn.executemany(
            "UPDATE activity_signals SET estado = 'perguntado' WHERE id = ? AND estado = 'novo'",
            [(p["id"],) for p in pendentes],
        )

    por_repo: dict[str, list[dict]] = {}
    for p in pendentes:
        por_repo.setdefault(p["repo"], []).append(p)
    return {
        "dias": dias,
        "repos_lidos": [r.name for r in alvo],
        "sinais_novos": novos,
        "pendentes": por_repo,
        "lembrete": "commit é sinal, não estudo: pergunte ao usuário o que ele estudou e por quanto tempo",
    }


def confirmar(
    conn: sqlite3.Connection,
    sinais: list[int],
    minutos: int,
    o_que_fez: str,
    slug: str | None = None,
    dificuldade: int | None = None,
) -> dict:
    """Você confirmou: os sinais viram **uma** sessão de estudo com o que você declarou.

    Vários commits de uma tarde são uma sessão só — quem diz os minutos é você, não a contagem
    de commits.
    """
    from hermes.domain import estudos

    if not sinais:
        raise AtividadeRecusada("informe ao menos um sinal")
    linhas = conn.execute(
        f"SELECT id, data, estado FROM activity_signals WHERE id IN ({','.join('?' * len(sinais))})",
        sinais,
    ).fetchall()
    faltando = set(sinais) - {r["id"] for r in linhas}
    if faltando:
        raise AtividadeRecusada(f"sinal(is) inexistente(s): {sorted(faltando)}")
    resolvidos = [r["id"] for r in linhas if r["estado"] in ("confirmado", "ignorado")]
    if resolvidos:
        raise AtividadeRecusada(f"sinal(is) já resolvido(s): {sorted(resolvidos)}")

    data = max(r["data"] for r in linhas)
    sessao = estudos.log_study(
        conn, minutos, o_que_fez, slug=slug, data=data, dificuldade=dificuldade
    )
    with conn:
        conn.executemany(
            "UPDATE activity_signals SET estado = 'confirmado', session_id = ?,"
            " competency_id = (SELECT competency_id FROM study_sessions WHERE id = ?)"
            " WHERE id = ?",
            [(sessao["id"], sessao["id"], s) for s in sinais],
        )
    return {**sessao, "sinais": sorted(sinais)}


def ignorar(conn: sqlite3.Connection, sinais: list[int]) -> dict:
    """Commit que não foi estudo (ajuste de config, typo). Sai da lista de perguntas."""
    if not sinais:
        raise AtividadeRecusada("informe ao menos um sinal")
    with conn:
        cursor = conn.execute(
            f"UPDATE activity_signals SET estado = 'ignorado'"
            f" WHERE id IN ({','.join('?' * len(sinais))}) AND estado IN ('novo', 'perguntado')",
            sinais,
        )
    return {"ignorados": cursor.rowcount}
