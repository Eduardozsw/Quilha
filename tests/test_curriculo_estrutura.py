"""Fase 9.2: a estrutura intermediária do currículo, os cabeçalhos completos e as habilidades."""

import json

import pytest

from hermes.domain import competencias, curriculo, perfis_cv
from hermes.domain import perfil as perfil_mod
from hermes.run_status import RunStatus
from hermes.vault.check import check_habilidades
from hermes.vault.reader import read_notes

ACME = """---
type: experience
id: acme
empresa: Acme
cargo: Estagiário de Engenharia de Software
inicio: 2026-08
fim: atual
local: Campinas, SP
stack: [java, spring-boot]
---

# Acme

## Fatos

- Integrou o módulo de cobrança a uma API externa (Java, Spring Boot) #java ^assinatura
"""

FAROL = """---
type: experience
id: farol
empresa: Farol
cargo: Estagiário
inicio: 2025-08
fim: 2025-12
stack: [go]
---

# Farol

## Fatos

- API REST em Go com JWT #go ^api-go
"""

MIRANTE = """---
type: project
id: mirante
nome: Mirante
subtitulo: {pt: "pipeline diário de notícias", en: "daily news pipeline"}
stack: [python, sqlite, github-actions]
link: https://github.com/fulano/mirante
inicio: 2026-06
---

# Mirante

## Fatos

- Pipeline batch diário em Python que coleta feeds RSS #python #automacao ^pipeline
"""

SEED = """competencias:
  - {slug: python, nome: Python, categoria: linguagem, peso: 3}
  - {slug: java, nome: Java, categoria: linguagem, peso: 3}
  - {slug: go, nome: Go, categoria: linguagem, peso: 2}
"""

YAML = """nomes:
  python: Python
  sqlite: SQLite
  github-actions: GitHub Actions
perfis:
  - slug: backend
    cargo: {pt: "Engenheiro Backend", en: "Backend Engineer"}
    competencias: {java: 3, python: 3, go: 2}
    habilidades:
      - rotulo: {pt: "Backend", en: "Core Backend"}
        itens: [Java (Spring Boot), Python]
      - rotulo: {pt: "Bancos", en: "Databases"}
        itens: [SQLite, PyTorch]
"""


@pytest.fixture
def vault_completo(tmp_path):
    raiz = tmp_path / "vault"
    for pasta, nome, texto in (
        ("Experiencias", "Acme.md", ACME),
        ("Experiencias", "Farol.md", FAROL),
        ("Projetos", "Mirante.md", MIRANTE),
    ):
        (raiz / "Carreira" / pasta).mkdir(parents=True, exist_ok=True)
        (raiz / "Carreira" / pasta / nome).write_text(texto, encoding="utf-8")
    (raiz / perfil_mod.ARQUIVO).write_text(
        "---\nnome: Fulano\nemail: f@x.com\ngithub: https://github.com/fulano\n"
        "idiomas: [Português (nativo)]\n---\n", encoding="utf-8")
    return raiz


@pytest.fixture
def banco_completo(conn, vault_completo, tmp_path):
    from hermes.db import store

    store.reindex_facts(conn, [
        {"nota": n.nota, "block_id": f.block_id, "tipo": n.tipo, "entidade": n.entidade,
         "texto": f.texto, "tags": f.tags}
        for n in read_notes(vault_completo) for f in n.facts
    ])
    seed = tmp_path / "competencias.yaml"
    seed.write_text(SEED, encoding="utf-8")
    competencias.seed(conn, seed)
    # Farol é a evidência mais forte: a ordem por força a poria antes da Acme
    for slug, ref, forca in (("go", "api-go", 3), ("java", "assinatura", 1), ("python", "pipeline", 2)):
        competencias.ligar_evidencia(conn, slug, ref, forca=forca)
        competencias.avaliar(conn, slug, 2, "uso")
    return conn


@pytest.fixture
def perfil_backend(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(YAML, encoding="utf-8")
    return caminho


VAZIO = {"resumo": "", "bullets": {}}


def _estrutura(conn, vault, idioma="pt", perfil=None, nomes=None):
    selecao = curriculo.selecionar(conn)
    return curriculo.estruturar(
        {"nome": "Fulano", "cargo_alvo": "Backend"}, selecao, VAZIO, idioma,
        entidades=curriculo._entidades(vault), perfil_cv=perfil, nomes=nomes,
    )


# -------------------------------------------------------------------- período


@pytest.mark.parametrize("inicio, fim, idioma, esperado", [
    ("2026-08", "atual", "pt", "08/2026 – Atual"),
    ("2026-08", "atual", "en", "08/2026 – Present"),
    ("2025-08", "2025-12", "pt", "08/2025 – 12/2025"),
    ("2026-06", None, "pt", "06/2026"),
    (None, None, "pt", ""),
])
def test_periodo(inicio, fim, idioma, esperado):
    assert curriculo.periodo(inicio, fim, idioma) == esperado


def test_yaml_le_a_data_sem_aspas_como_texto():
    """`inicio: 2026-08` sem aspas chega como str; `2026-08-01` chegaria como date."""
    import datetime

    assert curriculo.periodo(datetime.date(2026, 8, 1), "atual", "pt") == "08/2026 – Atual"


# -------------------------------------------------------------------- cabeçalhos


def test_experiencia_traz_cargo_periodo_e_local(banco_completo, vault_completo):
    estrutura = _estrutura(banco_completo, vault_completo)
    acme = next(e for e in estrutura["experiencias"] if e["entidade"] == "acme")
    assert acme["titulo"] == "Acme"
    assert acme["cargo"] == "Estagiário de Engenharia de Software"
    assert acme["periodo"] == "08/2026 – Atual"
    assert acme["local"] == "Campinas, SP"


def test_experiencias_saem_da_mais_recente_para_a_mais_antiga(banco_completo, vault_completo):
    """Na seleção a Farol vem antes (evidência mais forte); no currículo manda a data."""
    estrutura = _estrutura(banco_completo, vault_completo)
    assert [e["entidade"] for e in estrutura["experiencias"]] == ["acme", "farol"]


def test_projeto_traz_link_subtitulo_e_stack_com_nome_de_exibicao(banco_completo, vault_completo):
    nomes = {"python": "Python", "sqlite": "SQLite"}
    (projeto,) = _estrutura(banco_completo, vault_completo, "en", nomes=nomes)["projetos"]
    assert projeto["link"] == "https://github.com/fulano/mirante"
    assert projeto["subtitulo"] == "daily news pipeline"
    # slug sem nome de exibição aparece como veio: melhor feio que sumido
    assert projeto["stack"] == ["Python", "SQLite", "github-actions"]


def test_todo_bullet_da_estrutura_carrega_a_origem(banco_completo, vault_completo):
    estrutura = _estrutura(banco_completo, vault_completo)
    bullets = [b for secao in ("experiencias", "projetos") for e in estrutura[secao]
               for b in e["bullets"]]
    assert {b["origem"] for b in bullets} == {
        f["origem"] for f in curriculo.selecionar(banco_completo)}


def test_contato_mostra_o_link_sem_protocolo(banco_completo, vault_completo):
    perfil = perfil_mod.carregar(vault_completo)
    estrutura = curriculo.estruturar(perfil, curriculo.selecionar(banco_completo), VAZIO, "pt")
    assert {"texto": "github.com/fulano", "url": "https://github.com/fulano"} in estrutura["contato"]
    assert {"texto": "f@x.com", "url": "mailto:f@x.com"} in estrutura["contato"]


def test_markdown_mostra_cargo_periodo_e_link(banco_completo, vault_completo):
    markdown = curriculo.para_markdown(_estrutura(banco_completo, vault_completo))
    assert "### Acme — Estagiário de Engenharia de Software" in markdown
    assert "*08/2026 – Atual · Campinas, SP*" in markdown
    assert "### [Mirante](https://github.com/fulano/mirante) — pipeline diário de notícias" in markdown


# -------------------------------------------------------------------- habilidades


def test_habilidades_vem_do_perfil_no_idioma_pedido(banco_completo, vault_completo, perfil_backend):
    (perfil,) = perfis_cv.carregar(perfil_backend)
    estrutura = _estrutura(banco_completo, vault_completo, "en", perfil=perfil)
    assert estrutura["habilidades"][0] == {"rotulo": "Core Backend", "itens": ["Java (Spring Boot)", "Python"]}
    assert "**Core Backend:** Java (Spring Boot), Python" in curriculo.para_markdown(estrutura)


def test_item_de_habilidade_pode_ter_traducao(banco_completo, vault_completo, tmp_path):
    caminho = tmp_path / "c.yaml"
    caminho.write_text(
        "perfis:\n  - slug: x\n    cargo: {pt: a, en: b}\n    habilidades:\n"
        "      - rotulo: {pt: IA, en: AI}\n"
        "        itens: [RAG, {pt: busca híbrida, en: hybrid search}]\n", encoding="utf-8")
    (perfil,) = perfis_cv.carregar(caminho)
    en = _estrutura(banco_completo, vault_completo, "en", perfil=perfil)
    assert en["habilidades"] == [{"rotulo": "AI", "itens": ["RAG", "hybrid search"]}]


def test_sem_habilidades_no_perfil_cai_nas_competencias_prontas(banco_completo, vault_completo):
    prontas = [{"nome": "Python"}, {"nome": "Go"}]
    estrutura = curriculo.estruturar({"nome": "F"}, curriculo.selecionar(banco_completo), VAZIO,
                                     "pt", prontas)
    assert estrutura["habilidades"] == [{"rotulo": "", "itens": ["Python", "Go"]}]


def test_nomes_de_exibicao_vem_do_yaml(perfil_backend):
    assert perfis_cv.carregar_nomes(perfil_backend)["github-actions"] == "GitHub Actions"


def test_habilidade_sem_itens_e_erro(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(
        "perfis:\n  - slug: x\n    cargo: {pt: a, en: b}\n"
        "    habilidades:\n      - rotulo: {pt: A, en: B}\n", encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match="itens"):
        perfis_cv.carregar(caminho)


def test_check_avisa_habilidade_que_nenhuma_nota_sustenta(vault_completo, perfil_backend):
    """Declaração não é fato: PyTorch sem projeto nenhum vira aviso. Java (Spring Boot) passa."""
    problemas = check_habilidades(perfis_cv.carregar(perfil_backend), read_notes(vault_completo))
    assert [p.nivel for p in problemas] == ["aviso"]
    assert "PyTorch" in problemas[0].mensagem and "backend" in problemas[0].nota


def test_tag_de_fato_tambem_sustenta_habilidade(vault_completo, tmp_path):
    caminho = tmp_path / "c.yaml"
    caminho.write_text(
        "perfis:\n  - slug: x\n    cargo: {pt: a, en: b}\n"
        "    habilidades:\n      - rotulo: {pt: A, en: B}\n        itens: [Automação]\n",
        encoding="utf-8")
    # a tag é #automacao, sem acento: a comparação ignora acento e caixa
    assert check_habilidades(perfis_cv.carregar(caminho), read_notes(vault_completo)) == []


# -------------------------------------------------------------------- gerar


def test_gerar_grava_o_json_ao_lado_do_markdown(banco_completo, vault_completo, tmp_path, mocker):
    mocker.patch.object(curriculo, "redigir", return_value={"resumo": "R.", "bullets": {}})
    (r,) = curriculo.gerar(banco_completo, vault_completo, tmp_path / "out", RunStatus(),
                           idiomas=("pt",))
    dados = json.loads((tmp_path / "out" / "cv-pt.json").read_text(encoding="utf-8"))
    assert dados == r["estrutura"]
    assert dados["resumo"] == "R."


def test_reaproveitar_reconstroi_com_o_cabecalho_novo_sem_chamar_o_modelo(
    banco_completo, vault_completo, tmp_path, mocker
):
    """A redação fica guardada; cargo e datas vêm do vault a cada geração, de graça."""
    redigir = mocker.patch.object(curriculo, "redigir", return_value={"resumo": "R.", "bullets": {}})
    curriculo.gerar(banco_completo, vault_completo, tmp_path / "out", RunStatus(), idiomas=("pt",))

    nota = vault_completo / "Carreira" / "Experiencias" / "Acme.md"
    nota.write_text(nota.read_text(encoding="utf-8").replace("local: Campinas, SP", "local: Curitiba, PR"),
                    encoding="utf-8")
    (r,) = curriculo.gerar(banco_completo, vault_completo, tmp_path / "out", RunStatus(), idiomas=("pt",))

    assert redigir.call_count == 1
    assert r["reaproveitado"]
    assert "Curitiba, PR" in (tmp_path / "out" / "cv-pt.md").read_text(encoding="utf-8")
    assert r["estrutura"]["resumo"] == "R."
    guardado = banco_completo.execute("SELECT conteudo FROM cv_versions").fetchone()["conteudo"]
    assert "Curitiba, PR" in guardado  # a galeria mostra o que foi para o arquivo


def test_versao_antiga_sem_redacao_guardada_e_redigida_de_novo(
    banco_completo, vault_completo, tmp_path, mocker
):
    redigir = mocker.patch.object(curriculo, "redigir", return_value={"resumo": "R.", "bullets": {}})
    curriculo.gerar(banco_completo, vault_completo, tmp_path / "out", RunStatus(), idiomas=("pt",))
    banco_completo.execute("UPDATE cv_versions SET redacao = NULL")
    curriculo.gerar(banco_completo, vault_completo, tmp_path / "out", RunStatus(), idiomas=("pt",))
    assert redigir.call_count == 2


def test_perfil_define_o_limite_de_paginas(tmp_path):
    caminho = tmp_path / "c.yaml"
    caminho.write_text("perfis:\n  - slug: a\n    cargo: {pt: a, en: a}\n    paginas: 2\n"
                       "  - slug: b\n    cargo: {pt: b, en: b}\n", encoding="utf-8")
    assert [p.paginas for p in perfis_cv.carregar(caminho)] == [2, 1]
