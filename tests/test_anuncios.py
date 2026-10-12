"""Vagas anunciadas por e-mail: extração do alerta do LinkedIn e o cardápio sem repetição."""

from hermes.domain import anuncios
from hermes.domain import candidaturas as cand

ALERTA = """Seu alerta de vaga para Engenheiro de software em: Campinas foi criado
Novas vagas correspondem às suas preferências.
Gerenciar alertas: https://www.linkedin.com/comm/jobs/alerts?lipi=abc

AI Engineer (Remote, Sao Paulo)
Borda Digital
Brasil
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4000000001/?trackingId=x&refId=y

---------------------------------------------------------

Desenvolvedor(a) Mulesoft Pleno
Delta Sistemas
Campinas, SP

Esta empresa está contratando
Candidate-se com currículo e perfil
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4000000002/?trackingId=z

---------------------------------------------------------

Desenvolvedor Java Sênior
Sereno Tech

1 conexão
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4000000003/

---------------------------------------------------------

Ver todas as vagas no LinkedIn: https://www.linkedin.com/comm/jobs/search-results/?x=1
"""


def test_extrai_cada_vaga_do_alerta_sem_o_rastreio_do_link():
    vagas = anuncios.extrair_linkedin(ALERTA)
    assert [(v["titulo"], v["empresa"], v["local"]) for v in vagas] == [
        ("AI Engineer (Remote, Sao Paulo)", "Borda Digital", "Brasil"),
        ("Desenvolvedor(a) Mulesoft Pleno", "Delta Sistemas", "Campinas, SP"),
        ("Desenvolvedor Java Sênior", "Sereno Tech", None),
    ]
    assert vagas[0]["url"] == "https://www.linkedin.com/jobs/view/4000000001/"
    assert vagas[0]["id"] == "linkedin:4000000001"


def test_texto_sem_cartao_nao_vira_vaga():
    assert anuncios.extrair_linkedin("Olá, nenhuma vaga aqui. Visualizar vaga: https://exemplo.com/") == []


def _alerta(conn, gid, recebido, corpo=ALERTA, de="LinkedIn <jobalerts-noreply@linkedin.com>"):
    cand.inserir_email(conn, {"gmail_id": gid, "recebido_em": recebido, "de": de,
                              "assunto": "vagas", "corpo": corpo, "final": "outro"})


def test_cardapio_nao_repete_vaga_e_marca_empresa_onde_ja_se_candidatou(conn):
    _alerta(conn, "g1", "2026-09-20T10:00:00+00:00")
    _alerta(conn, "g2", "2026-09-25T10:00:00+00:00", corpo=ALERTA.split("------")[0])
    _alerta(conn, "g3", "2026-09-26T10:00:00+00:00", de="Glassdoor <noreply@glassdoor.com>")
    cand.registrar_manual(conn, "Delta Sistemas", "geral")

    vagas = anuncios.listar(conn)
    assert [v["empresa"] for v in vagas] == ["Borda Digital", "Delta Sistemas", "Sereno Tech"]
    primeira = vagas[0]
    assert primeira["vezes"] == 2 and primeira["anunciada_em"].startswith("2026-09-25")
    assert primeira["alerta"] == "Engenheiro de software · Campinas"
    assert [v["ja_candidatou"] for v in vagas] == [False, True, False]
