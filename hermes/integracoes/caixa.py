"""Qual caixa de e-mail o sync usa: `EMAIL_ORIGEM=gmail` (OAuth próprio, padrão) ou `imap` (senha de app)."""

from __future__ import annotations

import os

from hermes.config import Config
from hermes.integracoes.gmail import SemCredenciais
from hermes.integracoes.imap import FalhaIMAP

ORIGENS = ("gmail", "imap")
IMAP_HOST_PADRAO = "imap.gmail.com"
# o que quem chama precisa capturar: credencial ausente, login recusado, servidor fora
Indisponivel = (SemCredenciais, FalhaIMAP)


def origem() -> str:
    return (os.getenv("EMAIL_ORIGEM") or "gmail").strip().lower()


def abrir(cfg: Config, rotular: bool = False):
    if origem() == "imap":
        from hermes.integracoes.imap import CaixaIMAP

        if rotular:
            raise FalhaIMAP("labels só existem pela conexão OAuth com o Gmail; no IMAP o Quilha só lê.")
        return CaixaIMAP(os.getenv("IMAP_HOST") or IMAP_HOST_PADRAO, os.getenv("IMAP_USUARIO", ""),
                         os.getenv("IMAP_SENHA", ""))
    if origem() != "gmail":
        raise FalhaIMAP(f"EMAIL_ORIGEM={origem()!r}: use `gmail` ou `imap`.")
    from hermes.integracoes.gmail import CaixaGmail

    return CaixaGmail(cfg.gmail_dir, rotular=rotular)


def testar(cfg: Config) -> dict:
    """Conecta e conta os e-mails dos últimos 7 dias, sem classificar nada (custo zero)."""
    try:
        caixa = abrir(cfg)
        n = caixa.contar_recentes(7) if hasattr(caixa, "contar_recentes") else len(caixa.listar_ids(7, 500))
    except Indisponivel as exc:
        return {"ok": False, "origem": origem(), "mensagem": str(exc)}
    finally:
        if "caixa" in locals() and hasattr(caixa, "fechar"):
            caixa.fechar()
    return {"ok": True, "origem": origem(), "mensagem": f"Conectado: {n} e-mail(s) nos últimos 7 dias."}
