"""Onde moram configuração, banco e saídas — no checkout, numa pasta escolhida ou no app instalado.

Uma regra só, com o mesmo layout nos três casos (`.env`, `curriculos.yaml`, `data/`, `out/`…):

- `HERMES_HOME` definido: tudo mora lá.
- Binário congelado (o app instalado): a pasta de dados do usuário no sistema.
- Senão: a raiz do repositório, como sempre foi.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP = "quilha"
# Padrões que o binário congelado leva dentro de si (o spec do PyInstaller copia da raiz para cá).
EMBUTIDOS = Path(__file__).resolve().parent / "dados"
PADROES = (
    "competencias.yaml",
    "curriculos.example.yaml",
    "fontes.example.yaml",
    "mcp.example.yaml",
    "denylist.example.yaml",
)


def congelado() -> bool:
    return bool(getattr(sys, "frozen", False))


def base() -> Path:
    if home := os.getenv("HERMES_HOME"):
        return Path(home).expanduser()
    if congelado():
        from platformdirs import user_data_dir

        return Path(user_data_dir(APP, appauthor=False))
    return PROJECT_ROOT


def preparar() -> list[Path]:
    """Copia para a base os padrões que ainda não estão lá. Nunca sobrescreve; devolve o que copiou."""
    destino = base()
    if destino == PROJECT_ROOT:
        return []
    origem = EMBUTIDOS if EMBUTIDOS.is_dir() else PROJECT_ROOT
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "data" / "gmail").mkdir(parents=True, exist_ok=True)  # onde a tela manda pôr o credentials.json
    copiados = []
    for nome in PADROES:
        alvo = destino / nome
        if not alvo.exists() and (origem / nome).is_file():
            shutil.copyfile(origem / nome, alvo)
            copiados.append(alvo)
    return copiados
