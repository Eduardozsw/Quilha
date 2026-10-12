"""Configuração editável pelo app: o `.env` da base, sem o usuário abrir arquivo.

Só as chaves de `EDITAVEIS` passam por aqui; o resto do `.env` é preservado linha a linha. Chave
secreta nunca volta para a tela — só se está definida.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from hermes import caminhos
from hermes.config import Config, resolve_path
from hermes.domain.perfil import ARQUIVO as ARQUIVO_PERFIL
from hermes.domain.perfil import TEMPLATE as TEMPLATE_PERFIL
from hermes.vault.reader import CAREER_DIR

EDITAVEIS = ("VAULT_PATH", "LLM_MODEL", "LLM_API_KEY", "EMAIL_CLASSIFICADOR", "TYPESAFE_API_KEY",
             "EMAIL_ORIGEM", "IMAP_HOST", "IMAP_USUARIO", "IMAP_SENHA", "HERMES_MAX_COST_USD", "EMAIL_DIAS")
CLASSIFICADORES = ("llm", "jev")
ORIGENS = ("gmail", "imap")
SECRETAS = frozenset({"LLM_API_KEY", "TYPESAFE_API_KEY", "IMAP_SENHA"})
DIAS_PADRAO = 30

NOTA_EXEMPLO = """---
type: project
id: projeto-exemplo
nome: Projeto Exemplo
subtitulo: {pt: "troque pelo seu projeto", en: "replace with your project"}
stack: [python]
inicio: 2026-01
---

# Projeto Exemplo

Uma nota por emprego (`type: experience`) ou projeto (`type: project`). Cada fato termina num
block id: é ele que o currículo cita.

## Fatos

- Escreveu um script em Python que organiza arquivos por data #python ^script-organizador
- Cobriu o script com 12 testes automatizados, medidos em 01/2026 #python ^testes-script
"""


class ConfiguracaoRecusada(Exception):
    pass


def arquivo_env() -> Path:
    return caminhos.base() / ".env"


def _pasta_livre(base: Path) -> Path:
    """`~/Quilha`, ou `~/Quilha 2`, `~/Quilha 3`… se já existir: o vault de exemplo nunca entra numa pasta sua."""
    if not base.exists():
        return base
    n = 2
    while (base.parent / f"{base.name} {n}").exists():
        n += 1
    return base.parent / f"{base.name} {n}"


def _limite(valor: str) -> str:
    try:
        n = float(valor.replace(",", "."))
    except ValueError:
        raise ConfiguracaoRecusada("Limite por execução: escreva um valor em dólares, como 0,50") from None
    if not 0 < n <= 100:
        raise ConfiguracaoRecusada("Limite por execução: use um valor acima de 0 e até 100 dólares")
    return f"{n:g}"


def _dias(valor: str) -> str:
    if not valor.isdigit() or not 1 <= int(valor) <= 365:
        raise ConfiguracaoRecusada("Buscar e-mails: use de 1 a 365 dias")
    return str(int(valor))


def _dias_do_ambiente() -> int:
    """`EMAIL_DIAS` editado à mão com lixo não derruba a configuração: vale o padrão."""
    valor = (os.getenv("EMAIL_DIAS") or "").strip()
    return int(valor) if valor.isdigit() and 1 <= int(valor) <= 365 else DIAS_PADRAO


def _ultima_copia(pasta: Path) -> str | None:
    """Quando foi a cópia mais nova do banco (`hermes-*.db`), pela data do arquivo; nenhuma = None."""
    pasta = Path(pasta)
    copias = sorted(pasta.glob("hermes-*.db"), key=lambda p: p.stat().st_mtime) if pasta.is_dir() else []
    if not copias:
        return None
    return datetime.fromtimestamp(copias[-1].stat().st_mtime, timezone.utc).isoformat()


def _versao() -> str:
    try:
        return importlib.metadata.version("hermes")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def estado(cfg: Config) -> dict:
    vault = Path(cfg.vault_path)
    carreira = vault / CAREER_DIR
    notas = sum(1 for _ in carreira.rglob("*.md")) if carreira.is_dir() else 0
    return {
        "base": str(caminhos.base()),
        "vault": {"caminho": str(vault), "existe": vault.is_dir(), "notas": notas,
                  "sugestao": str(_pasta_livre(Path.home() / "Quilha"))},
        "llm": {"modelo": cfg.llm_model, "chave_definida": bool(os.getenv("LLM_API_KEY")),
                "limite_usd": cfg.max_cost_usd},
        "triagem": {"classificador": (os.getenv("EMAIL_CLASSIFICADOR") or "llm").strip().lower() or "llm",
                    "jev_chave_definida": bool(os.getenv("TYPESAFE_API_KEY"))},
        "email": {
            "origem": (os.getenv("EMAIL_ORIGEM") or "gmail").strip().lower(),
            "imap_host": os.getenv("IMAP_HOST") or "imap.gmail.com",
            "imap_usuario": os.getenv("IMAP_USUARIO", ""),
            "imap_senha_definida": bool(os.getenv("IMAP_SENHA")),
            "gmail_pasta": str(cfg.gmail_dir),
            "gmail_credenciais": (Path(cfg.gmail_dir) / "credentials.json").is_file(),
            # labels `Vagas/…` só existem pelo OAuth: quem escreve na caixa é a Gmail API
            "rotulos_disponiveis": (os.getenv("EMAIL_ORIGEM") or "gmail").strip().lower() == "gmail",
            "dias": _dias_do_ambiente(),
        },
        "pastas": {"base": str(caminhos.base()), "saida": str(cfg.saida_dir), "backups": str(cfg.backup_dir),
                   "ultima_copia": _ultima_copia(cfg.backup_dir)},
        "app": {"versao": _versao(), "sistema": platform.system() or "desconhecido"},
        "pronto": vault.is_dir() and notas > 0,
        # a tela de boas-vindas some quando o usuário escolhe um vault (ou já tinha um no `.env`)
        "configurado": bool((dotenv_values(arquivo_env()) if arquivo_env().exists() else {}).get("VAULT_PATH")),
    }


def gravar(cfg: Config, valores: dict[str, str | None]) -> Config:
    """Grava no `.env` (0600), aplica no processo e devolve a config nova. `None` = não mexe; "" = apaga."""
    mudancas = {k: v for k, v in valores.items() if v is not None}
    for chave, valor in mudancas.items():
        if chave not in EDITAVEIS:
            raise ConfiguracaoRecusada(f"`{chave}` não é editável pelo app")
        if "\n" in valor or "\r" in valor:
            raise ConfiguracaoRecusada(f"`{chave}` não pode ter quebra de linha")
        if chave == "EMAIL_CLASSIFICADOR" and valor and valor not in CLASSIFICADORES:
            raise ConfiguracaoRecusada(f"EMAIL_CLASSIFICADOR: use um de {list(CLASSIFICADORES)}")
        if chave == "EMAIL_ORIGEM" and valor and valor not in ORIGENS:
            raise ConfiguracaoRecusada(f"EMAIL_ORIGEM: use um de {list(ORIGENS)}")
    # limite e dias sempre têm valor: apagar o campo na tela não pode tirar a proteção em silêncio
    if mudancas.get("HERMES_MAX_COST_USD") == "":
        raise ConfiguracaoRecusada("Limite por execução: escreva um valor em dólares, como 0,50")
    if mudancas.get("EMAIL_DIAS") == "":
        raise ConfiguracaoRecusada("Buscar e-mails: use de 1 a 365 dias")
    if mudancas.get("HERMES_MAX_COST_USD"):
        mudancas["HERMES_MAX_COST_USD"] = _limite(mudancas["HERMES_MAX_COST_USD"])
    if mudancas.get("EMAIL_DIAS"):
        mudancas["EMAIL_DIAS"] = _dias(mudancas["EMAIL_DIAS"])
    if mudancas.get("VAULT_PATH"):
        mudancas["VAULT_PATH"] = str(Path(mudancas["VAULT_PATH"]).expanduser())

    caminho = arquivo_env()
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    pendentes = dict(mudancas)
    saida = []
    for linha in linhas:
        achada = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", linha)
        if achada and achada.group(1) in pendentes:
            saida.append(f"{achada.group(1)}={_aspas(pendentes.pop(achada.group(1)))}")
        else:
            saida.append(linha)
    saida += [f"{k}={_aspas(v)}" for k, v in pendentes.items()]

    caminho.parent.mkdir(parents=True, exist_ok=True)
    descritor = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descritor, "w", encoding="utf-8") as f:
        f.write("\n".join(saida) + "\n")
    os.chmod(caminho, 0o600)  # o arquivo pode já existir com permissão mais aberta

    for chave, valor in mudancas.items():
        if valor:
            os.environ[chave] = valor
        else:
            os.environ.pop(chave, None)
    novo = cfg
    if "VAULT_PATH" in mudancas and mudancas["VAULT_PATH"]:
        novo = replace(novo, vault_path=resolve_path(mudancas["VAULT_PATH"]))
    if mudancas.get("LLM_MODEL"):
        novo = replace(novo, llm_model=mudancas["LLM_MODEL"])
    if mudancas.get("HERMES_MAX_COST_USD"):
        novo = replace(novo, max_cost_usd=float(mudancas["HERMES_MAX_COST_USD"]))
    return novo


def inicializar(conn: sqlite3.Connection, cfg: Config) -> int:
    """Banco novo (app recém-instalado): carrega a taxonomia padrão. Banco com competência: não mexe."""
    from hermes.domain import competencias

    if conn.execute("SELECT 1 FROM competencies LIMIT 1").fetchone() or not Path(cfg.competencias_path).is_file():
        return 0
    criadas, _ = competencias.seed(conn, cfg.competencias_path)
    return criadas


def criar_vault_exemplo(destino: str | Path) -> list[str]:
    """Vault inicial com uma nota de exemplo e o `Perfil.md`. Não toca em nada que já exista."""
    raiz = Path(destino).expanduser()
    if raiz.exists() and not raiz.is_dir():
        raise ConfiguracaoRecusada(f"{raiz} existe e não é uma pasta")
    arquivos = {
        Path(CAREER_DIR) / "Projetos" / "Projeto Exemplo.md": NOTA_EXEMPLO,
        Path(ARQUIVO_PERFIL): TEMPLATE_PERFIL,
    }
    criados = []
    for relativo, conteudo in arquivos.items():
        alvo = raiz / relativo
        if alvo.exists():
            continue
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo, encoding="utf-8")
        criados.append(str(relativo))
    return criados


def _aspas(valor: str) -> str:
    """Aspas simples: o dotenv não interpreta `\\n` nelas (caminho do Windows sobrevive)."""
    if not re.search(r"[\s#'\"\\]", valor):
        return valor
    return "'" + valor.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ---------- chave do LLM recusada ----------
# Uma recusa de autenticação em qualquer rota acende o aviso; trocar a chave (ou o modelo) ou um teste
# que passou apaga. Mora em `estado_app` porque precisa sobreviver a reiniciar o app.

RECUSADA = "llm_recusada"
PREFIXO_RECUSA = "o provedor do LLM recusou a chave"


def marcar_recusa(conn: sqlite3.Connection, quando: str) -> None:
    conn.execute("INSERT INTO estado_app (chave, valor) VALUES (?, ?)"
                 " ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (RECUSADA, quando))
    conn.commit()


def limpar_recusa(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM estado_app WHERE chave = ?", (RECUSADA,))
    conn.commit()


def lembrar_recusa_nos_avisos(conn: sqlite3.Connection, avisos) -> None:
    """A triagem transforma a falha de cada e-mail em aviso; uma recusa da chave entre eles acende o status."""
    if any(PREFIXO_RECUSA in str(a) for a in avisos):
        from hermes.db import store

        marcar_recusa(conn, store.utcnow())


def chave_recusada(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM estado_app WHERE chave = ?", (RECUSADA,)).fetchone() is not None


def _chamada_minima(status=None) -> None:
    from hermes import llm

    llm.complete("Responda só: ok", "ok", status=status, max_tokens=5, temperature=0)
