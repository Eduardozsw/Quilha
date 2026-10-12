"""Leitura do vault Obsidian.

O vault é a fonte da verdade (ver `Como usar este vault.md`). Só é indexado o que
está na seção `## Fatos`, um item de lista por fato, cada um terminado por um
block id do Obsidian (`^algum-id`) — o ID estável que o currículo cita.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CAREER_DIR = "Carreira"
IGNORED_DIRS = {"Templates", ".obsidian", ".trash"}
TIPOS_VALIDOS = ("experience", "project")
FACTS_HEADING = "## Fatos"

BLOCK_ID_RE = re.compile(r"\s\^([A-Za-z0-9][A-Za-z0-9_-]*)\s*$")
TAG_RE = re.compile(r"#([A-Za-z][A-Za-z0-9_-]*)")
TRAILING_TAGS_RE = re.compile(r"(?:\s+#[A-Za-z][A-Za-z0-9_-]*)+\s*$")
BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
HEADING_RE = re.compile(r"^#{1,6}\s")


@dataclass
class Fact:
    nota: str
    block_id: str | None
    texto: str
    tags: list[str]
    linha: int


@dataclass
class Note:
    caminho: Path
    nota: str
    frontmatter: dict = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    tem_secao_fatos: bool = False
    erro_frontmatter: str | None = None
    texto_bruto: str = ""

    @property
    def tipo(self) -> str | None:
        valor = self.frontmatter.get("type")
        return valor if isinstance(valor, str) else None

    @property
    def entidade(self) -> str | None:
        valor = self.frontmatter.get("id")
        return valor if isinstance(valor, str) else None

    @property
    def titulo(self) -> str | None:
        """Nome para exibir: `nome` do projeto ou `empresa` da experiência; senão, o `id`."""
        campo = "empresa" if self.tipo == "experience" else "nome"
        valor = self.frontmatter.get(campo)
        return valor.strip() if isinstance(valor, str) and valor.strip() else self.entidade


def split_frontmatter(texto: str) -> tuple[dict, str, str | None]:
    """Devolve (frontmatter, corpo, erro). Sem frontmatter, erro explica o porquê."""
    linhas = texto.splitlines()
    if not linhas or linhas[0].strip() != "---":
        return {}, texto, "nota sem frontmatter"
    for i in range(1, len(linhas)):
        if linhas[i].strip() == "---":
            bruto = "\n".join(linhas[1:i])
            corpo = "\n".join(linhas[i + 1 :])
            try:
                dados = yaml.safe_load(bruto) or {}
            except yaml.YAMLError as exc:
                return {}, corpo, f"frontmatter inválido: {exc}"
            if not isinstance(dados, dict):
                return {}, corpo, "frontmatter não é um mapa YAML"
            return dados, corpo, None
    return {}, texto, "frontmatter sem fechamento (`---`)"


def _corta_secao_fatos(corpo: str, offset: int) -> tuple[list[tuple[int, str]], bool]:
    """Linhas da seção `## Fatos`, numeradas na origem do arquivo."""
    linhas = corpo.splitlines()
    inicio = None
    for i, linha in enumerate(linhas):
        if linha.strip() == FACTS_HEADING:
            inicio = i + 1
            break
    if inicio is None:
        return [], False
    coletadas: list[tuple[int, str]] = []
    for i in range(inicio, len(linhas)):
        if linhas[i].startswith("## "):
            break
        coletadas.append((offset + i + 1, linhas[i]))
    return coletadas, True


def _parse_fato(nota: str, linha_num: int, texto: str) -> Fact:
    block_id = None
    match = BLOCK_ID_RE.search(texto)
    if match:
        block_id = match.group(1)
        texto = texto[: match.start()]
    tags = TAG_RE.findall(texto)
    texto = TRAILING_TAGS_RE.sub("", texto).strip()
    return Fact(nota=nota, block_id=block_id, texto=texto, tags=tags, linha=linha_num)


def parse_note(caminho: Path, vault_root: Path) -> Note:
    bruto = caminho.read_text(encoding="utf-8")
    nota = caminho.relative_to(vault_root).as_posix()
    frontmatter, corpo, erro = split_frontmatter(bruto)
    offset = len(bruto.splitlines()) - len(corpo.splitlines())

    linhas, tem_secao = _corta_secao_fatos(corpo, offset)
    facts: list[Fact] = []
    atual: tuple[int, str] | None = None
    for linha_num, linha in linhas:
        bullet = BULLET_RE.match(linha)
        if bullet:
            if atual:
                facts.append(_parse_fato(nota, atual[0], atual[1]))
            atual = (linha_num, bullet.group(1))
        elif atual and linha.strip() and not HEADING_RE.match(linha):
            # continuação indentada do item anterior
            atual = (atual[0], f"{atual[1]} {linha.strip()}")
        elif not linha.strip() and atual:
            facts.append(_parse_fato(nota, atual[0], atual[1]))
            atual = None
    if atual:
        facts.append(_parse_fato(nota, atual[0], atual[1]))

    return Note(
        caminho=caminho,
        nota=nota,
        frontmatter=frontmatter,
        facts=facts,
        tem_secao_fatos=tem_secao,
        erro_frontmatter=erro,
        texto_bruto=bruto,
    )


class IndexacaoCancelada(Exception):
    """A pessoa cancelou a leitura do vault; nada foi gravado."""


def read_notes(vault_root: Path, progresso=None, cancelado=None) -> list[Note]:
    """Todas as notas de `Carreira/`, ignorando Templates e pastas internas.

    `progresso(feitas, total)` é chamado a cada nota lida; `cancelado()` verdadeiro interrompe a leitura
    com `IndexacaoCancelada` (antes de qualquer gravação: quem grava é o chamador, depois de ler tudo).
    """
    raiz = Path(vault_root)
    carreira = raiz / CAREER_DIR
    if not carreira.is_dir():
        return []
    caminhos = [c for c in sorted(carreira.rglob("*.md")) if not IGNORED_DIRS & set(c.relative_to(raiz).parts)]
    notas = []
    for i, caminho in enumerate(caminhos, start=1):
        if cancelado is not None and cancelado():
            raise IndexacaoCancelada("leitura do vault cancelada")
        notas.append(parse_note(caminho, raiz))
        if progresso is not None:
            progresso(i, len(caminhos))
    return notas
