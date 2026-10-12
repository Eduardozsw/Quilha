"""Dados de cabeçalho do currículo: quem você é, contato e formação.

Mora em `Perfil.md` na **raiz** do vault, não em `Carreira/`. O motivo é que perfil não é fato:
nada aqui é citado como evidência nem recebe block id, então fica fora do índice e fora da
validação de fatos sem precisar de exceção no reader.
"""

from __future__ import annotations

from pathlib import Path

from hermes.vault.reader import split_frontmatter

ARQUIVO = "Perfil.md"
OBRIGATORIOS = ("nome",)

TEMPLATE = """---
nome: Seu Nome Completo
cargo_alvo: Desenvolvedor de Automação (RPA)
email: voce@exemplo.com
telefone:
cidade: Cidade, UF
github: https://github.com/usuario
linkedin:
formacao:
  - curso: Nome do curso
    instituicao: Instituição
    periodo: 2024–2027 (cursando)
idiomas:
  - Português (nativo)
  - Inglês (leitura técnica)
---

# Perfil

Este arquivo é só cabeçalho de currículo. O que sustenta as afirmações continua em `Carreira/`.
"""


class PerfilAusente(FileNotFoundError):
    """Sem perfil não há cabeçalho de currículo. A mensagem diz o que criar."""


def caminho(vault_path: str | Path) -> Path:
    return Path(vault_path) / ARQUIVO


def carregar(vault_path: str | Path) -> dict:
    alvo = caminho(vault_path)
    if not alvo.is_file():
        raise PerfilAusente(
            f"`{alvo}` não existe. Crie o arquivo com este conteúdo e ajuste os campos:\n\n{TEMPLATE}"
        )

    frontmatter, _, erro = split_frontmatter(alvo.read_text(encoding="utf-8"))
    if erro:
        raise PerfilAusente(f"`{alvo}`: {erro}")

    faltando = [c for c in OBRIGATORIOS if not frontmatter.get(c)]
    if faltando:
        raise PerfilAusente(f"`{alvo}` sem {', '.join(faltando)}")

    return {k: v for k, v in frontmatter.items() if v not in (None, "", [], {})}

