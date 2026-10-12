"""API local do app desktop (`hermes serve`). Só escuta em 127.0.0.1.

Cada rota é uma casca fina sobre a mesma função de `hermes/domain` que a CLI chama: regra de
negócio não mora aqui. O token por execução impede que uma página qualquer aberta no navegador
chame `localhost` e grave no banco ou no vault.
"""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from hermes.agent.mcp_client import FalhaMCP
from hermes.api.chat import Confirmacoes, Paradas
from hermes.config import Config
from hermes.domain.atividade import AtividadeRecusada
from hermes.domain.candidaturas import CandidaturaRecusada
from hermes.domain.coletor import ColetaRecusada
from hermes.db import store
from hermes.domain import configuracao
from hermes.domain.configuracao import ConfiguracaoRecusada
from hermes.domain.competencias import RegraViolada
from hermes.domain.curriculo import SemFatos
from hermes.domain.estudos import EstudoRecusado
from hermes.domain.perfil import PerfilAusente
from hermes.domain.perfis_cv import PerfilInvalido
from hermes.domain.triagem_email import TriagemRecusada
from hermes.domain.vaga import VagaRecusada
from hermes.domain.curriculo import CurriculoRecusado
from hermes.llm import CostLimitError, FalhaLLM
from hermes.vault.indice import IndiceBloqueado, VaultSemCarreira
from hermes.vault.writer import EscritaRecusada

HEADER_TOKEN = "X-Hermes-Token"

# Origens do webview do Tauri (Linux/macOS e Windows) e do Vite em desenvolvimento.
ORIGENS = ("tauri://localhost", "http://tauri.localhost", "http://localhost:1420")

# Recusa do domínio: a mensagem já diz o que fazer, então vai para a tela como está.
RECUSAS = (
    RegraViolada, VagaRecusada, EstudoRecusado, AtividadeRecusada, ColetaRecusada, SemFatos,
    CandidaturaRecusada, EscritaRecusada, IndiceBloqueado, VaultSemCarreira, PerfilAusente, PerfilInvalido,
    CostLimitError, FalhaMCP, ConfiguracaoRecusada, TriagemRecusada, CurriculoRecusado,
)

ABERTAS = {"/api/saude"}


def criar_app(cfg: Config, token: str) -> FastAPI:
    if not token:
        raise ValueError("a API não sobe sem token")

    app = FastAPI(title="Hermes", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg = cfg
    app.state.token = token
    app.state.confirmacoes = Confirmacoes()
    app.state.paradas = Paradas()

    @app.middleware("http")
    async def exige_token(request: Request, call_next):
        if request.method != "OPTIONS" and request.url.path not in ABERTAS:
            enviado = request.headers.get(HEADER_TOKEN, "")
            if not hmac.compare_digest(enviado.encode(), token.encode()):
                return JSONResponse({"erro": "token ausente ou inválido"}, status_code=401)
        return await call_next(request)

    # adicionado depois do token para rodar antes dele: o preflight do CORS não leva header
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ORIGENS),
        allow_methods=["*"],
        allow_headers=[HEADER_TOKEN, "Content-Type"],
    )

    async def recusa(request: Request, exc: Exception):
        return JSONResponse({"erro": str(exc)}, status_code=422)

    for classe in RECUSAS:
        app.add_exception_handler(classe, recusa)

    async def falha_llm(request: Request, exc: Exception):
        # chave recusada em qualquer rota acende o aviso de Configurações; o aviso nunca derruba o erro
        if str(exc).startswith(configuracao.PREFIXO_RECUSA):
            try:
                conn = store.connect(request.app.state.cfg.db_path, uma_thread=False)
                try:
                    configuracao.marcar_recusa(conn, store.utcnow())
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
        # `codigo` diz à tela que a saída é configurar o LLM, não tentar de novo
        return JSONResponse({"erro": str(exc), "codigo": "llm"}, status_code=502)

    app.add_exception_handler(FalhaLLM, falha_llm)

    async def http(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"erro": exc.detail}, status_code=exc.status_code)

    app.add_exception_handler(StarletteHTTPException, http)

    @app.get("/api/saude")
    def saude() -> dict:
        return {"ok": True}

    from hermes.api.rotas import (
        candidaturas,
        chat,
        competencias,
        config,
        curriculos,
        emails,
        estudos,
        inicio,
        operacao,
        vagas,
    )

    for modulo in (inicio, config, chat, competencias, vagas, candidaturas, emails, curriculos, estudos, operacao):
        app.include_router(modulo.router)
    return app
