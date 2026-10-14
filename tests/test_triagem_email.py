"""Triagem de e-mail: política do Jev no código, sync idempotente e avaliação. Sem Gmail nem Jev reais."""

import base64
import json
from types import SimpleNamespace

import pytest

from hermes.domain import candidaturas as cand
from hermes.domain import triagem_email as tri
from hermes.run_status import RunStatus


class JevFalso:
    """Responde por assunto: {assunto: (categoria, p_categoria, p_processo)}."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.chamadas = 0

    def system_one(self, state, questions):
        self.chamadas += 1
        cat, p_cat, p_proc = self.respostas[state["subject"]]
        if cat == "erro":
            raise RuntimeError("timeout")
        return SimpleNamespace(
            choices={"categoria": SimpleNamespace(choice=cat, probabilities={cat: p_cat}, confidence=p_cat)},
            nouls={"e_processo": SimpleNamespace(noul=p_proc), "tem_prazo": SimpleNamespace(noul=0.1)},
            usage=SimpleNamespace(input_tokens=100),
        )


class CaixaFalsa:
    def __init__(self, emails):
        self.emails = {e["gmail_id"]: e for e in emails}
        self.rotulos = []

    def listar_ids(self, dias, maximo):
        # Gmail: mais novo primeiro
        return sorted(self.emails, key=lambda i: self.emails[i]["recebido_em"], reverse=True)[:maximo]

    def ler(self, msg_id):
        return self.emails[msg_id]

    def rotular(self, msg_id, label):
        self.rotulos.append((msg_id, label))


def _e(gid, de, assunto, recebido):
    return {"gmail_id": gid, "de": de, "assunto": assunto, "recebido_em": recebido, "corpo": "..."}


@pytest.mark.parametrize("resposta, final", [
    (("avanco", 0.95, 0.9), "avanco"),
    (("pendencia", 0.9, 0.9), "pendencia"),
    (("avanco", 0.6, 0.9), "revisar"),        # abaixo do LIMIAR
    (("avanco", 0.95, 0.3), "outro"),         # não é processo
    (("outro", 0.99, 0.9), "outro"),
])
def test_classificar_aplica_a_politica(resposta, final):
    r = tri.classificar(JevFalso({"s": resposta}), {"de": "x", "assunto": "s", "corpo": "c"})
    assert r["final"] == final
    assert r["categoria_jev"] == resposta[0]


EMAILS = [
    _e("1", "noreply@mail.orbital.jobs", "Agradecemos por você se candidatar a uma vaga na Orbital.",
       "2026-09-01T10:00:00+00:00"),
    _e("2", "noreply@mail.orbital.jobs", "Processo de candidatura na Orbital: atualização",
       "2026-09-20T10:00:00+00:00"),
    _e("3", "Cloudflare <em@em1.cloudflare.com>", "Welcome to Birthday Week", "2026-09-21T10:00:00+00:00"),
    _e("4", "x@y.com", "quebra", "2026-09-22T10:00:00+00:00"),
]
RESPOSTAS = {
    EMAILS[0]["assunto"]: ("inscricao_confirmada", 0.97, 0.95),
    EMAILS[1]["assunto"]: ("reprovado", 0.96, 0.95),
    EMAILS[2]["assunto"]: ("outro", 0.99, 0.02),
    "quebra": ("erro", 0, 0),
}


def test_sincronizar_liga_em_ordem_cronologica_e_nao_para_no_erro(conn):
    """Review Focus 2: a pingada nasce com a data da inscrição, não da reprovação."""
    status = RunStatus()
    r = tri.sincronizar(conn, CaixaFalsa(EMAILS), JevFalso(RESPOSTAS), 30, 200, status)

    assert (r["lidos"], r["novos"], r["ligados"]) == (4, 3, 2)
    assert r["por_categoria"] == {"inscricao_confirmada": 1, "reprovado": 1, "outro": 1}
    assert status.tool_errors == 1 and any("4" in a for a in status.warnings)
    [c] = cand.listar(conn)
    assert (c["empresa_norm"], c["status"], c["enviada_em"]) == ("orbital", "reprovada", "2026-09-01T10:00:00+00:00")
    assert conn.execute("SELECT COUNT(*) FROM emails WHERE assunto LIKE 'Welcome%' AND empresa_extraida IS NULL"
                        ).fetchone()[0] == 1  # `outro` não gasta extração


def test_sincronizar_de_novo_nao_chama_o_jev(conn):
    jev = JevFalso(RESPOSTAS)
    tri.sincronizar(conn, CaixaFalsa(EMAILS), jev, 30, 200, RunStatus())
    antes = jev.chamadas
    r = tri.sincronizar(conn, CaixaFalsa(EMAILS), jev, 30, 200, RunStatus())
    assert jev.chamadas == antes + 1  # só o que deu erro é tentado de novo
    assert r["ja_vistos"] == 3


def test_rotular_aplica_label_so_nas_categorias_com_label(conn):
    caixa = CaixaFalsa(EMAILS[:3])
    tri.sincronizar(conn, caixa, JevFalso(RESPOSTAS), 30, 200, RunStatus(), rotular=True)
    assert sorted(caixa.rotulos) == [("1", "Vagas/Inscrito"), ("2", "Vagas/Reprovado")]


def test_avaliar_usa_o_rotulo_manual(conn):
    tri.sincronizar(conn, CaixaFalsa(EMAILS[:3]), JevFalso(RESPOSTAS), 30, 200, RunStatus())
    ids = [r[0] for r in conn.execute("SELECT id FROM emails ORDER BY recebido_em")]
    cand.corrigir(conn, ids[0], "inscricao_confirmada")  # certo
    cand.corrigir(conn, ids[1], "avanco")                # Jev errou
    r = tri.avaliar(conn)
    assert (r["rotuladas"], r["decididas"], r["certas"]) == (2, 2, 1)
    assert r["erros"][0]["final"] == "reprovado" and r["erros"][0]["rotulo_manual"] == "avanco"


def test_extrair_corpo_prefere_texto_e_limpa_html():
    from hermes.integracoes.gmail import extrair_corpo

    b64 = lambda s: base64.urlsafe_b64encode(s.encode()).decode()  # noqa: E731
    html = {"mimeType": "text/html", "body": {"data": b64("<p>Oi <b>Fulano</b></p><script>x()</script>")}}
    assert extrair_corpo({"parts": [html]}) == "Oi Fulano"
    plano = {"mimeType": "text/plain", "body": {"data": b64("Texto   puro")}}
    assert extrair_corpo({"parts": [html, plano]}) == "Texto puro"


def test_erro_ao_ligar_nao_derruba_o_sync_e_o_email_volta_no_proximo(conn, monkeypatch):
    """I3: e-mail que falhou ao ligar não fica gravado como visto e sem candidatura."""
    original = cand.ligar

    def ligar(c, email_id):
        if c.execute("SELECT gmail_id FROM emails WHERE id = ?", (email_id,)).fetchone()[0] == "1":
            raise RuntimeError("database is locked")
        return original(c, email_id)

    monkeypatch.setattr(cand, "ligar", ligar)
    status = RunStatus()
    r = tri.sincronizar(conn, CaixaFalsa(EMAILS[:3]), JevFalso(RESPOSTAS), 30, 200, status)
    assert status.tool_errors == 1 and r["novos"] == 2
    assert conn.execute("SELECT COUNT(*) FROM emails WHERE gmail_id = '1'").fetchone()[0] == 0


def test_token_expirado_refaz_a_autorizacao_e_grava_so_para_o_dono(tmp_path, monkeypatch):
    """I4: refresh token de app em modo Testing expira em 7 dias."""
    import google.oauth2.credentials as creds_mod
    import google_auth_oauthlib.flow as flow_mod
    import googleapiclient.discovery as discovery
    from google.auth.exceptions import RefreshError

    from hermes.integracoes import gmail

    class Velho:
        valid, expired, refresh_token = False, True, "r"

        def refresh(self, _):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    class Novo:
        valid = True

        def to_json(self):
            return '{"novo": true}'

    (tmp_path / "token_readonly.json").write_text("{}")
    (tmp_path / "credentials.json").write_text("{}")
    monkeypatch.setattr(creds_mod.Credentials, "from_authorized_user_file", lambda *a: Velho())
    monkeypatch.setattr(flow_mod.InstalledAppFlow, "from_client_secrets_file",
                        lambda *a: SimpleNamespace(run_local_server=lambda port: Novo()))
    monkeypatch.setattr(discovery, "build", lambda *a, **k: object())

    gmail.CaixaGmail(tmp_path)
    token = tmp_path / "token_readonly.json"
    assert token.read_text() == '{"novo": true}'
    assert token.stat().st_mode & 0o777 == 0o600


def test_cli_carrega_sem_o_sdk_do_jev(monkeypatch):
    """Só `email sync` precisa do Jev; `quilha backup` e o resto não podem quebrar sem ele."""
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)  # import passa a falhar
    import hermes.domain

    for nome in ("hermes.domain.triagem_email", "hermes.cli"):
        monkeypatch.delitem(sys.modules, nome, raising=False)
    monkeypatch.delattr(hermes.domain, "triagem_email", raising=False)
    importlib.import_module("hermes.cli")


class _Resposta(dict):
    def __init__(self, status):
        super().__init__(status=str(status))
        self.status = status
        self.reason = "x"


def _cota():
    from googleapiclient.errors import HttpError

    return HttpError(_Resposta(403), b'{"error": {"errors": [{"reason": "rateLimitExceeded"}]}}')


def test_gmail_espera_e_tenta_de_novo_quando_estoura_a_cota(monkeypatch):
    """Sync real de 29/09: 65 de 200 e-mails falharam com 403 rateLimitExceeded, sem nova tentativa."""
    from hermes.integracoes import gmail

    esperas = []
    monkeypatch.setattr(gmail, "_dormir", esperas.append)
    respostas = iter([_cota(), _cota(), "ok"])

    def pedido():
        r = next(respostas)
        if isinstance(r, Exception):
            raise r
        return r

    assert gmail._com_retentativa(pedido) == "ok"
    assert esperas == [1, 2]


def test_gmail_desiste_depois_de_cinco_tentativas_e_nao_repete_outros_erros(monkeypatch):
    from googleapiclient.errors import HttpError

    from hermes.integracoes import gmail

    monkeypatch.setattr(gmail, "_dormir", lambda s: None)
    chamadas = []

    def sempre_cota():
        chamadas.append(1)
        raise _cota()

    with pytest.raises(HttpError):
        gmail._com_retentativa(sempre_cota)
    assert len(chamadas) == 5

    def nao_encontrado():
        chamadas.append(1)
        raise HttpError(_Resposta(404), b"not found")

    chamadas.clear()
    with pytest.raises(HttpError):
        gmail._com_retentativa(nao_encontrado)
    assert len(chamadas) == 1


def test_avisos_repetidos_saem_resumidos():
    avisos = [f"e-mail {i}: <HttpError 403 when requesting https://x returned \"Quota exceeded\" ...>"
              for i in range(65)] + ["label em 9: boom"]
    linhas = tri.resumir_avisos(avisos)
    assert len(linhas) <= 6
    assert any("65" in l for l in linhas)
    assert all(len(l) <= 160 for l in linhas)


# --- corpo guardado (migração 006) ---------------------------------------------


def test_sync_grava_o_corpo_inteiro_e_manda_ao_jev_so_o_comeco(conn):
    longo = "Queremos te conhecer melhor.\n\n" + "x" * (tri.MAX_CORPO + 500)
    caixa = CaixaFalsa([{**_e("g1", "rh@aureo.com.br", "Áureo | Próxima etapa", "2026-10-01T10:00:00+00:00"),
                         "corpo": longo}])
    vistos = []

    class JevQueGuarda(JevFalso):
        def system_one(self, state, questions):
            vistos.append(state["body"])
            return super().system_one(state, questions)

    tri.sincronizar(conn, caixa, JevQueGuarda({"Áureo | Próxima etapa": ("avanco", 0.95, 0.9)}), 30, 10, RunStatus())
    assert conn.execute("SELECT corpo FROM emails").fetchone()[0] == longo
    assert len(vistos[0]) == tri.MAX_CORPO


def test_preencher_corpos_busca_so_os_que_faltam_e_nao_para_no_erro(conn):
    for gid in ("g1", "g2", "g3"):
        cand.inserir_email(conn, {**_e(gid, "rh@x.com", gid, "2026-10-01T10:00:00+00:00"), "corpo": None,
                                  "final": "outro"})
    conn.execute("UPDATE emails SET corpo = 'já tinha' WHERE gmail_id = 'g3'")
    conn.commit()
    caixa = CaixaFalsa([{**_e("g1", "rh@x.com", "g1", "2026-10-01T10:00:00+00:00"), "corpo": "Olá"}])
    status = RunStatus()
    r = tri.preencher_corpos(conn, caixa, status)  # g2 sumiu do Gmail
    assert r == {"faltando": 2, "preenchidos": 1}
    corpos = dict(conn.execute("SELECT gmail_id, corpo FROM emails").fetchall())
    assert corpos == {"g1": "Olá", "g2": None, "g3": "já tinha"}
    assert status.tool_errors == 1


def test_extrair_corpo_mantem_paragrafos():
    from hermes.integracoes.gmail import extrair_corpo

    b64 = lambda s: base64.urlsafe_b64encode(s.encode()).decode()  # noqa: E731
    html = {"mimeType": "text/html", "body": {"data": b64("<p>Olá,</p><p>Queremos te<br>conhecer.</p>")}}
    assert extrair_corpo({"parts": [html]}) == "Olá,\n\nQueremos te\nconhecer."
    plano = {"mimeType": "text/plain", "body": {"data": b64("Oi\r\n\r\n\r\nTchau  \n")}}
    assert extrair_corpo({"parts": [plano]}) == "Oi\n\nTchau"


# --- triagem pelo LLM do usuário -------------------------------------------------


@pytest.mark.parametrize("resposta, final", [
    ('{"e_processo": true, "categoria": "avanco", "certeza": 0.93, "tem_prazo": true}', "avanco"),
    ('{"e_processo": true, "categoria": "reprovado", "certeza": 0.6, "tem_prazo": false}', "revisar"),
    ('{"e_processo": false, "categoria": "avanco", "certeza": 0.99, "tem_prazo": false}', "outro"),
    ('Claro! {"e_processo": true, "categoria": "pendencia", "certeza": 1.7}', "pendencia"),  # texto em volta, certeza > 1
])
def test_llm_aplica_a_mesma_politica(monkeypatch, resposta, final):
    pedidos = []
    monkeypatch.setattr(tri.llm, "complete", lambda system, user, **kw: pedidos.append(user) or resposta)

    r = tri.classificar_llm({"de": "rh@x.com", "assunto": "Próxima etapa", "corpo": "y" * (tri.MAX_CORPO + 9)})

    assert r["final"] == final and 0 <= r["prob_categoria"] <= 1
    assert len(json.loads(pedidos[0])["body"]) == tri.MAX_CORPO


def test_llm_com_categoria_inventada_vira_aviso_no_sync(conn, monkeypatch):
    monkeypatch.setattr(tri.llm, "complete", lambda *a, **kw: '{"categoria": "entrevista", "certeza": 0.9}')
    status = RunStatus()

    r = tri.sincronizar(conn, CaixaFalsa(EMAILS[:1]), tri.com_llm(), 30, 10, status)

    assert r["novos"] == 0 and status.tool_errors == 1
    assert "categoria que não existe" in status.warnings[0]
    assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 0  # tenta de novo no próximo sync


# --- data da entrevista ------------------------------------------------------------


@pytest.mark.parametrize("campo, esperado", [
    ('"entrevista_em": "2026-10-10T14:00:00-03:00"', "2026-10-10T14:00:00-03:00"),
    ('"entrevista_em": null', None),
    ('"entrevista_em": "sexta às 14h"', None),       # não é ISO: some, a classificação continua
    ('"entrevista_em": "2026-10-10"', None),          # sem hora não é entrevista marcada
])
def test_llm_extrai_a_data_da_entrevista(monkeypatch, campo, esperado):
    resposta = '{"e_processo": true, "categoria": "avanco", "certeza": 0.95, "tem_prazo": true, ' + campo + "}"
    monkeypatch.setattr(tri.llm, "complete", lambda *a, **kw: resposta)
    r = tri.classificar_llm({"de": "rh@x.com", "assunto": "Entrevista técnica", "corpo": "Sexta, 14h"})
    assert r["final"] == "avanco" and r["entrevista_em"] == esperado


def test_llm_sem_o_campo_da_entrevista_devolve_none(monkeypatch):
    monkeypatch.setattr(tri.llm, "complete", lambda *a, **kw: '{"e_processo": true, "categoria": "avanco", "certeza": 0.9}')
    assert tri.classificar_llm({"de": "rh@x.com", "assunto": "a", "corpo": ""})["entrevista_em"] is None


def test_llm_hora_sem_fuso_ganha_o_fuso_local(monkeypatch):
    resposta = '{"e_processo": true, "categoria": "avanco", "certeza": 0.9, "entrevista_em": "2026-10-10T14:00:00"}'
    monkeypatch.setattr(tri.llm, "complete", lambda *a, **kw: resposta)
    r = tri.classificar_llm({"de": "rh@x.com", "assunto": "a", "corpo": ""})
    from datetime import datetime
    quando = datetime.fromisoformat(r["entrevista_em"])
    assert quando.tzinfo is not None and quando.hour == 14


def test_sync_com_entrevista_marcada_leva_a_candidatura_para_a_etapa(conn, monkeypatch):
    cid = cand.registrar_manual(conn, "Orbital", "geral", enviada_em="2026-09-01")
    resposta = ('{"e_processo": true, "categoria": "avanco", "certeza": 0.95,'
                ' "entrevista_em": "2026-10-10T14:00:00-03:00"}')
    monkeypatch.setattr(tri.llm, "complete", lambda *a, **kw: resposta)
    email = _e("ent1", "noreply@mail.orbital.jobs", "Processo de candidatura na Orbital: entrevista técnica",
               "2026-10-05T12:00:00+00:00")

    tri.sincronizar(conn, CaixaFalsa([email]), tri.com_llm(), 30, 10, RunStatus())

    c = conn.execute("SELECT status, entrevista_em FROM candidaturas WHERE id = ?", (cid,)).fetchone()
    assert tuple(c) == ("entrevista", "2026-10-10T14:00:00-03:00")




def test_llm_recebe_a_data_do_email_no_fuso_local(monkeypatch):
    from datetime import datetime
    pedidos = []
    monkeypatch.setattr(tri.llm, "complete", lambda system, user, **kw: pedidos.append(user) or
                        '{"e_processo": true, "categoria": "avanco", "certeza": 0.9}')
    tri.classificar_llm({"de": "rh@x.com", "assunto": "a", "corpo": "", "recebido_em": "2026-10-06T01:30:00+00:00"})
    esperado = datetime.fromisoformat("2026-10-06T01:30:00+00:00").astimezone().isoformat(timespec="seconds")
    assert json.loads(pedidos[0])["received"] == esperado
    tri.classificar_llm({"de": "rh@x.com", "assunto": "a", "corpo": ""})
    assert "received" not in json.loads(pedidos[1])  # sem data: não manda null para o modelo chutar o ano


def test_llm_aceita_espaco_no_lugar_do_t(monkeypatch):
    resposta = '{"e_processo": true, "categoria": "avanco", "certeza": 0.9, "entrevista_em": "2026-10-10 14:00:00-03:00"}'
    monkeypatch.setattr(tri.llm, "complete", lambda *a, **kw: resposta)
    assert tri.classificar_llm({"de": "rh@x.com", "assunto": "a", "corpo": ""})["entrevista_em"] == "2026-10-10T14:00:00-03:00"
