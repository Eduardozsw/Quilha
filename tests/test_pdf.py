"""Fase 9.3: PDF do currículo com Typst e a checagem de páginas."""

from pathlib import Path

import pytest

from hermes.domain import curriculo, pdf


def _estrutura(bullets_por_entrada=2, texto="Construiu um pipeline diário em Python com N=57 execuções."):
    def entrada(entidade, titulo, **extra):
        return {"entidade": entidade, "titulo": titulo, "subtitulo": "", "cargo": "", "periodo": "",
                "local": "", "stack": [], "link": None,
                "bullets": [{"texto": texto, "origem": f"^b{i} @ X.md", "referencia": f"X.md#b{i}"}
                            for i in range(bullets_por_entrada)], **extra}

    return {
        "idioma": "pt", "rotulos": curriculo.SECOES["pt"], "nome": "Fulano de Tal",
        "cargo": "Engenheiro Backend",
        "contato": [{"texto": "f@x.com", "url": "mailto:f@x.com"},
                    {"texto": "github.com/fulano", "url": "https://github.com/fulano"}],
        "idiomas": ["Português (nativo)"], "resumo": "Resumo curto.",
        "experiencias": [entrada("acme", "Acme", cargo="Estagiário", periodo="08/2026 – Atual")],
        "projetos": [entrada("mirante", "Mirante", subtitulo="pipeline de notícias",
                             stack=["Python", "SQLite"], link="https://github.com/x/mirante")],
        "habilidades": [{"rotulo": "Backend", "itens": ["Python (FastAPI)", "Java"]}],
        "formacao": [{"curso": "Ciência da Computação", "instituicao": "UNIPÊ", "periodo": "02/2025 – 12/2028"}],
    }


def test_estrutura_curta_vira_pdf_de_uma_pagina(tmp_path):
    destino = tmp_path / "cv-pt.pdf"
    resultado = pdf.compilar(_estrutura(), destino)
    assert destino.read_bytes().startswith(b"%PDF")
    assert resultado["paginas"] == 1
    assert {e["titulo"] for e in resultado["entradas"]} == {"Acme", "Mirante"}


def test_passou_do_limite_falha_e_aponta_o_que_ocupa_mais(tmp_path):
    estrutura = _estrutura(bullets_por_entrada=3)
    estrutura["projetos"][0]["bullets"] *= 20  # o Mirante é o culpado
    destino = tmp_path / "cv-pt.pdf"

    with pytest.raises(pdf.PaginasDemais) as exc:
        pdf.compilar(estrutura, destino, paginas=1)

    assert exc.value.paginas >= 2
    assert exc.value.entradas[0]["titulo"] == "Mirante"
    assert exc.value.entradas[0]["linhas"] > exc.value.entradas[-1]["linhas"]
    assert "Mirante" in str(exc.value)
    assert destino.is_file()  # o PDF fica para você ver o que passou; cortar é decisão sua


def test_texto_com_caractere_especial_do_typst_nao_quebra(tmp_path):
    """O texto chega como dado (JSON), não como marcação: `#`, `*`, `$` e `_` saem literais."""
    estrutura = _estrutura(texto="Reduziu custo a US$ 2,41 *por* 1.000 consultas #rag em snake_case @x")
    resultado = pdf.compilar(estrutura, tmp_path / "cv.pdf")
    assert resultado["paginas"] == 1


def test_usa_a_fonte_do_projeto_e_nao_a_do_sistema(tmp_path):
    destino = tmp_path / "cv.pdf"
    pdf.compilar(_estrutura(), destino)
    assert b"XCharter" in destino.read_bytes()  # nome da fonte embutida, no dicionário do PDF


def test_linhas_estimadas_batem_com_o_que_se_ve(tmp_path):
    """Experiência: cargo/data + empresa + 3 bullets de uma linha = 5. Projeto: título + 3 = 4."""
    resultado = pdf.compilar(_estrutura(bullets_por_entrada=3), tmp_path / "cv.pdf")
    linhas = {e["titulo"]: e["linhas"] for e in resultado["entradas"]}
    assert linhas == {"Acme": 5, "Mirante": 4}


def test_erro_do_typst_vira_pdf_falhou(monkeypatch, tmp_path):
    import typst

    def quebra(*a, **k):
        raise typst.TypstError("expected expression")

    monkeypatch.setattr(typst, "compile", quebra)
    with pytest.raises(pdf.PdfFalhou, match="expected expression"):
        pdf.compilar(_estrutura(), tmp_path / "x.pdf", 1)


# --- prévia: as páginas do mesmo PDF, com a posição de cada fato ---------------------------------------

# o template de antes das marcas `<linha>`, congelado: as duas versões renderizam no mesmo Typst, então a
# comparação não quebra quando o Typst atualiza (hash fixo de PNG quebrava)
SEM_MARCAS = Path(__file__).parent / "fixtures" / "cv" / "cv-sem-marcas.typ"


def _paginas(fonte: bytes, estrutura) -> list[bytes]:
    import json

    import typst

    p = typst.compile(fonte, root=str(pdf.TEMPLATE.parent), font_paths=[str(pdf.FONTES)], ignore_system_fonts=True,
                      sys_inputs={"dados": json.dumps(estrutura, ensure_ascii=False)}, format="png", ppi=72)
    return [p] if isinstance(p, bytes) else p


@pytest.mark.parametrize("n", [2, 30])
def test_marcas_nao_mudam_as_paginas(n):
    estrutura = _estrutura(bullets_por_entrada=n)
    assert _paginas(pdf.TEMPLATE.read_bytes(), estrutura) == _paginas(SEM_MARCAS.read_bytes(), estrutura)


def test_previa_tem_as_mesmas_paginas_do_pdf(tmp_path):
    estrutura = _estrutura(bullets_por_entrada=30)
    feito = pdf.compilar(estrutura, tmp_path / "cv.pdf", 2)
    previa = pdf.previa(estrutura)
    assert len(previa["paginas"]) == feito["paginas"] == 2
    assert all(p.startswith(b"\x89PNG") for p in previa["paginas"])


def test_previa_marca_uma_linha_por_fato():
    estrutura = _estrutura(bullets_por_entrada=60)
    previa = pdf.previa(estrutura)
    refs = [b["referencia"] for secao in ("experiencias", "projetos") for e in estrutura[secao] for b in e["bullets"]]
    assert [l["ref"] for l in previa["linhas"]] == refs
    assert {l["pagina"] for l in previa["linhas"]} >= {1, 2}  # fato depois da quebra marca a página certa
    for l in previa["linhas"]:
        assert 0 < l["x"] < previa["largura"] and 0 < l["y"] < previa["altura"]
        assert l["w"] > 0 and l["h"] > 0 and l["x"] + l["w"] <= previa["largura"]


def test_previa_com_typst_quebrado_vira_pdf_falhou(monkeypatch):
    import typst

    def quebra(*a, **k):
        raise typst.TypstError("expected expression")

    monkeypatch.setattr(typst, "compile", quebra)
    with pytest.raises(pdf.PdfFalhou):
        pdf.previa(_estrutura())
