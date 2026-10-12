"""Perfis de currículo: um vault, vários recortes, e a galeria de versões geradas."""

import json
from types import SimpleNamespace

import pytest

from hermes.domain import competencias, curriculo, perfis_cv
from hermes.domain import perfil as perfil_mod
from hermes.run_status import RunStatus

YAML = """perfis:
  - slug: dados
    cargo: {pt: "Engenharia de Dados", en: "Data Engineering"}
    foco: SQL e modelagem.
    competencias: {sql: 3}
    peso_fora_do_perfil: 0.5
    projetos: {primeiro: [], excluir: []}
    limite_fatos: 10
  - slug: sem-mirante
    cargo: {pt: "Qualquer", en: "Any"}
    competencias: {python: 1}
    projetos: {excluir: [mirante]}
"""


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(YAML, encoding="utf-8")
    return caminho


@pytest.fixture
def com_evidencias(banco):
    for slug, ref in (("python", "pipeline"), ("sql", "sql-ddl"), ("python", "testes")):
        competencias.ligar_evidencia(banco, slug, ref)
    competencias.avaliar(banco, "python", 2, "uso")
    competencias.avaliar(banco, "sql", 2, "uso")
    return banco


def test_carrega_os_perfis(arquivo):
    perfis = perfis_cv.carregar(arquivo)
    assert [p.slug for p in perfis] == ["dados", "sem-mirante"]
    assert perfis[0].cargo["en"] == "Data Engineering"
    assert perfis[1].limite_fatos == curriculo.MAX_FATOS  # padrão


def test_arquivo_ausente_e_lista_vazia(tmp_path):
    assert perfis_cv.carregar(tmp_path / "nao-existe.yaml") == []


@pytest.mark.parametrize("ruim", [
    "perfis:\n  - slug: x\n",                                    # sem cargo
    "perfis:\n  - slug: x\n    cargo: {pt: a}\n",                 # cargo sem en
    "perfis:\n  - {slug: x, cargo: {pt: a, en: b}}\n  - {slug: x, cargo: {pt: a, en: b}}\n",
])
def test_perfil_invalido_e_recusado(tmp_path, ruim):
    caminho = tmp_path / "c.yaml"
    caminho.write_text(ruim, encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido):
        perfis_cv.carregar(caminho)


def test_competencia_desconhecida_e_recusada(banco, arquivo, tmp_path):
    caminho = tmp_path / "c.yaml"
    caminho.write_text("perfis:\n  - {slug: x, cargo: {pt: a, en: b}, competencias: {cobol: 3}}\n",
                       encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match="cobol"):
        perfis_cv.validar(banco, perfis_cv.carregar(caminho))


def test_perfil_muda_o_peso_da_selecao(com_evidencias, arquivo):
    dados = perfis_cv.buscar(perfis_cv.carregar(arquivo), "dados")
    selecao = curriculo.selecionar(com_evidencias, perfil=dados)
    # sql vale 3 no perfil; python cai para peso 3 × 0.5 = 1.5
    assert selecao[0]["block_id"] == "sql-ddl"


def test_perfil_exclui_projeto(com_evidencias, arquivo):
    sem = perfis_cv.buscar(perfis_cv.carregar(arquivo), "sem-mirante")
    assert curriculo.selecionar(com_evidencias, perfil=sem) == []


# --- geração por perfil + galeria ------------------------------------------------


def _resposta(conteudo):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


@pytest.fixture
def provedor(mocker):
    import litellm

    mock = mocker.patch.object(litellm, "completion")
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    mock.return_value = _resposta('{"resumo": "r", "bullets": {}}')
    return mock


@pytest.fixture
def vault_com_perfil(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    return vault


def test_gerar_por_perfil_usa_o_cargo_do_perfil_e_grava_na_pasta_dele(
    com_evidencias, arquivo, vault_com_perfil, tmp_path, provedor
):
    dados = perfis_cv.buscar(perfis_cv.carregar(arquivo), "dados")
    r = curriculo.gerar(com_evidencias, vault_com_perfil, tmp_path / "out", RunStatus(),
                        perfil=dados)

    pt = (tmp_path / "out" / "dados" / "cv-pt.md").read_text(encoding="utf-8")
    en = (tmp_path / "out" / "dados" / "cv-en.md").read_text(encoding="utf-8")
    assert "**Engenharia de Dados**" in pt and "**Data Engineering**" in en
    assert all(not x["reaproveitado"] for x in r)
    # o foco do perfil chega ao modelo
    assert "SQL e modelagem." in provedor.call_args_list[0].kwargs["messages"][-1]["content"]


def test_mesma_selecao_nao_paga_de_novo(com_evidencias, arquivo, vault_com_perfil, tmp_path,
                                        provedor):
    dados = perfis_cv.buscar(perfis_cv.carregar(arquivo), "dados")
    curriculo.gerar(com_evidencias, vault_com_perfil, tmp_path / "out", RunStatus(), perfil=dados)
    status = RunStatus()
    r = curriculo.gerar(com_evidencias, vault_com_perfil, tmp_path / "out", status, perfil=dados)

    assert provedor.call_count == 2  # só a primeira geração chamou o modelo
    assert all(x["reaproveitado"] for x in r)
    assert status.llm_calls == 0

    curriculo.gerar(com_evidencias, vault_com_perfil, tmp_path / "out", RunStatus(),
                    perfil=dados, forcar=True)
    assert provedor.call_count == 4


def test_galeria_agrupa_por_perfil(com_evidencias, arquivo, vault_com_perfil, tmp_path, provedor):
    perfis = perfis_cv.carregar(arquivo)
    curriculo.gerar(com_evidencias, vault_com_perfil, tmp_path / "out", RunStatus(),
                    perfil=perfis_cv.buscar(perfis, "dados"))
    curriculo.gerar(com_evidencias, vault_com_perfil, tmp_path / "out", RunStatus())

    grupos = curriculo.galeria(com_evidencias, perfis)

    assert [g["perfil"] for g in grupos] == ["dados", "sem-mirante", None]
    dados = grupos[0]
    assert dados["titulo"] == "Melhores para vaga de Engenharia de Dados"
    assert {v["idioma"] for v in dados["versoes"]} == {"pt", "en"}
    pt = next(v for v in dados["versoes"] if v["idioma"] == "pt")
    assert "Engenharia de Dados" in pt["conteudo"]
    assert grupos[1]["versoes"] == []  # perfil sem build ainda aparece, vazio
    assert grupos[2]["titulo"] == "Currículo geral"
    assert json.loads(json.dumps(grupos))  # serializável para a API


# --- criar recorte pela tela (V3) ------------------------------------------------------

YAML_COM_COMENTARIOS = """# meus recortes, à mão
nomes:
  fastapi: FastAPI  # nome bonito

perfis:
  # o primeiro
  - slug: backend
    cargo: {pt: "Desenvolvedor Backend", en: "Backend Developer"}
    competencias: {python: 3}
"""


def test_criar_recorte_preserva_o_arquivo_e_acrescenta_no_fim(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(YAML_COM_COMENTARIOS, encoding="utf-8")
    p = perfis_cv.criar(caminho, banco, cargo_pt="Analista de Dados Júnior", cargo_en="Junior Data Analyst",
                        foco="SQL e Python para relatórios", competencias={"sql": 3, "python": 2}, limite_fatos=10)
    texto = caminho.read_text(encoding="utf-8")
    assert texto.startswith(YAML_COM_COMENTARIOS)  # nada do que você escreveu muda
    assert p.slug == "analista-de-dados-junior"
    todos = perfis_cv.carregar(caminho)
    assert [x.slug for x in todos] == ["backend", "analista-de-dados-junior"]
    assert todos[1].cargo == {"pt": "Analista de Dados Júnior", "en": "Junior Data Analyst"}
    assert todos[1].competencias == {"sql": 3.0, "python": 2.0} and todos[1].limite_fatos == 10
    assert perfis_cv.carregar_nomes(caminho) == {"fastapi": "FastAPI"}


def test_slug_repetido_ganha_numero(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(YAML_COM_COMENTARIOS, encoding="utf-8")
    assert perfis_cv.criar(caminho, banco, cargo_pt="Backend", cargo_en="Backend", competencias={"python": 2}).slug == "backend-2"


def test_recorte_invalido_nao_toca_no_arquivo(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(YAML_COM_COMENTARIOS, encoding="utf-8")
    antes = caminho.read_bytes()
    for erro, kwargs in [
        ("competência", {"competencias": {"cobol": 2}}),
        ("peso", {"competencias": {"sql": 5}}),
        ("cargo", {"cargo_pt": "  "}),
        ("limite", {"limite_fatos": 99}),
        ("páginas", {"paginas": 3}),
    ]:
        args = {"cargo_pt": "Dados", "cargo_en": "Data", "competencias": {"sql": 2}, **kwargs}
        with pytest.raises(perfis_cv.PerfilInvalido, match=erro):
            perfis_cv.criar(caminho, banco, **args)
        assert caminho.read_bytes() == antes


def test_sem_arquivo_cria_um_valido(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    assert [p.slug for p in perfis_cv.carregar(caminho)] == ["dados"]


def test_perfis_antes_de_outra_chave_de_topo(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("perfis:\n  - slug: backend\n    cargo: {pt: B, en: B}\n\nnomes:\n  sql: SQL\n", encoding="utf-8")
    perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    assert [p.slug for p in perfis_cv.carregar(caminho)] == ["backend", "dados"]
    assert perfis_cv.carregar_nomes(caminho) == {"sql": "SQL"}


def test_sem_curriculos_yaml_a_galeria_tem_o_recorte_geral(banco):
    """Primeiro dia: quem instala não tem curriculos.yaml; a tela abre com o recorte Geral, não vazia."""
    grupos = curriculo.galeria(banco, [])
    assert [(g["perfil"], g["titulo"], g["versoes"]) for g in grupos] == [(None, "Geral", [])]


def test_com_recortes_e_sem_versao_geral_o_geral_nao_aparece(banco):
    perfil = perfis_cv.PerfilCV(slug="backend", cargo={"pt": "Backend", "en": "Backend"})
    assert [g["perfil"] for g in curriculo.galeria(banco, [perfil])] == ["backend"]


@pytest.mark.parametrize("conteudo", [
    "perfis: [{slug: backend, cargo: {pt: B, en: B}}]\n",                      # estilo fluxo numa linha
    "perfis: [\n  {slug: backend, cargo: {pt: B, en: B}}\n]\n",                 # fluxo em várias linhas
    "﻿perfis:\n  - slug: backend\n    cargo: {pt: B, en: B}\n",           # BOM de editor do Windows
    '"perfis":\n  - slug: backend\n    cargo: {pt: B, en: B}\n',               # chave entre aspas
])
def test_layout_que_o_inseridor_nao_entende_recusa_sem_tocar_no_arquivo(banco, tmp_path, conteudo):
    """Review: nunca esconder os recortes que já existem. Ou mantém todos e acrescenta, ou recusa intacto."""
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    antes = caminho.read_bytes()
    try:
        perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    except perfis_cv.PerfilInvalido:
        assert caminho.read_bytes() == antes
    else:
        assert [p.slug for p in perfis_cv.carregar(caminho)] == ["backend", "dados"]


def test_itens_na_coluna_zero_sao_aceitos(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("perfis:\n- slug: backend\n  cargo: {pt: B, en: B}\nnomes:\n  sql: SQL\n", encoding="utf-8")
    perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    assert [p.slug for p in perfis_cv.carregar(caminho)] == ["backend", "dados"]
    assert perfis_cv.carregar_nomes(caminho) == {"sql": "SQL"}


def test_yaml_quebrado_vira_recusa_clara(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("perfis:\n\t- slug: backend\n", encoding="utf-8")
    antes = caminho.read_bytes()
    with pytest.raises(perfis_cv.PerfilInvalido, match="não abre"):
        perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    assert caminho.read_bytes() == antes


def test_yaml_quebrado_e_recusa_com_o_nome_do_arquivo(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("perfis:\n  - slug: a\n   cargo: [", encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match="curriculos.yaml não abre"):
        perfis_cv.carregar(caminho)
    with pytest.raises(perfis_cv.PerfilInvalido, match="curriculos.yaml não abre"):
        perfis_cv.carregar_nomes(caminho)


def test_item_que_nao_e_mapa_e_recusa(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("perfis:\n  - so-um-texto\n", encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match="perfil #1"):
        perfis_cv.carregar(caminho)


@pytest.mark.parametrize("conteudo, trecho", [
    ("perfis:\n  - slug: a\n    cargo: {pt: A, en: A}\n    competencias:\n      - python\n", "competencias"),
    ("perfis:\n  - slug: a\n    cargo: {pt: A, en: A}\n    projetos:\n      - x\n", "projetos"),
    ("perfis:\n  - slug: a\n    cargo: {pt: A, en: A}\n    habilidades:\n      - Backend\n", "habilidades"),
])
def test_valor_aninhado_fora_do_formato_e_recusa(tmp_path, conteudo, trecho):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match=trecho):
        perfis_cv.carregar(caminho)


def test_nomes_como_lista_e_recusa(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("nomes:\n  - fastapi\n", encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match="nomes"):
        perfis_cv.carregar_nomes(caminho)


def test_item_que_nao_e_mapa_diz_o_arquivo(tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text("perfis:\n  - texto solto\n", encoding="utf-8")
    with pytest.raises(perfis_cv.PerfilInvalido, match=r"curriculos\.yaml: perfil #1 não é um item"):
        perfis_cv.carregar(caminho)


def test_falha_depois_de_inserir_cita_o_arquivo_real(banco, tmp_path, monkeypatch):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_text(YAML_COM_COMENTARIOS, encoding="utf-8")
    monkeypatch.setattr(perfis_cv, "_inserir_no_bloco", lambda texto, bloco: texto + "\n: [quebrado\n")
    with pytest.raises(perfis_cv.PerfilInvalido) as exc:
        perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    assert "curriculos.yaml" in str(exc.value) and ".curriculos-" not in str(exc.value)
    assert caminho.read_text(encoding="utf-8") == YAML_COM_COMENTARIOS


def test_criar_preserva_crlf(banco, tmp_path):
    caminho = tmp_path / "curriculos.yaml"
    caminho.write_bytes(YAML_COM_COMENTARIOS.replace("\n", "\r\n").encode("utf-8"))
    perfis_cv.criar(caminho, banco, cargo_pt="Dados", cargo_en="Data", competencias={"sql": 2})
    bruto = caminho.read_bytes()
    assert b"\r\n" in bruto and bruto.count(b"\n") == bruto.count(b"\r\n")
