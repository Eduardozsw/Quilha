"""Configuração do Hermes, lida do ambiente (`.env` na base de `hermes.caminhos`)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from hermes import caminhos
from hermes.caminhos import PROJECT_ROOT  # noqa: F401 (reexportado)


@dataclass(frozen=True)
class Config:
    vault_path: Path
    db_path: Path
    denylist_path: Path
    llm_model: str
    max_cost_usd: float
    repos_dir: Path = Path("~/Projetos").expanduser()
    fontes_path: Path = Path("fontes.yaml")
    mcp_path: Path = Path("mcp.yaml")
    backup_dir: Path = Path("data/backups")
    perfis_cv_path: Path = Path("curriculos.yaml")
    competencias_path: Path = Path("competencias.yaml")
    saida_dir: Path = Path("out")
    gmail_dir: Path = Path("data/gmail")
    # tools que gravam sem perguntar: baixo risco, alto atrito (especificacoes.md §2)
    sem_confirmacao: frozenset[str] = frozenset({"log_study", "git_activity"})


def resolve_path(value: str | Path) -> Path:
    """Expande `~` e resolve caminho relativo contra a base (raiz do projeto, `HERMES_HOME` ou app)."""
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else caminhos.base() / path


def load_config(
    vault_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> Config:
    """Lê o .env e devolve a configuração. Argumentos explícitos vencem o ambiente."""
    load_dotenv(caminhos.base() / ".env")
    return Config(
        vault_path=resolve_path(vault_path or os.getenv("VAULT_PATH", "~/Obsidian")),
        db_path=resolve_path(db_path or os.getenv("HERMES_DB", "data/hermes.db")),
        denylist_path=resolve_path(os.getenv("HERMES_DENYLIST", "denylist.yaml")),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        max_cost_usd=float(os.getenv("HERMES_MAX_COST_USD", "0.50")),
        repos_dir=resolve_path(os.getenv("HERMES_REPOS_DIR", "~/Projetos")),
        fontes_path=resolve_path(os.getenv("HERMES_FONTES", "fontes.yaml")),
        mcp_path=resolve_path(os.getenv("HERMES_MCP", "mcp.yaml")),
        backup_dir=resolve_path(os.getenv("HERMES_BACKUP_DIR", "data/backups")),
        perfis_cv_path=resolve_path(os.getenv("HERMES_CURRICULOS", "curriculos.yaml")),
        competencias_path=resolve_path(os.getenv("HERMES_COMPETENCIAS", "competencias.yaml")),
        saida_dir=resolve_path(os.getenv("HERMES_SAIDA", "out")),
        gmail_dir=resolve_path(os.getenv("HERMES_GMAIL_DIR", "data/gmail")),
        sem_confirmacao=frozenset(
            t.strip()
            for t in os.getenv("HERMES_SEM_CONFIRMACAO", "log_study,git_activity").split(",")
            if t.strip()
        ),
    )
