"""Validação do vault. Sem LLM, sem rede, custo zero.

Erro (`erro`) faz o comando sair com código 1. Aviso (`aviso`) só sai com 1 no
modo `--strict`. Um termo da denylist é sempre erro: nada é enviado para a API
enquanto ele estiver no vault.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from hermes.vault.reader import FACTS_HEADING, TIPOS_VALIDOS, Note

# Heurística do "número sem fonte": um número de 2+ dígitos ou percentual no
# fato, sem nada que diga de onde ele veio (N=, denominador, data, período).
# É um empurrão, não um portão: escala ("de 0 a 10") e constante de protocolo
# ("limite de 4.096 caracteres") são descontadas para o aviso não virar ruído.
NUMERO_RE = re.compile(r"\b\d+\s*%|\b\d{2,}(?:[.,]\d+)?\b")
FONTE_RE = re.compile(
    r"(N\s*=\s*\d+|\d+\s+de\s+\d+|fonte|medid|\b(?:19|20)\d{2}\b|\d{1,2}/\d{1,2})",
    re.IGNORECASE,
)
ESCALA_RE = re.compile(r"\bde\s+\d+\s+a\s+\d+\b", re.IGNORECASE)
CONSTANTE_RE = re.compile(r"\b(limite|m[áa]xim|m[íi]nim|vers[ãa]o|escala)", re.IGNORECASE)


def numero_sem_fonte(texto: str) -> bool:
    if ESCALA_RE.search(texto) or CONSTANTE_RE.search(texto):
        return False
    return bool(NUMERO_RE.search(texto)) and not FONTE_RE.search(texto)


# Um fato "com métrica" é o oposto do aviso acima: tem número E diz de onde ele
# veio. É o que a regra de nível 3 exige da evidência.
PERIODO_RE = re.compile(
    r"(de\s+\d{1,2}/\d{1,2}.{0,20}?a\s+\d{1,2}/\d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}.{0,20}?\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)


def tem_metrica(texto: str) -> bool:
    return bool(NUMERO_RE.search(texto)) and bool(FONTE_RE.search(texto))


def tem_periodo(texto: str) -> bool:
    """Um intervalo de datas explícito. Exigido pelo nível 4 (rodou em operação)."""
    return bool(PERIODO_RE.search(texto))


@dataclass
class Problem:
    nivel: str  # 'erro' | 'aviso'
    nota: str
    mensagem: str
    linha: int | None = None


def load_denylist(caminho: Path) -> list[str]:
    """Termos que não podem sair da máquina. Arquivo ausente = lista vazia."""
    if not Path(caminho).is_file():
        return []
    dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    termos = dados.get("termos") or []
    return [str(t).strip() for t in termos if str(t).strip()]


def check_notes(notes: list[Note], denylist: list[str] | None = None) -> list[Problem]:
    problemas: list[Problem] = []
    termos = [t.lower() for t in (denylist or [])]

    for nota in notes:
        if nota.erro_frontmatter:
            problemas.append(Problem("erro", nota.nota, nota.erro_frontmatter, 1))
        else:
            if nota.tipo not in TIPOS_VALIDOS:
                problemas.append(
                    Problem(
                        "erro",
                        nota.nota,
                        f"`type` ausente ou inválido (esperado um de {list(TIPOS_VALIDOS)})",
                        1,
                    )
                )
            if not nota.entidade:
                problemas.append(Problem("erro", nota.nota, "`id` ausente no frontmatter", 1))

        if not nota.tem_secao_fatos:
            problemas.append(Problem("erro", nota.nota, f"nota sem seção `{FACTS_HEADING}`"))
        elif not nota.facts:
            problemas.append(
                Problem("aviso", nota.nota, f"seção `{FACTS_HEADING}` vazia: a nota não entra no currículo")
            )

        vistos: dict[str, int] = {}
        for fato in nota.facts:
            if not fato.texto:
                problemas.append(Problem("erro", nota.nota, "fato sem texto", fato.linha))
                continue
            if not fato.block_id:
                problemas.append(
                    Problem("erro", nota.nota, "fato sem block id (`^algum-id`)", fato.linha)
                )
            elif fato.block_id in vistos:
                problemas.append(
                    Problem(
                        "erro",
                        nota.nota,
                        f"block id `^{fato.block_id}` repetido (já usado na linha {vistos[fato.block_id]})",
                        fato.linha,
                    )
                )
            else:
                vistos[fato.block_id] = fato.linha

            if numero_sem_fonte(fato.texto):
                problemas.append(
                    Problem("aviso", nota.nota, "número sem N, fonte ou período no fato", fato.linha)
                )

        baixo = nota.texto_bruto.lower()
        for termo in termos:
            if termo in baixo:
                problemas.append(
                    Problem("erro", nota.nota, f"termo da denylist na nota: `{termo}`")
                )

    return problemas


def check_orphan_evidence(orfas: list[dict]) -> list[Problem]:
    """Evidência cujo block id sumiu do vault. Nunca apagada em silêncio."""
    return [
        Problem(
            "aviso",
            o["nota"],
            f"evidência órfã: `{o['slug']}` aponta para `^{o['block_id']}`, que não existe mais",
        )
        for o in orfas
    ]


def _normaliza(termo: str) -> str:
    """`Spring Boot`, `spring-boot` e `Spring-boot` são a mesma coisa; `Automação` é `automacao`."""
    sem_acento = unicodedata.normalize("NFKD", termo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def check_habilidades(perfis, notes: list[Note]) -> list[Problem]:
    """Declaração não é fato: item de habilidade que nenhuma nota sustenta vira aviso.

    Sustenta quem aparece no `stack` de alguma nota ou em tag de fato. `Java (Spring Boot)` é
    conferido por partes — `java` e `spring-boot` — e o aviso nomeia só a parte que faltou.
    """
    conhecidos = set()
    for nota in notes:
        stack = nota.frontmatter.get("stack") if not nota.erro_frontmatter else None
        conhecidos |= {_normaliza(str(s)) for s in (stack if isinstance(stack, list) else [])}
        conhecidos |= {_normaliza(t) for fato in nota.facts for t in fato.tags}

    problemas = []
    for perfil in perfis:
        for linha in perfil.habilidades:
            for item in (i["pt"] for i in linha["itens"]):  # o EN é tradução do mesmo item
                partes = [p.strip() for p in re.split(r"[(),/]", item) if p.strip()]
                faltando = [p for p in partes if _normaliza(p) not in conhecidos]
                if faltando:
                    onde = f"linha {linha['rotulo']['pt']}" + ("" if faltando == [item] else f", em `{item}`")
                    problemas.append(Problem(
                        "aviso", f"curriculos.yaml ({perfil.slug})",
                        f"habilidade sem stack nem tag que a sustente: `{', '.join(faltando)}` ({onde})",
                    ))
    return problemas


def check_curriculos(caminho: Path, notes: list[Note]) -> list[Problem]:
    """Habilidades de todos os perfis de `curriculos.yaml`. Arquivo inválido é erro."""
    from hermes.domain import perfis_cv

    try:
        return check_habilidades(perfis_cv.carregar(caminho), notes)
    except perfis_cv.PerfilInvalido as exc:
        return [Problem("erro", Path(caminho).name, str(exc))]


def exit_code(problemas: list[Problem], strict: bool = False) -> int:
    if any(p.nivel == "erro" for p in problemas):
        return 1
    if strict and problemas:
        return 1
    return 0
