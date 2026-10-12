"""E-mail por IMAP com senha de app: a alternativa ao OAuth do Gmail que não exige Google Cloud.

Mesma interface da `CaixaGmail` (`listar_ids`, `ler`), só leitura: a pasta é aberta em modo
`readonly`, então nada é marcado como lido. Labels só existem pelo OAuth — aqui `rotular` recusa.

No Gmail, o id de cada e-mail é o `X-GM-MSGID` em hexadecimal, o mesmo da Gmail API: quem troca do
OAuth para o IMAP não reclassifica (nem paga de novo) o que já estava no banco.
"""

from __future__ import annotations

import email
import imaplib
import re
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from hermes.integracoes.gmail import normalizar_corpo, texto_de_html

PORTA = 993
TIMEOUT = 30  # segundos para conectar


class FalhaIMAP(Exception):
    """Login recusado, servidor fora ou pasta inexistente. A mensagem diz o que conferir."""


def _cabecalho(valor: str | None) -> str:
    return str(make_header(decode_header(valor))) if valor else ""


def _corpo(msg: email.message.Message) -> str:
    planos, htmls = [], []
    for parte in msg.walk():
        if parte.is_multipart() or parte.get_content_disposition() == "attachment":
            continue
        tipo = parte.get_content_type()
        if tipo not in ("text/plain", "text/html"):
            continue
        dados = parte.get_payload(decode=True) or b""
        texto = dados.decode(parte.get_content_charset() or "utf-8", errors="ignore")
        (planos if tipo == "text/plain" else htmls).append(texto if tipo == "text/plain" else texto_de_html(texto))
    return normalizar_corpo("\n".join(planos) or "\n".join(htmls))


class CaixaIMAP:
    def __init__(self, host: str, usuario: str, senha: str, pasta: str = "INBOX", porta: int = PORTA):
        if not (host and usuario and senha):
            raise FalhaIMAP("faltam servidor, e-mail ou senha de app do IMAP. Configure em Configurações → E-mail.")
        self.host, self.pasta = host, pasta
        try:
            self._m = imaplib.IMAP4_SSL(host, porta, timeout=TIMEOUT)
            self._m.login(usuario, senha)
        except imaplib.IMAP4.error as exc:
            raise FalhaIMAP(
                f"o servidor recusou o login ({exc}). Confira o e-mail e use uma senha de app, não a senha normal."
            ) from None
        except OSError as exc:
            raise FalhaIMAP(f"não consegui conectar em {host}:{porta} ({exc}).") from None
        status, _ = self._m.select(f'"{pasta}"', readonly=True)
        if status != "OK":
            raise FalhaIMAP(f"a pasta {pasta!r} não existe no servidor.")
        self._gmail = b"X-GM-EXT-1" in {c if isinstance(c, bytes) else c.encode() for c in self._m.capabilities}
        _, dados = self._m.response("UIDVALIDITY")
        self._validade = (dados[0] or b"0").decode() if dados and dados[0] else "0"
        self._uid_por_id: dict[str, bytes] = {}

    def listar_ids(self, dias: int, maximo: int) -> list[str]:
        """Mais novo primeiro, como a Gmail API."""
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        status, dados = self._m.uid("SEARCH", None, f"SINCE {desde}")
        if status != "OK":
            raise FalhaIMAP(f"a busca no IMAP falhou: {dados!r}")
        uids = (dados[0] or b"").split()[::-1][:maximo]
        ids = []
        if self._gmail and uids:
            _, resp = self._m.uid("FETCH", b",".join(uids).decode(), "(X-GM-MSGID)")
            por_uid = {}
            for item in resp:
                linha = item[0] if isinstance(item, tuple) else item
                achado = re.search(rb"X-GM-MSGID (\d+).*?UID (\d+)|UID (\d+).*?X-GM-MSGID (\d+)", linha or b"")
                if achado:
                    msgid, uid = (achado.group(1), achado.group(2)) if achado.group(1) else (achado.group(4), achado.group(3))
                    por_uid[uid] = format(int(msgid), "x")
            for uid in uids:
                ids.append(por_uid.get(uid) or f"imap:{self.host}:{self._validade}:{uid.decode()}")
                self._uid_por_id[ids[-1]] = uid
        else:
            for uid in uids:
                ids.append(f"imap:{self.host}:{self._validade}:{uid.decode()}")
                self._uid_por_id[ids[-1]] = uid
        return ids

    def ler(self, msg_id: str) -> dict:
        uid = self._uid_por_id.get(msg_id)
        if uid is None:
            raise FalhaIMAP(f"e-mail {msg_id} não foi listado nesta sessão")
        status, dados = self._m.uid("FETCH", uid.decode(), "(INTERNALDATE BODY.PEEK[])")
        if status != "OK" or not dados or not isinstance(dados[0], tuple):
            raise FalhaIMAP(f"não consegui ler o e-mail {msg_id}")
        msg = email.message_from_bytes(dados[0][1])
        quando = imaplib.Internaldate2tuple(dados[0][0])  # hora local do processo
        if quando:
            recebido = datetime.fromtimestamp(time.mktime(quando), timezone.utc)
        else:
            recebido = parsedate_to_datetime(msg["Date"]).astimezone(timezone.utc)
        return {
            "gmail_id": msg_id,
            "recebido_em": recebido.isoformat(timespec="seconds"),
            "de": _cabecalho(msg["From"]),
            "assunto": _cabecalho(msg["Subject"]),
            "corpo": _corpo(msg),
        }

    def rotular(self, msg_id: str, label: str) -> None:
        raise FalhaIMAP("labels só existem pela conexão OAuth com o Gmail; no IMAP o Quilha só lê.")

    def contar_recentes(self, dias: int = 7) -> int:
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        _, dados = self._m.uid("SEARCH", None, f"SINCE {desde}")
        return len((dados[0] or b"").split())

    def fechar(self) -> None:
        try:
            self._m.logout()
        except Exception:  # noqa: BLE001 — fechar nunca derruba quem chamou
            pass
