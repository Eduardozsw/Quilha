"""Confere se a instalação funciona, sem LLM e sem tocar no banco real: schema, PDF e caminhos.

Serve de teste de fumaça do binário congelado (o que o PyInstaller esquece só aparece rodando) e de
primeiro passo de qualquer relato de problema.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from hermes import caminhos
from hermes.config import Config

EXEMPLO_CV = {
    "idioma": "pt", "nome": "Fulano de Tal", "cargo": "Desenvolvedor", "resumo": "Diagnóstico do Quilha.",
    "contato": [{"texto": "fulano@exemplo.com", "url": "mailto:fulano@exemplo.com"}],
    "idiomas": ["Português (nativo)"],
    "experiencias": [],
    "projetos": [{"entidade": "exemplo", "titulo": "Projeto Exemplo", "subtitulo": "", "cargo": "",
                  "periodo": "", "local": "", "stack": ["Python"], "link": None,
                  "bullets": [{"texto": "Escreveu um script com 12 testes, medidos em 01/2026.",
                               "origem": "^exemplo @ Exemplo.md", "referencia": "Exemplo.md#exemplo"}]}],
    "habilidades": [{"rotulo": "Backend", "itens": ["Python"]}],
    "formacao": [],
}


def rodar(cfg: Config) -> list[dict]:
    """Cada item: `{"item", "ok", "detalhe"}`. Só schema e PDF derrubam; o resto é informação."""
    from hermes.db import store
    from hermes.domain import curriculo, pdf

    itens = [
        {"item": "versão do Python", "ok": True, "detalhe": sys.version.split()[0]},
        {"item": "modo", "ok": True, "detalhe": "app instalado" if caminhos.congelado() else "código-fonte"},
        {"item": "base", "ok": True, "detalhe": str(caminhos.base())},
        {"item": "vault", "ok": True,
         "detalhe": f"{cfg.vault_path} ({'existe' if Path(cfg.vault_path).is_dir() else 'não existe'})"},
    ]
    with tempfile.TemporaryDirectory(prefix="quilha-diagnostico-") as tmp:
        try:
            conn = store.connect(Path(tmp) / "teste.db")
            versao = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.close()
            itens.append({"item": "schema do banco", "ok": True, "detalhe": f"aplicado (user_version {versao})"})
        except Exception as e:  # noqa: BLE001 — o diagnóstico mostra qualquer falha, não decide
            itens.append({"item": "schema do banco", "ok": False, "detalhe": f"{type(e).__name__}: {e}"})
        try:
            estrutura = {**EXEMPLO_CV, "rotulos": curriculo.SECOES["pt"]}
            resultado = pdf.compilar(estrutura, Path(tmp) / "cv.pdf")
            itens.append({"item": "PDF (Typst e fontes)", "ok": True,
                          "detalhe": f"{resultado['paginas']} página(s)"})
        except Exception as e:  # noqa: BLE001
            itens.append({"item": "PDF (Typst e fontes)", "ok": False, "detalhe": f"{type(e).__name__}: {e}"})
    return itens
