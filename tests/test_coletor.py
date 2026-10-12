"""Coletor: fila com backoff entre execuções, robots.txt, dedup e uma linha por fonte em `coletas`.

Toda a rede é um roteador falso de URL: nenhum teste sai da máquina.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hermes.domain import coletor
from hermes.run_status import RunStatus

GH_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/beta?mode=json"

GREENHOUSE = {
    "jobs": [
        {"id": 1, "title": "Automation Engineer (Júnior)", "absolute_url": "https://acme.test/1",
         "location": {"name": "Remote"},
         "content": "&lt;p&gt;Build RPA flows in Python.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;"},
        {"id": 2, "title": "Senior Automation Engineer", "absolute_url": "https://acme.test/2",
         "location": {"name": "Remote"}, "content": "&lt;p&gt;Lead the team.&lt;/p&gt;"},
        {"id": 3, "title": "Account Executive", "absolute_url": "https://acme.test/3",
         "location": {"name": "SP"}, "content": "&lt;p&gt;Sell.&lt;/p&gt;"},
    ]
}

LEVER = [
    {"text": "Integration Developer", "hostedUrl": "https://jobs.lever.co/beta/1",
     "categories": {"location": "São Paulo"}, "descriptionPlain": "Integrate EHR systems.",
     "lists": [{"text": "Requirements", "content": "<li>APIs REST</li><li>Python</li>"}],
     "additionalPlain": "Remote friendly."},
]


class Rede:
    """Roteador de URL → resposta. Cada chamada fica registrada em `chamadas`."""

    def __init__(self):
        self.rotas = {}
        self.chamadas = []

    def __call__(self, url, **_):
        self.chamadas.append(url)
        resposta = self.rotas.get(url, (404, ""))
        if isinstance(resposta, Exception):
            raise resposta
        if isinstance(resposta, list):  # sequência: uma resposta por chamada
            resposta = resposta.pop(0) if len(resposta) > 1 else resposta[0]
        codigo, corpo = resposta
        texto = corpo if isinstance(corpo, str) else json.dumps(corpo)
        return httpx.Response(codigo, text=texto, request=httpx.Request("GET", url))


@pytest.fixture
def rede(mocker):
    mocker.patch("time.sleep")  # backoff do tenacity sem esperar
    r = Rede()
    r.rotas[GH_URL] = (200, GREENHOUSE)
    r.rotas[LEVER_URL] = (200, LEVER)
    mocker.patch.object(httpx, "get", side_effect=r)
    return r


FILTRO = coletor._termos(["automation", "integration"]), coletor._termos(["senior"])
ACME = coletor.Fonte("greenhouse", "acme", "Acme", incluir=FILTRO[0], excluir=FILTRO[1])
BETA = coletor.Fonte("lever", "beta", "Beta", intervalo_h=12)


def _coletar(conn, fontes, forcar=False, status=None):
    return coletor.coletar(conn, fontes, "2026-09-22T12:00:00+00:00", status or RunStatus(), forcar)


# -------------------------------------------------------------------- config


def test_carrega_fontes_com_filtro_global_e_proprio(tmp_path):
    caminho = tmp_path / "fontes.yaml"
    caminho.write_text(
        "filtro: {incluir: [Automação], excluir: [Sênior]}\n"
        "fontes:\n"
        "  - {tipo: greenhouse, board: acme, empresa: Acme}\n"
        "  - {tipo: lever, board: beta, intervalo_h: 6, filtro: {incluir: []}}\n",
        encoding="utf-8",
    )
    acme, beta = coletor.carregar_fontes(caminho)
    assert (acme.incluir, acme.excluir) == (("automacao",), ("senior",))
    assert beta.incluir == () and beta.intervalo_h == 6 and beta.empresa == "beta"


@pytest.mark.parametrize("conteudo, erro", [
    ("fontes:\n  - {tipo: workday, board: x}\n", "`tipo`"),
    ("fontes:\n  - {tipo: lever, board: 'a/b'}\n", "`board` inválido"),
    ("fontes:\n  - {tipo: lever, board: a}\n  - {tipo: lever, board: a}\n", "repetida"),
    ("fontes:\n  - {tipo: lever, board: a, intervalo_h: 0}\n", "intervalo_h"),
])
def test_config_invalida_recusa(tmp_path, conteudo, erro):
    caminho = tmp_path / "fontes.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(coletor.ColetaRecusada, match=erro):
        coletor.carregar_fontes(caminho)


def test_sem_fontes_yaml_explica_o_exemplo(tmp_path):
    with pytest.raises(coletor.ColetaRecusada, match="fontes.example.yaml"):
        coletor.carregar_fontes(tmp_path / "fontes.yaml")


# ---------------------------------------------------------------- normalização


def test_filtro_ignora_acento_e_caixa():
    assert coletor.passa_no_filtro("Automation Engineer (Júnior)", ACME)
    assert not coletor.passa_no_filtro("SENIOR Automation Engineer", ACME)
    assert not coletor.passa_no_filtro("Account Executive", ACME)
    assert coletor.passa_no_filtro("Qualquer coisa", BETA)  # sem `incluir`, aceita tudo


def test_greenhouse_desescapa_o_html():
    vagas = coletor.normalizar_resposta("greenhouse", json.dumps(GREENHOUSE))
    assert vagas[0]["texto"] == "Build RPA flows in Python.\n- SQL"
    assert vagas[0]["local"] == "Remote"


def test_lever_junta_descricao_listas_e_adicional():
    (v,) = coletor.normalizar_resposta("lever", json.dumps(LEVER))
    assert v["texto"].splitlines() == [
        "Integrate EHR systems.", "Requirements", "- APIs REST", "- Python", "Remote friendly."]


@pytest.mark.parametrize("fonte, corpo", [("greenhouse", "[]"), ("lever", "{}"), ("lever", "<html>")])
def test_formato_inesperado_e_erro_nao_lista_vazia(fonte, corpo):
    with pytest.raises(ValueError):
        coletor.normalizar_resposta(fonte, corpo)


# -------------------------------------------------------------------- coleta


def test_coleta_grava_vagas_filtradas_sem_requisitos(banco, rede):
    r = _coletar(banco, [ACME, BETA])

    assert (r["processadas"], r["ok"], r["vagas_novas"]) == (2, 2, 2)
    acme = next(c for c in r["resultados"] if c["board"] == "acme")
    assert (acme["vagas_vistas"], acme["vagas_filtradas"], acme["vagas_novas"]) == (3, 1, 1)

    jobs = banco.execute("SELECT empresa, titulo, fonte, status FROM jobs ORDER BY id").fetchall()
    assert [tuple(j) for j in jobs] == [
        ("Acme", "Automation Engineer (Júnior)", "greenhouse", "novo"),
        ("Beta", "Integration Developer", "lever", "novo"),
    ]
    # extração adiada: coletar não gasta crédito
    assert banco.execute("SELECT COUNT(*) FROM job_requirements").fetchone()[0] == 0
    assert banco.execute("SELECT COUNT(*) FROM coletas").fetchone()[0] == 2


def test_fonte_recem_coletada_espera_o_intervalo(banco, rede):
    _coletar(banco, [ACME, BETA])
    segunda = _coletar(banco, [ACME, BETA])
    assert (segunda["processadas"], segunda["adiadas"]) == (0, 2)

    fila = {f["board"]: f for f in coletor.fila(banco)}
    proximo = datetime.fromisoformat(fila["beta"]["proximo_em"])
    faltam = proximo - datetime.now(timezone.utc)
    assert timedelta(hours=11, minutes=58) < faltam <= timedelta(hours=12)


def test_forcar_coleta_de_novo_e_deduplica(banco, rede):
    _coletar(banco, [ACME])
    r = _coletar(banco, [ACME], forcar=True)
    (acme,) = r["resultados"]
    assert (acme["vagas_novas"], acme["duplicadas"]) == (0, 1)
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_vaga_colada_antes_nao_duplica_na_coleta(banco, rede):
    """Mesma vaga que você colou (mesmo texto) não entra de novo pelo coletor."""
    from hermes.db import store
    from hermes.domain import vaga

    texto = "Build RPA flows in Python.\n- SQL"
    with banco:
        banco.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Acme', 'Colada', 'colado', ?, ?, ?)",
            (texto, vaga.hash_texto(texto), store.utcnow()),
        )
    (acme,) = _coletar(banco, [ACME])["resultados"]
    assert (acme["vagas_novas"], acme["duplicadas"]) == (0, 1)


# ------------------------------------------------------------- falha e backoff


def test_backoff_dobra_ate_o_teto():
    assert [coletor.backoff(n) for n in (1, 2, 3)] == [
        timedelta(minutes=15), timedelta(minutes=30), timedelta(hours=1)]
    assert coletor.backoff(20) == timedelta(hours=12)


def test_falha_de_rede_vira_linha_falhou_e_backoff(banco, rede):
    rede.rotas[GH_URL] = (503, "fora do ar")
    status = RunStatus()
    r = _coletar(banco, [ACME, BETA], status=status)

    acme = next(c for c in r["resultados"] if c["board"] == "acme")
    assert acme["status"] == "falhou"
    assert acme["vagas_novas"] is None  # desconhecido, não zero
    assert r["ok"] == 1  # a Lever seguiu mesmo com a Greenhouse fora
    assert rede.chamadas.count(GH_URL) == 3  # 1 + 2 retries dentro da execução
    assert any("acme" in a for a in status.warnings)

    fila = {f["board"]: f for f in coletor.fila(banco)}
    assert (fila["acme"]["estado"], fila["acme"]["tentativas"]) == ("falhou", 1)
    espera = datetime.fromisoformat(fila["acme"]["proximo_em"]) - datetime.now(timezone.utc)
    assert timedelta(minutes=14) < espera <= timedelta(minutes=15)

    linha = banco.execute("SELECT status, vagas_vistas, erro FROM coletas WHERE board='acme'").fetchone()
    assert (linha["status"], linha["vagas_vistas"]) == ("falhou", None)


def test_falhas_seguidas_acumulam_e_sucesso_zera(banco, rede):
    rede.rotas[GH_URL] = (500, "erro")
    for _ in range(coletor.AVISO_FALHAS - 1):
        _coletar(banco, [ACME], forcar=True)
    status = RunStatus()
    _coletar(banco, [ACME], forcar=True, status=status)
    assert coletor.fila(banco)[0]["tentativas"] == coletor.AVISO_FALHAS
    assert any("falhas seguidas" in a for a in status.warnings)

    rede.rotas[GH_URL] = (200, GREENHOUSE)
    _coletar(banco, [ACME], forcar=True)
    fila = coletor.fila(banco)[0]
    assert (fila["estado"], fila["tentativas"], fila["ultimo_erro"]) == ("ok", 0, None)


def test_404_nao_refaz(banco, rede):
    rede.rotas[GH_URL] = (404, "board não existe")
    _coletar(banco, [ACME])
    assert rede.chamadas.count(GH_URL) == 1


def test_json_inesperado_falha_sem_gravar(banco, rede):
    rede.rotas[GH_URL] = (200, {"erro": "board privado"})
    (acme,) = _coletar(banco, [ACME])["resultados"]
    assert acme["status"] == "falhou"
    assert "jobs" in acme["erro"]
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


# -------------------------------------------------------------------- robots


def test_robots_que_proibe_bloqueia_sem_chamar_a_api(banco, rede):
    rede.rotas["https://boards-api.greenhouse.io/robots.txt"] = (200, "User-agent: *\nDisallow: /v1/\n")
    (acme,) = _coletar(banco, [ACME])["resultados"]

    assert acme["status"] == "bloqueada"
    assert GH_URL not in rede.chamadas
    assert banco.execute("SELECT status FROM coletas").fetchone()[0] == "bloqueada"


def test_robots_lido_uma_vez_por_host(banco, rede):
    outra = coletor.Fonte("greenhouse", "outra", "Outra")
    rede.rotas[outra.url] = (200, {"jobs": []})
    _coletar(banco, [ACME, outra])
    assert rede.chamadas.count("https://boards-api.greenhouse.io/robots.txt") == 1


def test_robots_inacessivel_nao_conta_como_permitido(banco, rede):
    rede.rotas["https://api.lever.co/robots.txt"] = httpx.ConnectError("sem rede")
    (beta,) = _coletar(banco, [BETA])["resultados"]
    assert beta["status"] == "falhou"
    assert "robots.txt" in beta["erro"]
    assert LEVER_URL not in rede.chamadas


def test_robots_em_html_le_as_regras_do_pre(banco, rede):
    """A Gupy serve o robots.txt como página HTML; as regras estão num <pre>."""
    pagina = ('<!DOCTYPE html><html><body><pre style="x">User-agent: *\nDisallow: /v0/\n'
              "Sitemap: https://x.test/?a=1&amp;b=2</pre></body></html>")
    rede.rotas["https://api.lever.co/robots.txt"] = (200, pagina)
    (beta,) = _coletar(banco, [BETA])["resultados"]
    assert beta["status"] == "bloqueada"
    assert LEVER_URL not in rede.chamadas


# ---------------------------------------------------------------------- gupy


def _pagina_next(page_props: dict) -> str:
    """HTML mínimo de uma página Next.js renderizada no servidor, como a Gupy serve."""
    dados = json.dumps({"props": {"pageProps": page_props}, "page": "/"})
    return (f'<html><head></head><body><div id="__next"></div>'
            f'<script id="__NEXT_DATA__" type="application/json">{dados}</script></body></html>')


def _vaga_lista(id_, titulo, tipo="vacancy_type_effective", modo="on-site"):
    return {"id": id_, "title": titulo, "type": tipo, "department": "TI",
            "workplace": {"address": {"city": "Belo Horizonte", "stateShortName": "MG"},
                          "workplaceType": modo}}


GUPY_LISTA = _pagina_next({"subdomain": "gama", "jobs": [
    _vaga_lista(1, "Analista de Automação  Júnior"),
    _vaga_lista(2, "Analista de Automação Sênior"),
    _vaga_lista(3, "Automação - Banco de Talentos", tipo="vacancy_type_talent_pool"),
    _vaga_lista(4, "Desenvolvedor de Integrações", modo="remote"),
    _vaga_lista(5, "Vendedor"),
]})


def _pagina_vaga(id_, descricao):
    return _pagina_next({"job": {
        "id": id_, "name": f"vaga {id_}", "description": f"<p>{descricao}</p>",
        "responsibilities": "<ul><li>Criar robôs RPA</li></ul>", "prerequisites": "<p>Python e SQL</p>",
        "relevantExperiences": "",
    }})


GAMA = coletor.Fonte("gupy", "gama", "Gama", incluir=coletor._termos(["automacao", "integra"]),
                     excluir=coletor._termos(["senior"]))
GUPY_URL = "https://gama.gupy.io/"


@pytest.fixture
def gupy(rede):
    rede.rotas[GUPY_URL] = (200, GUPY_LISTA)
    rede.rotas["https://gama.gupy.io/jobs/1"] = (200, _pagina_vaga(1, "Automatizar faturamento."))
    rede.rotas["https://gama.gupy.io/jobs/4"] = (200, _pagina_vaga(4, "Integrar sistemas de saúde."))
    return rede


def test_gupy_lista_ignora_banco_de_talentos_e_normaliza():
    itens = coletor.listar_gupy(GUPY_LISTA, "gama")
    assert [i["url"] for i in itens] == [f"https://gama.gupy.io/jobs/{n}" for n in (1, 2, 4, 5)]
    assert itens[0]["titulo"] == "Analista de Automação Júnior"
    assert (itens[0]["local"], itens[2]["local"]) == ("Belo Horizonte/MG", "Remoto")


def test_gupy_texto_junta_as_secoes_da_vaga():
    texto = coletor.texto_vaga_gupy(_pagina_vaga(1, "Automatizar faturamento."))
    assert texto.splitlines() == [
        "Automatizar faturamento.", "Responsabilidades", "- Criar robôs RPA", "Requisitos", "Python e SQL"]


@pytest.mark.parametrize("pagina", ["<html>sem dados</html>", _pagina_next({"outra": 1})])
def test_gupy_formato_inesperado_e_erro(pagina):
    with pytest.raises(ValueError):
        coletor.listar_gupy(pagina, "gama")


def test_gupy_baixa_so_as_vagas_filtradas(banco, gupy):
    (gama,) = _coletar(banco, [GAMA])["resultados"]

    assert (gama["status"], gama["vagas_vistas"], gama["vagas_filtradas"], gama["vagas_novas"]) == (
        "ok", 4, 2, 2)
    paginas = [u for u in gupy.chamadas if "/jobs/" in u]
    assert paginas == ["https://gama.gupy.io/jobs/1", "https://gama.gupy.io/jobs/4"]
    jobs = banco.execute("SELECT titulo, fonte, local, texto_bruto FROM jobs ORDER BY id").fetchall()
    assert [(j["titulo"], j["fonte"], j["local"]) for j in jobs] == [
        ("Analista de Automação Júnior", "gupy", "Belo Horizonte/MG"),
        ("Desenvolvedor de Integrações", "gupy", "Remoto"),
    ]
    assert "Criar robôs RPA" in jobs[0]["texto_bruto"]


def test_gupy_vaga_ja_gravada_nao_baixa_de_novo(banco, gupy):
    _coletar(banco, [GAMA])
    gupy.chamadas.clear()
    (gama,) = _coletar(banco, [GAMA], forcar=True)["resultados"]
    assert (gama["vagas_novas"], gama["duplicadas"]) == (0, 2)
    assert not [u for u in gupy.chamadas if "/jobs/" in u]


def test_gupy_pausa_entre_paginas_e_respeita_o_teto(banco, gupy, mocker):
    dormir = mocker.patch("hermes.domain.coletor.time.sleep")
    mocker.patch.object(coletor, "GUPY_MAX_VAGAS", 1)
    status = RunStatus()
    (gama,) = _coletar(banco, [GAMA], status=status)["resultados"]

    assert gama["vagas_novas"] == 1
    assert any("1 vaga(s) ficaram para a próxima coleta" in a for a in status.warnings)
    assert dormir.call_count == 0  # uma página só: nada a espaçar

    mocker.patch.object(coletor, "GUPY_MAX_VAGAS", 25)
    _coletar(banco, [GAMA], forcar=True)
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_gupy_pagina_que_falha_vira_aviso_e_as_outras_entram(banco, gupy):
    gupy.rotas["https://gama.gupy.io/jobs/4"] = (404, "vaga encerrada")
    status = RunStatus()
    (gama,) = _coletar(banco, [GAMA], status=status)["resultados"]
    assert (gama["status"], gama["vagas_novas"]) == ("ok", 1)
    assert any("1 vaga(s) não baixaram" in a for a in status.warnings)


def test_gupy_todas_as_paginas_falham_e_a_fonte_falha(banco, gupy):
    for n in (1, 4):
        gupy.rotas[f"https://gama.gupy.io/jobs/{n}"] = (404, "")
    (gama,) = _coletar(banco, [GAMA])["resultados"]
    assert gama["status"] == "falhou"
    assert coletor.fila(banco)[0]["tentativas"] == 1


def test_gupy_robots_vale_para_as_paginas_de_vaga(banco, gupy):
    gupy.rotas["https://gama.gupy.io/robots.txt"] = (200, "User-agent: *\nDisallow: /jobs/\n")
    (gama,) = _coletar(banco, [GAMA])["resultados"]
    assert gama["status"] == "bloqueada"  # a lista pôde ser lida, as vagas não
    assert not [u for u in gupy.chamadas if "/jobs/" in u]
