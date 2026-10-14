"""Turno de chat fora do terminal: o mesmo `loop.responder`, com eventos em vez de `print`.

O turno roda numa thread e fala com quem assiste por `emitir(tipo, dados)` — na API, isso vira
evento SSE. Gravação que pede confirmação para o turno até você clicar: `Confirmacoes.pedir`
espera a resposta e, sem ela no prazo, conta como recusa (nada é gravado por omissão).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Callable

from hermes import runs
from hermes.agent import loop, mcp_client
from hermes.agent import session as agent_session
from hermes.agent.registry import TOOLS, Registry, Tool
from hermes.api import conversa
from hermes.config import Config
from hermes.db import store
from hermes.domain import atividade, configuracao
from hermes.llm import FalhaLLM
from hermes.vault.check import load_denylist

Emitir = Callable[[str, dict], None]

TIMEOUT_CONFIRMACAO_S = 300


class Confirmacoes:
    """Pedidos de gravação esperando clique. Uma instância por processo da API."""

    def __init__(self, timeout: float = TIMEOUT_CONFIRMACAO_S):
        self.timeout = timeout
        self._pendentes: dict[str, dict] = {}
        self._trava = threading.Lock()

    def pedir(self, emitir: Emitir, tool: Tool, argumentos: dict, sessao_id: int | None = None) -> bool:
        return self.pedir_resultado(emitir, tool, argumentos, sessao_id)[1] == "aprovado"

    def pedir_resultado(self, emitir: Emitir, tool: Tool, argumentos: dict, sessao_id: int | None = None,
                        extra: dict | None = None, parar: threading.Event | None = None) -> tuple[str, str]:
        """(id do pedido, "aprovado" | "recusado" | "expirou"). `extra` vai junto no evento `confirmar`.

        Com `parar` já ligado, o pedido sai recusado sem esperar: o Parar pode ter chegado entre a última
        checagem do loop e o registro do pedido, e aí `cancelar_da_sessao` não o alcançou."""
        pedido = {"evento": threading.Event(), "aprovado": False, "sessao_id": sessao_id}
        chave = uuid.uuid4().hex
        with self._trava:
            self._pendentes[chave] = pedido
        if parar is not None and parar.is_set():
            with self._trava:
                self._pendentes.pop(chave, None)
            return chave, "recusado"
        try:
            emitir("confirmar", {"id": chave, "tool": tool.nome, "argumentos": argumentos,
                                 "expira_em_s": self.timeout, **(extra or {})})
            if not pedido["evento"].wait(self.timeout):
                return chave, "expirou"
            return chave, "aprovado" if pedido["aprovado"] else "recusado"
        finally:
            with self._trava:
                self._pendentes.pop(chave, None)

    def responder(self, chave: str, aprovar: bool) -> bool:
        """False quando o pedido não existe mais (expirou, já foi respondido ou o Parar recusou)."""
        with self._trava:  # o primeiro que resolve vale: um "Gravar" atrasado não desfaz o Parar
            pedido = self._pendentes.get(chave)
            if pedido is None or pedido["evento"].is_set():
                return False
            pedido["aprovado"] = aprovar
            pedido["evento"].set()
        return True

    def cancelar_da_sessao(self, sessao_id: int) -> int:
        """O "Parar": os pedidos pendentes da sessão viram recusa na hora. Devolve quantos."""
        n = 0
        with self._trava:
            for pedido in self._pendentes.values():
                if pedido["sessao_id"] == sessao_id and not pedido["evento"].is_set():
                    pedido["aprovado"] = False
                    pedido["evento"].set()
                    n += 1
        return n


class Paradas:
    """O botão "Parar" de cada turno rodando, por sessão. Uma instância por processo da API."""

    def __init__(self):
        self._eventos: dict[int, threading.Event] = {}
        self._trava = threading.Lock()

    def iniciar(self, sessao_id: int) -> threading.Event | None:
        """None quando já há um turno rodando nessa sessão: dois turnos juntos quebrariam o histórico."""
        evento = threading.Event()
        with self._trava:
            if sessao_id in self._eventos:
                return None
            self._eventos[sessao_id] = evento
        return evento

    def apagar_parada(self, sessao_id: int, apagar: Callable[[], None]) -> bool:
        """Apaga só se não há turno rodando, segurando a trava: nenhum turno começa no meio do apagar."""
        with self._trava:
            if sessao_id in self._eventos:
                return False
            apagar()
        return True

    def rodando(self, sessao_id: int) -> bool:
        with self._trava:
            return sessao_id in self._eventos

    def parar(self, sessao_id: int) -> bool:
        """False quando não há turno rodando nessa sessão."""
        with self._trava:
            evento = self._eventos.get(sessao_id)
        if evento is None:
            return False
        evento.set()
        return True

    def terminar(self, sessao_id: int, evento: threading.Event | None = None) -> None:
        with self._trava:
            if evento is None or self._eventos.get(sessao_id) is evento:
                self._eventos.pop(sessao_id, None)


def abrir_sessao(conn: sqlite3.Connection, model: str) -> int:
    return agent_session.abrir(conn, model).id


TITULO_LIMITE = 40


def titulo_automatico(texto: str, limite: int = TITULO_LIMITE) -> str:
    """A primeira pergunta como título: cortada no fim de uma palavra, com "…". Sem LLM."""
    limpo = " ".join(texto.split())
    if len(limpo) <= limite:
        return limpo
    corte = limpo[: limite + 1].rfind(" ")
    if corte <= 0:  # uma palavra só maior que o limite: corta duro
        return limpo[:limite] + "…"
    return limpo[:corte].rstrip(" ,.;:") + "…"


_SESSOES_SQL = (
    "SELECT s.id, s.started_at, s.finished_at, s.model, s.cost_usd, s.titulo AS titulo_editado,"
    "  (SELECT content FROM agent_messages m WHERE m.session_id = s.id AND m.role = 'user'"
    "   ORDER BY idx LIMIT 1) AS primeira,"
    "  (SELECT COUNT(*) FROM agent_messages m WHERE m.session_id = s.id) AS n_mensagens"
    " FROM agent_sessions s"
)


def _sessao(linha: sqlite3.Row) -> dict:
    d = dict(linha)
    editado, primeira = d.pop("titulo_editado"), d.pop("primeira")
    d["titulo"] = editado or (titulo_automatico(primeira) if primeira else None)
    return d


def listar_sessoes(conn: sqlite3.Connection, limite: int = 50) -> list[dict]:
    return [_sessao(r) for r in conn.execute(_SESSOES_SQL + " ORDER BY s.id DESC LIMIT ?", (limite,))]


def renomear(conn: sqlite3.Connection, sessao_id: int, titulo: str | None) -> dict:
    """Título vazio (ou None) volta ao automático."""
    limpo = " ".join((titulo or "").split()) or None
    with conn:
        cur = conn.execute("UPDATE agent_sessions SET titulo = ? WHERE id = ?", (limpo, sessao_id))
    if cur.rowcount == 0:
        raise SessaoInexistente(f"sessão {sessao_id} não existe")
    return _sessao(conn.execute(_SESSOES_SQL + " WHERE s.id = ?", (sessao_id,)).fetchone())


def apagar(conn: sqlite3.Connection, sessao_id: int) -> None:
    """Apaga a conversa e as mensagens (cascata); as execuções ficam, sem a ligação com ela."""
    with conn:
        cur = conn.execute("DELETE FROM agent_sessions WHERE id = ?", (sessao_id,))
    if cur.rowcount == 0:
        raise SessaoInexistente(f"sessão {sessao_id} não existe")


def mensagens(conn: sqlite3.Connection, sessao_id: int) -> list[dict]:
    if conn.execute("SELECT 1 FROM agent_sessions WHERE id = ?", (sessao_id,)).fetchone() is None:
        raise SessaoInexistente(f"sessão {sessao_id} não existe")
    historico = agent_session.Session(conn=conn, id=sessao_id).mensagens_com_meta()
    for m in historico:  # a linha de ferramenta do histórico, nos mesmos rótulos do turno ao vivo
        if m.get("tool_calls"):
            m["ferramentas"] = [{"nome": c["function"]["name"],
                                 "rotulo": conversa.rotulo_ferramenta(c["function"]["name"])}
                                for c in m["tool_calls"]]
    return historico


class SessaoInexistente(Exception):
    pass


def _tipo_do_erro(exc: Exception) -> str:
    if isinstance(exc, FalhaLLM):
        return "chave" if str(exc).startswith(configuracao.PREFIXO_RECUSA) else "llm"
    return "outro"


class _Fio:
    """Enriquece os eventos do loop para a tela e junta o `meta` da resposta: rótulo de ferramenta,
    cartão de confirmação legível e o resultado de cada confirmação (gravado, recusado, expirou)."""

    def __init__(self, conn: sqlite3.Connection, emitir: Emitir, confirmacoes: Confirmacoes,
                 parar: threading.Event | None = None):
        self.conn, self._emitir, self.confirmacoes, self.parar = conn, emitir, confirmacoes, parar
        self.ferramentas: list[dict] = []
        self.resolvidas: list[dict] = []
        self._aprovada: tuple[str, dict] | None = None  # (id, cartão) esperando o resultado da ferramenta
        self._cancelada = False

    def emitir(self, tipo: str, dados: dict) -> None:
        if tipo == "tool":
            dados = {**dados, "rotulo": conversa.rotulo_ferramenta(dados["nome"])}
        elif tipo == "tool_resultado":
            if self._cancelada:
                dados = {**dados, "cancelada": True}
                self._cancelada = False
            self.ferramentas.append({k: dados[k] for k in ("nome", "ok", "cancelada") if k in dados})
            self._emitir(tipo, dados)
            if self._aprovada is not None:
                chave, cartao = self._aprovada
                self._aprovada = None
                self._resolver(chave, cartao, "gravado" if dados["ok"] else "falhou")
            return
        self._emitir(tipo, dados)

    def confirmar(self, sessao_id: int, tool: Tool, argumentos: dict) -> bool:
        cartao = conversa.confirmacao(self.conn, tool.nome, argumentos)
        extra = {k: cartao[k] for k in ("titulo", "campos", "resumo", "objeto", "linhas")}
        cartao["ferramenta"] = tool.nome
        chave, resultado = self.confirmacoes.pedir_resultado(self._emitir, tool, argumentos, sessao_id, extra,
                                                             parar=self.parar)
        if resultado == "aprovado":
            self._aprovada = (chave, cartao)
            return True
        self._cancelada = True
        self._resolver(chave, cartao, resultado)
        return False

    def _resolver(self, chave: str, cartao: dict, resultado: str) -> None:
        linha = cartao["linhas"][resultado]
        self.resolvidas.append({"objeto": cartao["objeto"], "resumo": cartao["resumo"],
                                "resultado": resultado, "linha": linha, "ferramenta": cartao["ferramenta"]})
        self._emitir("confirmacao_resolvida", {"id": chave, "resultado": resultado, "linha": linha})


def rodar_turno(cfg: Config, sessao_id: int, texto: str, confirmacoes: Confirmacoes,
                emitir: Emitir, parar: threading.Event | None = None) -> None:
    """Um turno inteiro. Termina sempre com um evento `fim` ou `erro` — nunca levanta."""
    conn = store.connect(cfg.db_path)
    model = cfg.llm_model
    fio = _Fio(conn, emitir, confirmacoes, parar)
    try:
        with runs.registrando(conn, "chat") as ex:
            ex.model = model
            sessao = agent_session.continuar(conn, sessao_id)
            ex.session_id = sessao.id
            anterior = conn.execute(
                "SELECT cost_usd FROM agent_sessions WHERE id = ?", (sessao.id,)
            ).fetchone()["cost_usd"]
            remotas = mcp_client.remotas_da_config(cfg.mcp_path, cfg.db_path.parent, ex.status)
            registry = Registry(
                tools=TOOLS + tuple(remotas),
                conn=conn,
                confirmar=lambda tool, args: fio.confirmar(sessao.id, tool, args),
                status=ex.status,
                model=model,
                denylist=tuple(load_denylist(cfg.denylist_path)),
                repos_conhecidos=tuple(atividade.descobrir_repos(cfg.repos_dir)),
                cfg=cfg,
                sem_confirmacao=cfg.sem_confirmacao,
            )
            loop.descartar_parcial(sessao, texto)
            inicio = sessao.proximo_idx
            turno = loop.responder(sessao, registry, texto, status=ex.status,
                                   teto_usd=cfg.max_cost_usd, model=model, on_evento=fio.emitir,
                                   parar=parar)
            ex.delivered = turno.completo or turno.parou_por == "parado"

            do_turno = ex.status.cost_usd
            acumulado = None if do_turno is None else (anterior or 0.0) + do_turno
            sessao.fechar(model, acumulado)
            cartoes = conversa.cartoes(conn, turno.resultados)
            sessao.anotar_turno(inicio, {
                "custo_usd": do_turno, "cartoes": cartoes, "confirmacoes": fio.resolvidas,
                "ferramentas": fio.ferramentas, "parado": turno.parou_por == "parado",
            })
        if turno.parou_por == "teto_custo":
            emitir("erro", {"tipo": "teto", "mensagem": ex.status.warnings[-1] if ex.status.warnings
                            else "teto de custo atingido", "erro": "teto de custo atingido",
                            "gasto_usd": do_turno, "teto_usd": cfg.max_cost_usd})
            return
        emitir("fim", {
            "resposta": turno.resposta,
            "parou_por": turno.parou_por,
            "custo": {"llm_calls": ex.status.llm_calls,
                      "tokens": ex.status.prompt_tokens + ex.status.completion_tokens,
                      "custo_usd": do_turno, "sessao_usd": acumulado,
                      "teto_usd": cfg.max_cost_usd},
            "cartoes": cartoes,
            "titulo": _sessao(conn.execute(_SESSOES_SQL + " WHERE s.id = ?", (sessao.id,)).fetchone())["titulo"],
            "avisos": list(ex.status.warnings),
        })
    except Exception as exc:  # noqa: BLE001 — quem assiste precisa saber que o turno acabou
        # o turno engole a exceção para emitir `erro`: a recusa da chave acende o status de Configurações aqui
        tipo = _tipo_do_erro(exc)
        if tipo == "chave":
            try:
                configuracao.marcar_recusa(conn, store.utcnow())
            except Exception:  # noqa: BLE001
                pass
        emitir("erro", {"tipo": tipo, "mensagem": str(exc), "erro": f"{type(exc).__name__}: {exc}"})
    finally:
        conn.close()
