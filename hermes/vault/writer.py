"""Escrita no vault. O único lugar do Hermes que toca o Obsidian para escrever.

Duas regras, garantidas aqui e não por quem chama:
- só escreve dentro das pastas liberadas (`Diario/`, `Estudos/`): `Carreira/` é sua, e é dela que
  sai o currículo;
- só **acrescenta**: nota existente recebe o trecho no fim, nunca é reescrita.

A exceção é a nota **gerada** (`substituir_gerada`): um espelho do banco na raiz do vault, reescrito
inteiro a cada exportação. Só é sobrescrita se já carrega a marca `gerado_por: hermes` no
frontmatter — nota escrita à mão com o mesmo nome nunca é tocada.

Mostrar o trecho e pedir confirmação é trabalho da CLI; este módulo não conhece terminal.
"""

from __future__ import annotations

from pathlib import Path

PASTAS_LIBERADAS = ("Diario", "Estudos")


class EscritaRecusada(Exception):
    """Caminho fora das pastas liberadas ou nome de nota inválido."""


def caminho_da_nota(vault: Path, pasta: str, nome: str) -> Path:
    if pasta not in PASTAS_LIBERADAS:
        raise EscritaRecusada(f"o Hermes só escreve em {', '.join(PASTAS_LIBERADAS)}; não em `{pasta}`")
    if not nome or "/" in nome or "\\" in nome or nome.startswith("."):
        raise EscritaRecusada(f"nome de nota inválido: `{nome}`")
    raiz = (Path(vault).expanduser() / pasta).resolve()
    destino = (raiz / f"{nome}.md").resolve()
    if destino.parent != raiz:  # symlink ou `..` que escaparia da pasta
        raise EscritaRecusada(f"`{nome}` sairia de {pasta}/")
    return destino


def acrescentar(vault: Path, pasta: str, nome: str, trecho: str, titulo: str | None = None) -> dict:
    """Acrescenta `trecho` ao fim da nota; cria a nota (com `titulo`) se ela não existir."""
    destino = caminho_da_nota(vault, pasta, nome)
    if not Path(vault).expanduser().is_dir():
        raise EscritaRecusada(f"vault não encontrado em {vault}")
    destino.parent.mkdir(exist_ok=True)
    criada = not destino.exists()
    with destino.open("a", encoding="utf-8") as f:
        if criada:
            f.write(f"# {titulo or nome}\n\n")
        else:
            f.write("\n")
        f.write(trecho if trecho.endswith("\n") else trecho + "\n")
    return {"caminho": str(destino), "criada": criada}


MARCA_GERADA = "---\ngerado_por: hermes"


def substituir_gerada(vault: Path, nome: str, conteudo: str) -> dict:
    """Escreve `<vault>/<nome>.md` inteiro. Recusa se a nota existente não foi gerada pelo Hermes."""
    if not conteudo.startswith(MARCA_GERADA):
        raise EscritaRecusada("conteúdo sem a marca `gerado_por: hermes` no frontmatter")
    if not nome or "/" in nome or "\\" in nome or nome.startswith("."):
        raise EscritaRecusada(f"nome de nota inválido: `{nome}`")
    raiz = Path(vault).expanduser().resolve()
    if not raiz.is_dir():
        raise EscritaRecusada(f"vault não encontrado em {vault}")
    destino = (raiz / f"{nome}.md").resolve()
    if destino.parent != raiz:
        raise EscritaRecusada(f"`{nome}` sairia da raiz do vault")
    criada = not destino.exists()
    if not criada and not destino.read_text(encoding="utf-8").startswith(MARCA_GERADA):
        raise EscritaRecusada(
            f"{destino.name} existe e não foi gerada pelo Hermes; renomeie ou apague antes de exportar"
        )
    destino.write_text(conteudo, encoding="utf-8")
    return {"caminho": str(destino), "criada": criada}
