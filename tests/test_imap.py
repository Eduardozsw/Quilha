"""E-mail por IMAP com senha de app: servidor falso no lugar do imaplib, nenhuma rede."""

import imaplib
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from hermes.api.app import criar_app
from hermes.config import load_config
from hermes.domain import configuracao
from hermes.domain import triagem_email as tri
from hermes.integracoes import caixa as caixas
from hermes.integracoes import imap
from hermes.run_status import RunStatus


def _bruto(assunto, de, html=None, texto=None, anexo=False) -> bytes:
    m = EmailMessage()
    m["Subject"], m["From"], m["Date"] = assunto, de, "Sun, 05 Oct 2026 10:00:00 +0000"
    if texto:
        m.set_content(texto)
    if html:
        if texto:
            m.add_alternative(html, subtype="html")
        else:
            m.set_content(html, subtype="html")
    if anexo:
        m.add_attachment(b"%PDF-1.4 binario", maintype="application", subtype="pdf", filename="cv.pdf")
    return m.as_bytes()


MENSAGENS = {  # uid -> (X-GM-MSGID, INTERNALDATE, bruto)
    b"11": (1782345, "03-Oct-2026 09:00:00 +0000", _bruto("Candidatura recebida", "rh@quartzo.example", texto="Recebemos.")),
    b"12": (1782346, "04-Oct-2026 09:00:00 +0000",
            _bruto("=?utf-8?q?Convite_para_entrevista_=E2=9C=A8?=", "Lume <no-reply@ashbyhq.com>",
                   html="<p>Oi!</p><p>Vamos <b>conversar</b>?</p><script>x()</script>", anexo=True)),
    b"13": (1782347, "05-Oct-2026 10:00:00 -0300", _bruto("Resultado", "rh@kova.example", texto="Não seguiremos.")),
}


class ServidorFalso:
    senha_certa = "abcd efgh ijkl mnop"
    gmail = True

    def __init__(self, host, porta, timeout=None):
        self.host = host
        self.capabilities = ("IMAP4REV1", "X-GM-EXT-1") if self.gmail else ("IMAP4REV1",)
        self.selecionada = None

    def login(self, usuario, senha):
        if senha != self.senha_certa:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"logged in"]

    def select(self, pasta, readonly=False):
        assert readonly, "o Quilha nunca abre a caixa para escrita"
        self.selecionada = pasta
        return ("OK", [b"3"]) if pasta == '"INBOX"' else ("NO", [b"no such mailbox"])

    def response(self, codigo):
        return codigo, [b"777"]

    def uid(self, comando, *args):
        if comando == "SEARCH":
            return "OK", [b" ".join(MENSAGENS)]
        conjunto, partes = args
        if partes == "(X-GM-MSGID)":
            return "OK", [f"{i} (X-GM-MSGID {MENSAGENS[u][0]} UID {u.decode()})".encode()
                          for i, u in enumerate(conjunto.encode().split(b","), 1)]
        msgid, data, bruto = MENSAGENS[conjunto.encode()]
        cab = f'1 (UID {conjunto} INTERNALDATE "{data}" BODY[] {{{len(bruto)}}}'.encode()
        return "OK", [(cab, bruto), b")"]

    def logout(self):
        return "BYE", [b""]


@pytest.fixture
def servidor(monkeypatch):
    ServidorFalso.gmail = True
    monkeypatch.setattr(imaplib, "IMAP4_SSL", ServidorFalso)
    return ServidorFalso


def _caixa():
    return imap.CaixaIMAP("imap.gmail.com", "fulano@gmail.com", ServidorFalso.senha_certa)


def test_no_gmail_o_id_e_o_mesmo_da_gmail_api_e_o_mais_novo_vem_primeiro(servidor):
    ids = _caixa().listar_ids(30, 2)
    assert ids == [format(1782347, "x"), format(1782346, "x")]


def test_outro_provedor_usa_host_validade_e_uid(servidor):
    servidor.gmail = False
    c = imap.CaixaIMAP("imap.mail.example", "fulano@mail.example", ServidorFalso.senha_certa)
    assert c.listar_ids(30, 10) == [f"imap:imap.mail.example:777:{u}" for u in ("13", "12", "11")]


def test_ler_decodifica_assunto_e_html_e_ignora_anexo(servidor):
    c = _caixa()
    eid = c.listar_ids(30, 10)[1]
    e = c.ler(eid)
    assert e["assunto"] == "Convite para entrevista ✨"
    assert e["de"] == "Lume <no-reply@ashbyhq.com>"
    assert e["corpo"] == "Oi!\n\nVamos conversar ?" and "PDF" not in e["corpo"]
    assert e["recebido_em"] == "2026-10-04T09:00:00+00:00"


def test_data_com_fuso_vira_utc(servidor):
    c = _caixa()
    assert c.ler(c.listar_ids(30, 1)[0])["recebido_em"] == "2026-10-05T13:00:00+00:00"


def test_senha_errada_explica_a_senha_de_app(servidor):
    with pytest.raises(imap.FalhaIMAP, match="senha de app"):
        imap.CaixaIMAP("imap.gmail.com", "fulano@gmail.com", "senha normal")


def test_sem_dados_recusa_antes_de_conectar(servidor):
    with pytest.raises(imap.FalhaIMAP, match="Configurações"):
        imap.CaixaIMAP("imap.gmail.com", "", "")


def test_labels_so_pelo_oauth(servidor):
    with pytest.raises(imap.FalhaIMAP, match="OAuth"):
        _caixa().rotular("x", "Vagas/Avanço")


def test_sync_pelo_imap_grava_e_liga(conn, servidor):
    def classificador(email, status):
        final = "reprovado" if "Resultado" in email["assunto"] else "inscricao_confirmada"
        return {"categoria_jev": final, "prob_categoria": 0.95, "prob_processo": 1.0, "prob_prazo": 0.0,
                "final": final, "latencia_ms": 1}

    r = tri.sincronizar(conn, _caixa(), classificador, 30, 10, RunStatus())

    assert r["novos"] == 3
    assert {row[0] for row in conn.execute("SELECT gmail_id FROM emails")} == {
        format(m[0], "x") for m in MENSAGENS.values()}


# --- configuração e "Testar conexão" ------------------------------------------


@pytest.fixture
def api(monkeypatch, tmp_path, servidor):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "base"))
    for chave in configuracao.EDITAVEIS:
        monkeypatch.delenv(chave, raising=False)
    cfg = load_config(vault_path=tmp_path / "vault", db_path=tmp_path / "hermes.db")
    return TestClient(criar_app(cfg, "t"), headers={"X-Hermes-Token": "t"})


def test_testar_conexao_pela_api(api):
    estado = api.put("/api/config", json={"email_origem": "imap", "imap_usuario": "fulano@gmail.com",
                                          "imap_senha": ServidorFalso.senha_certa}).json()
    assert estado["email"]["origem"] == "imap" and estado["email"]["imap_senha_definida"] is True
    assert estado["email"]["rotulos_disponiveis"] is False
    assert ServidorFalso.senha_certa not in str(estado)

    r = api.post("/api/emails/testar").json()
    assert r == {"ok": True, "origem": "imap", "mensagem": "Conectado: 3 e-mail(s) nos últimos 7 dias."}


def test_testar_com_senha_errada_nao_estoura(api):
    api.put("/api/config", json={"email_origem": "imap", "imap_usuario": "f@gmail.com", "imap_senha": "errada"})
    r = api.post("/api/emails/testar").json()
    assert r["ok"] is False and "senha de app" in r["mensagem"]


def test_origem_invalida_e_recusada(api):
    r = api.put("/api/config", json={"email_origem": "outlook"})
    assert r.status_code == 422 and "EMAIL_ORIGEM" in r.json()["erro"]


def test_rotular_com_imap_recusa_antes_de_conectar(api, monkeypatch):
    monkeypatch.setenv("EMAIL_ORIGEM", "imap")
    with pytest.raises(imap.FalhaIMAP, match="OAuth"):
        caixas.abrir(load_config(), rotular=True)
