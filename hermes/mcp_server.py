"""Servidor MCP do Quilha: as tools do registry para Claude Code, Cursor e Claude Desktop.

Um adaptador, não uma segunda implementação: lista e despacha as mesmas `Tool` do chat. Quem confirma
gravação é o cliente MCP — cada tool vai marcada como leitura ou escrita. Sem LLM próprio configurado,
a tool que precisa de modelo devolve o pedido ao modelo do cliente (`submit_draft`), e o Quilha valida a
resposta com o mesmo código que valida a do próprio modelo (ver `llm.respostas_externas`).
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from pathlib import Path

import mcp_types as types
from mcp.server import Server

from hermes import llm, runs
from hermes.agent.registry import TOOLS, Registry, Tool, erro, ok
from hermes.db import store
from hermes.domain import atividade, rascunhos, saude, vaga
from hermes.run_status import RunStatus
from hermes.vault import indice
from hermes.vault.check import load_denylist
from hermes.vault.reader import CAREER_DIR

log = logging.getLogger("quilha.mcp")

MODELO_CLIENTE = "cliente-mcp"
MAX_RODADAS = 4  # CV em PT e EN são 2; mais que isso é laço

INSTRUCOES = """O Quilha guarda a carreira do usuário: fatos do vault (cada um com uma `referencia`
nota.md#block-id), competências com nível 0–4 sustentado por evidência, vagas, candidaturas e estudos.

- Antes de afirmar qualquer coisa sobre a experiência do usuário, busque no vault (`vault_search_facts`) e
  cite a `referencia` de cada fato que usar. Não invente experiência, número ou ferramenta.
- O score de uma vaga é calculado pelo código: apresente-o com o número de requisitos, quantos foram
  mapeados e os obrigatórios descobertos, nunca sozinho.
- Commit é sinal, não estudo: use `git_activity` para perguntar o que a pessoa estudou e só registre
  (`confirm_study_signals`) com os minutos que ela disser.
- Quando uma tool devolver `"etapa": "aguardando_texto"`, escreva a resposta seguindo `instrucoes` com os
  dados de `entrada` e mande com `submit_draft` (mesmo `rascunho_id`). Responda só o objeto JSON pedido.
"""

AVISO_SEM_LLM = (
    "O Quilha não tem um modelo próprio configurado, então quem escreve esta parte é você, o modelo deste "
    "cliente. Siga `instrucoes`, use só o que está em `entrada` e mande o objeto JSON com `submit_draft`; o "
    "Quilha valida antes de gravar e descarta o que as regras não permitem. A qualidade do texto depende do "
    "seu modelo. Para o Quilha usar um modelo próprio: `quilha init`, ou LLM_MODEL e LLM_API_KEY no .env."
)

SUBMIT = Tool(
    nome="submit_draft",
    descricao=(
        "Segunda etapa de uma tool que devolveu `etapa: aguardando_texto`: manda a resposta escrita seguindo as "
        "`instrucoes` daquele pedido. O Quilha valida e grava, ou devolve o próximo pedido."
    ),
    parametros={
        "type": "object",
        "properties": {
            "rascunho_id": {"type": "string"},
            "resposta": {"type": "object", "description": "o objeto JSON que as instruções pedem"},
        },
        "required": ["rascunho_id", "resposta"],
    },
    funcao=lambda conn, **_: None,  # tratada no servidor: precisa do rascunho, não do registry
    escreve=True,
)


class Quilha:
    """Estado de um processo `quilha mcp serve`: a conexão, o gasto acumulado e o último índice."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.conn = store.connect(cfg.db_path)
        self.gasto = 0.0
        self.denylist = tuple(load_denylist(cfg.denylist_path))
        self.repos = tuple(atividade.descobrir_repos(cfg.repos_dir))
        self._assinatura_vault: tuple | None = None
        rascunhos.limpar_vencidos(self.conn)

    def sem_llm(self) -> bool:
        return saude._falta_llm(self.cfg)

    def tools(self) -> tuple[Tool, ...]:
        return TOOLS + ((SUBMIT,) if self.sem_llm() else ())

    def listar(self) -> list[types.Tool]:
        return [
            types.Tool(
                name=t.nome,
                description=t.descricao,
                input_schema=t.parametros,
                annotations=types.ToolAnnotations(read_only_hint=not t.escreve,
                                                  destructive_hint=False if t.escreve else None),
            )
            for t in self.tools()
        ]

    def chamar(self, nome: str, argumentos: dict) -> dict:
        if falta := self._falta_configurar():
            return erro("nao_configurado", falta)
        avisos = self._reindexar_se_mudou()
        if nome == SUBMIT.nome:
            resultado = self._submeter(argumentos)
        else:
            resultado = self._despachar(nome, argumentos, {})
        if avisos:
            resultado = {**resultado, "avisos": avisos + resultado.get("avisos", [])}
        return resultado

    # ------------------------------------------------------------------ internos

    def _falta_configurar(self) -> str | None:
        if not Path(self.cfg.vault_path).is_dir():
            return f"o vault {self.cfg.vault_path} não existe: rode `quilha init`"
        if not self.conn.execute("SELECT 1 FROM competencies LIMIT 1").fetchone():
            return "nenhuma competência cadastrada: rode `quilha init`"
        return None

    def _reindexar_se_mudou(self) -> list[str]:
        """O dev edita as notas no editor: antes de cada chamada, reindexa se algum .md de Carreira/ mudou."""
        carreira = Path(self.cfg.vault_path) / CAREER_DIR
        assinatura = tuple(sorted((str(p), p.stat().st_mtime_ns) for p in carreira.rglob("*.md"))) \
            if carreira.is_dir() else ()
        if assinatura == self._assinatura_vault:
            return []
        status = RunStatus()
        try:
            indice.reindexar(self.conn, Path(self.cfg.vault_path), list(self.denylist), status)
        except (indice.IndiceBloqueado, indice.VaultSemCarreira) as e:
            detalhe = "; ".join(p.mensagem for p in getattr(e, "bloqueios", [])) or str(e)
            return [f"índice do vault não atualizado ({detalhe}); as respostas usam o índice anterior"]
        self._assinatura_vault = assinatura
        return list(status.warnings)

    def _despachar(self, nome: str, argumentos: dict, respostas: dict, rascunho_id: str | None = None) -> dict:
        tool = next((t for t in TOOLS if t.nome == nome), None)
        sem_llm = self.sem_llm()
        if tool is not None and "model" in tool.injeta and not sem_llm and self.gasto >= self.cfg.max_cost_usd:
            return erro("teto_de_custo",
                        f"este servidor já gastou US$ {self.gasto:.4f} de US$ {self.cfg.max_cost_usd:.2f} "
                        "(HERMES_MAX_COST_USD); reinicie o servidor ou aumente o teto")
        ex = runs.Execucao(self.conn, f"mcp {nome}")
        ex.model = MODELO_CLIENTE if sem_llm else self.cfg.llm_model
        registry = Registry(conn=self.conn, tools=TOOLS, status=ex.status, model=ex.model,
                            denylist=self.denylist, repos_conhecidos=self.repos, cfg=self.cfg)
        try:
            with llm.respostas_externas(respostas) if sem_llm else nullcontext():
                resultado = registry.dispatch(nome, argumentos)
            ex.delivered = resultado["ok"]
        except llm.PrecisaDeTexto as pedido:
            ex.delivered = True
            resultado = ok(self._pedir_texto(nome, argumentos, respostas, pedido, rascunho_id))
        except Exception as e:  # noqa: BLE001 — bug de uma tool não derruba o servidor
            ex.crashed, ex.erro = True, str(e)
            log.exception("tool %s falhou", nome)
            resultado = erro("erro_interno", f"{type(e).__name__}: {e} (detalhes no log do servidor MCP)")
        finally:
            runs.gravar(ex)
            self.gasto += ex.status.cost_usd or 0.0
        if ex.status.warnings:  # o que a validação descartou e por quê: o modelo do cliente precisa ver
            resultado = {**resultado, "avisos": list(ex.status.warnings)}
        return resultado

    def _pedir_texto(self, nome, argumentos, respostas, pedido: llm.PrecisaDeTexto, rascunho_id) -> dict:
        if rascunho_id is None:
            rascunho_id = rascunhos.criar(self.conn, nome, argumentos, pedido.chave, respostas)
        else:
            rascunhos.atualizar(self.conn, rascunho_id, pedido.chave, respostas)
        dados = {"etapa": "aguardando_texto", "rascunho_id": rascunho_id, "aviso": AVISO_SEM_LLM,
                 "instrucoes": pedido.system, "entrada": pedido.user, "responda_com": SUBMIT.nome,
                 "esquema": pedido.contrato.esquema if pedido.contrato is not None else None}
        if nome == "match_job" and not respostas:
            # o score é do código: grava já, o texto de lacunas e riscos vem na segunda etapa
            dados["resultado_parcial"] = vaga.match_job(self.conn, argumentos["job_id"], redigir=False)
        return dados

    def _submeter(self, argumentos: dict) -> dict:
        resposta = argumentos.get("resposta")
        if not isinstance(resposta, dict):
            return erro("argumentos_invalidos", "`resposta` é o objeto JSON que as `instrucoes` pedem")
        try:
            rascunho = rascunhos.buscar(self.conn, str(argumentos.get("rascunho_id")))
        except rascunhos.RascunhoInvalido as e:
            return erro("rascunho_invalido", str(e))
        respostas = {**rascunho["respostas"], rascunho["pendente"]: json.dumps(resposta, ensure_ascii=False)}
        if len(respostas) > MAX_RODADAS:
            rascunhos.apagar(self.conn, rascunho["id"])
            return erro("rascunho_invalido", "rodadas demais neste rascunho: chame a tool de novo")
        resultado = self._despachar(rascunho["tool"], rascunho["argumentos"], respostas, rascunho["id"])
        aguardando = resultado["ok"] and isinstance(resultado["data"], dict) \
            and resultado["data"].get("etapa") == "aguardando_texto"
        corrigivel = not resultado["ok"] and resultado["error"]["code"] == "resposta_invalida"
        if corrigivel:
            resultado["error"]["message"] += f" — corrija e mande de novo com o mesmo rascunho_id ({rascunho['id']})"
        if not aguardando and not corrigivel:
            rascunhos.apagar(self.conn, rascunho["id"])
        return resultado


def para_mcp(resultado: dict) -> types.CallToolResult:
    """`{"ok": true}` vira resultado (texto + estruturado); `{"ok": false}` vira erro da tool com o código."""
    if resultado["ok"]:
        texto = json.dumps(resultado["data"], ensure_ascii=False, default=str)
        dados = json.loads(texto)
        conteudo = [types.TextContent(type="text", text=texto)]
        if resultado.get("avisos"):
            conteudo.append(types.TextContent(type="text", text="avisos: " + " | ".join(resultado["avisos"])))
        return types.CallToolResult(content=conteudo,
                                    structured_content=dados if isinstance(dados, dict) else {"result": dados})
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(resultado["error"], ensure_ascii=False))],
        is_error=True,
    )


def _versao() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("quilha")
    except PackageNotFoundError:
        return "0.0.0"


def criar_servidor(cfg) -> Server:
    quilha = Quilha(cfg)

    async def listar(ctx, params):
        return types.ListToolsResult(tools=quilha.listar())

    async def chamar(ctx, params):
        return para_mcp(quilha.chamar(params.name, dict(params.arguments or {})))

    return Server("quilha", version=_versao(), instructions=INSTRUCOES,
                  on_list_tools=listar, on_call_tool=chamar)


def servir(cfg) -> None:
    """stdio até o cliente fechar. Log em `data/mcp-serve.log`: o stdout é do protocolo."""
    import anyio
    from mcp.server.stdio import stdio_server

    destino = Path(cfg.db_path).parent / "mcp-serve.log"
    destino.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=destino, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    servidor = criar_servidor(cfg)

    async def rodar():
        # o SDK aponta o fd 1 para o stderr enquanto serve: print de biblioteca não chega ao protocolo
        async with stdio_server() as (leitura, escrita):
            await servidor.run(leitura, escrita, servidor.create_initialization_options())

    anyio.run(rodar)
