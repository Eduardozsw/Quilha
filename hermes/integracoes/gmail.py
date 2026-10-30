"""Gmail: a única parte do Hermes que fala com o Google. Credenciais em `HERMES_GMAIL_DIR`.

`credentials.json` (OAuth client do tipo Desktop) fica nessa pasta; os tokens são gravados lá na
primeira autorização. Só leitura por padrão; `rotular` pede o escopo de modificar.
"""

from __future__ import annotations

import base64
import html
import re
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_GRAVADO = 20000  # caracteres do corpo guardados no banco; ao Jev vão menos (triagem_email.MAX_CORPO)
SCOPES_LEITURA = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES_ROTULO = ["https://www.googleapis.com/auth/gmail.modify"]


class SemCredenciais(Exception):
    pass


_dormir = time.sleep  # trocado nos testes
TENTATIVAS = 5
_MOTIVOS_COTA = (b"rateLimitExceeded", b"userRateLimitExceeded", b"quotaExceeded")


def _estourou_cota(exc) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    conteudo = getattr(exc, "content", b"") or b""
    return status == 429 or (status == 403 and any(m in conteudo for m in _MOTIVOS_COTA))


def _com_retentativa(pedido):
    """Cota por minuto do Gmail: espera 1, 2, 4, 8 s e tenta de novo; outro erro sobe na hora."""
    from googleapiclient.errors import HttpError

    for tentativa in range(TENTATIVAS):
        try:
            return pedido()
        except HttpError as exc:
            if not _estourou_cota(exc) or tentativa == TENTATIVAS - 1:
                raise
            _dormir(2 ** tentativa)


def texto_de_html(texto: str) -> str:
    """HTML de e-mail vira texto com as quebras de parágrafo; script e style somem."""
    texto = re.sub(r"(?is)<(script|style).*?</\1>", " ", texto)
    texto = re.sub(r"(?i)<br\s*/?>", "\n", texto)
    texto = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table)>", "\n\n", texto)
    texto = re.sub(r"<[^>]+>", " ", texto)
    return html.unescape(texto)


def normalizar_corpo(texto: str) -> str:
    """Espaços somem, mas a quebra de parágrafo fica: a tela mostra o texto como a empresa escreveu."""
    texto = re.sub(r"[ \t\r\f\v\u00a0]+", " ", texto)
    texto = re.sub(r" *\n[ \n]*\n *", "\n\n", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    return texto.strip()[:MAX_GRAVADO]


def _texto_da_parte(parte) -> str:
    dados = parte.get("body", {}).get("data")
    if not dados:
        return ""
    texto = base64.urlsafe_b64decode(dados).decode("utf-8", errors="ignore")
    return texto_de_html(texto) if parte.get("mimeType") == "text/html" else texto


def extrair_corpo(payload) -> str:
    """Prefere text/plain; cai para text/html sem tags."""
    planos, htmls = [], []
    pilha = [payload]
    while pilha:
        p = pilha.pop()
        pilha.extend(p.get("parts", []) or [])
        if p.get("mimeType") == "text/plain":
            planos.append(_texto_da_parte(p))
        elif p.get("mimeType") == "text/html":
            htmls.append(_texto_da_parte(p))
    return normalizar_corpo("\n".join(planos) or "\n".join(htmls))


class CaixaGmail:
    def __init__(self, pasta: Path, rotular: bool = False):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        pasta = Path(pasta)
        scopes = SCOPES_ROTULO if rotular else SCOPES_LEITURA
        token = pasta / ("token_modify.json" if rotular else "token_readonly.json")
        creds = Credentials.from_authorized_user_file(str(token), scopes) if token.exists() else None
        novo = False
        if creds and not creds.valid and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                novo = True
            except RefreshError:
                # app OAuth em modo Testing: o refresh token expira em 7 dias; autoriza de novo
                creds = None
        if not creds or not creds.valid:
            segredo = pasta / "credentials.json"
            if not segredo.exists():
                raise SemCredenciais(
                    f"falta {segredo}. Crie um OAuth client (Desktop app) com a Gmail API ativa e salve lá."
                )
            creds = InstalledAppFlow.from_client_secrets_file(str(segredo), scopes).run_local_server(port=0)
            novo = True
        if novo:
            pasta.mkdir(parents=True, exist_ok=True)
            token.write_text(creds.to_json(), encoding="utf-8")
            token.chmod(0o600)  # guarda o refresh token do Gmail
        self._gmail = build("gmail", "v1", credentials=creds)
        self._labels: dict[str, str] | None = None

    def listar_ids(self, dias: int, maximo: int) -> list[str]:
        q = f"newer_than:{dias}d -in:chats -category:social"
        ids, pagina = [], None
        while len(ids) < maximo:
            resp = _com_retentativa(self._gmail.users().messages().list(
                userId="me", q=q, pageToken=pagina, maxResults=min(100, maximo - len(ids))).execute)
            ids += [m["id"] for m in resp.get("messages", [])]
            pagina = resp.get("nextPageToken")
            if not pagina:
                break
        return ids

    def ler(self, msg_id: str) -> dict:
        m = _com_retentativa(self._gmail.users().messages().get(userId="me", id=msg_id, format="full").execute)
        cab = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        recebido = datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc)
        return {
            "gmail_id": msg_id,
            "recebido_em": recebido.isoformat(timespec="seconds"),
            "de": cab.get("from", ""),
            "assunto": cab.get("subject", ""),
            "corpo": extrair_corpo(m["payload"]) or m.get("snippet", ""),
        }

    def rotular(self, msg_id: str, label: str) -> None:
        if self._labels is None:
            existentes = self._gmail.users().labels().list(userId="me").execute()["labels"]
            self._labels = {l["name"]: l["id"] for l in existentes}
        if label not in self._labels:
            criado = self._gmail.users().labels().create(userId="me", body={"name": label}).execute()
            self._labels[label] = criado["id"]
        _com_retentativa(self._gmail.users().messages().modify(
            userId="me", id=msg_id, body={"addLabelIds": [self._labels[label]]}).execute)
