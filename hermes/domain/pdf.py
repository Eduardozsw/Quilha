"""PDF do currículo: a estrutura (`curriculo.estruturar`) passa pelo template Typst.

O PDF é artefato, não fonte: nada nele é editado à mão. Por isso a checagem de páginas **falha em
vez de cortar** — dizer o que ocupa mais espaço é trabalho do código; escolher o que sai é seu.
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "cv.typ"
FONTES = TEMPLATE.parent / "fonts"

# Passo de uma linha de corpo no template, medido: o Typst conta a caixa da linha da altura das
# maiúsculas à linha de base, mais a entrelinha (0,5 em). Mudou o template, meça de novo
# (`test_linhas_estimadas_batem_com_o_que_se_ve`).
PT_POR_LINHA = 9.7


class PaginasDemais(RuntimeError):
    """O currículo passou do limite de páginas. `entradas` vem da maior para a menor."""

    def __init__(self, paginas: int, limite: int, entradas: list[dict], destino: Path):
        self.paginas, self.limite, self.entradas, self.destino = paginas, limite, entradas, destino
        maiores = ", ".join(f"{e['titulo']} (~{e['linhas']} linhas)" for e in entradas[:3])
        super().__init__(
            f"{paginas} páginas, o limite é {limite}. O que mais ocupa: {maiores}. "
            "Corte com `--limite` ou tire bullets no vault; o PDF ficou em "
            f"{destino} para você ver onde passou."
        )


def _consultar(fonte: bytes, entradas: dict, seletor: str) -> list:
    import typst

    return json.loads(typst.query(fonte, seletor, field="value", root=str(TEMPLATE.parent),
                                  font_paths=[str(FONTES)], ignore_system_fonts=True,
                                  sys_inputs=entradas))


class PdfFalhou(Exception):
    """O Typst não conseguiu montar o PDF. A mensagem é a primeira linha do erro dele."""


def compilar(estrutura: dict, destino: str | Path, paginas: int = 1) -> dict:
    """Grava o PDF em `destino` e confere o número de páginas.

    Devolve `{"paginas": n, "entradas": [{secao, titulo, linhas}, ...]}`, entradas da maior para a
    menor. Passou de `paginas`: grava mesmo assim e levanta `PaginasDemais`.
    """
    import typst

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fonte = TEMPLATE.read_bytes()
    # o JSON vai como texto: é dado para o template, nunca marcação Typst
    entradas = {"dados": json.dumps(estrutura, ensure_ascii=False)}

    try:
        destino.write_bytes(typst.compile(fonte, root=str(TEMPLATE.parent), font_paths=[str(FONTES)],
                                          ignore_system_fonts=True, sys_inputs=entradas))
        (total,) = _consultar(fonte, entradas, "<paginas>")
        marcas = _consultar(fonte, entradas, "<medida>")
    except typst.TypstError as exc:
        raise PdfFalhou((str(exc).strip().splitlines() or ["erro do Typst"])[0]) from exc
    medidas = sorted(
        ({"secao": m["secao"], "titulo": m["titulo"], "linhas": round(m["altura"] / PT_POR_LINHA)}
         for m in marcas),
        key=lambda m: -m["linhas"],
    )
    if total > paginas:
        raise PaginasDemais(total, paginas, medidas, destino)
    return {"paginas": total, "entradas": medidas}


def previa(estrutura: dict, ppi: int = 144) -> dict:
    """As páginas do mesmo PDF do download, como imagens PNG, e onde cada fato caiu nelas (marcas `<linha>`).
    Não confere o limite de páginas: a prévia mostra o que sairia, quem avisa do limite é a tela."""
    import typst

    fonte = TEMPLATE.read_bytes()
    entradas = {"dados": json.dumps(estrutura, ensure_ascii=False)}
    try:
        paginas = typst.compile(fonte, root=str(TEMPLATE.parent), font_paths=[str(FONTES)], ignore_system_fonts=True,
                                sys_inputs=entradas, format="png", ppi=ppi)
        (marcas,) = _consultar(fonte, entradas, "<previa>")
    except typst.TypstError as exc:
        raise PdfFalhou((str(exc).strip().splitlines() or ["erro do Typst"])[0]) from exc
    if isinstance(paginas, bytes):
        paginas = [paginas]
    return {"largura": marcas["largura"], "altura": marcas["altura"], "paginas": paginas, "linhas": marcas["linhas"]}
