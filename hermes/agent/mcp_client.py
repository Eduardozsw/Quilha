"""Cliente MCP: tools de servidores externos entram no mesmo registry das tools locais.

Um servidor é um comando que fala MCP por stdio (ex.: um servidor de notícias com `news_today` e
`search_news`). O Hermes descobre as tools dele na abertura do chat e registra **só as da
allowlist** de `mcp.yaml` — servidor externo não ganha acesso ao agente por ter tool nova.

Cada chamada abre o processo, faz o handshake, chama e fecha. Custa ~1 s por chamada, mas não
deixa processo órfão nem sessão presa se o chat cair; para `news_today` uma vez por conversa, é o
preço certo. O stderr do servidor vai para `data/mcp-<nome>.log`, não para o terminal do chat.

Tool remota é tratada como leitura: o Hermes não sabe o que ela faz do outro lado. Por isso a
allowlist é obrigatória e explícita (não existe "todas").
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from hermes.agent.registry import TOOLS, Tool

TIMEOUT_PADRAO = 20.0


class FalhaMCP(Exception):
    """Servidor não subiu, não respondeu a tempo ou a tool devolveu erro."""


class ConfigMCPInvalida(Exception):
    """`mcp.yaml` com erro. A mensagem diz o que corrigir."""


@dataclass(frozen=True)
class Servidor:
    nome: str
    comando: tuple[str, ...]
    tools: tuple[str, ...]  # allowlist
    cwd: Path | None = None
    timeout: float = TIMEOUT_PADRAO


def carregar(caminho: Path) -> list[Servidor]:
    """Lê `mcp.yaml`. Arquivo ausente = nenhum servidor (MCP é opcional)."""
    caminho = Path(caminho)
    if not caminho.is_file():
        return []
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    servidores, nomes = [], set()
    for i, item in enumerate(dados.get("servidores") or [], 1):
        if not isinstance(item, dict):
            raise ConfigMCPInvalida(f"servidor {i}: esperado um mapa")
        nome = str(item.get("nome") or "").strip()
        comando = item.get("comando")
        tools = item.get("tools")
        if not nome or nome in nomes:
            raise ConfigMCPInvalida(f"servidor {i}: `nome` ausente ou repetido")
        if not isinstance(comando, list) or not comando or not all(isinstance(c, str) for c in comando):
            raise ConfigMCPInvalida(f"servidor `{nome}`: `comando` deve ser uma lista, ex: [uv, run, ...]")
        if not isinstance(tools, list) or not tools:
            raise ConfigMCPInvalida(
                f"servidor `{nome}`: `tools` é obrigatório e explícito — liste as tools permitidas"
            )
        nomes.add(nome)
        cwd = item.get("cwd")
        servidores.append(Servidor(
            nome=nome,
            comando=tuple(str(Path(c).expanduser()) if c.startswith("~") else c for c in comando),
            tools=tuple(str(t) for t in tools),
            cwd=Path(cwd).expanduser() if cwd else None,
            timeout=float(item.get("timeout_s", TIMEOUT_PADRAO)),
        ))
    return servidores


# ------------------------------------------------------------------ protocolo


async def _com_cliente(servidor: Servidor, log: Path, operacao):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    parametros = StdioServerParameters(
        command=servidor.comando[0],
        args=list(servidor.comando[1:]),
        cwd=servidor.cwd,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as errlog:
        async with Client(stdio_client(parametros, errlog=errlog),
                          read_timeout_seconds=servidor.timeout) as cliente:
            return await operacao(cliente)


def _rodar(servidor: Servidor, log: Path, operacao):
    """Ponte síncrona: o loop do agente é síncrono, o SDK é assíncrono."""
    try:
        return asyncio.run(asyncio.wait_for(_com_cliente(servidor, log, operacao), servidor.timeout))
    except FalhaMCP:
        raise
    except TimeoutError:
        raise FalhaMCP(f"`{servidor.nome}` não respondeu em {servidor.timeout:.0f} s") from None
    except Exception as e:  # processo que não sobe, handshake que falha, protocolo quebrado
        detalhe = f"{type(e).__name__}: {e}".strip()
        raise FalhaMCP(f"`{servidor.nome}` falhou ({detalhe}); detalhes em {log}") from None


def _resultado(nome: str, resultado) -> object:
    if resultado.is_error:
        texto = " ".join(getattr(c, "text", "") for c in resultado.content).strip()
        raise FalhaMCP(f"`{nome}` devolveu erro: {texto or 'sem mensagem'}")
    if resultado.structured_content is not None:
        estruturado = resultado.structured_content
        # o SDK embrulha retorno que não é objeto em {"result": ...}
        if isinstance(estruturado, dict) and set(estruturado) == {"result"}:
            return estruturado["result"]
        return estruturado
    textos = [getattr(c, "text", None) for c in resultado.content]
    texto = "\n".join(t for t in textos if t)
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return texto


def listar_tools(servidor: Servidor, log: Path) -> list:
    async def operacao(cliente):
        return (await cliente.list_tools()).tools

    return _rodar(servidor, log, operacao)


def chamar(servidor: Servidor, log: Path, nome: str, argumentos: dict) -> object:
    async def operacao(cliente):
        return await cliente.call_tool(nome, argumentos)

    # interpretado fora do contexto assíncrono: exceção levantada lá dentro sairia embrulhada
    # num ExceptionGroup do anyio, com a mensagem ilegível
    return _resultado(nome, _rodar(servidor, log, operacao))


# -------------------------------------------------------------------- registro


def _tool_remota(servidor: Servidor, log: Path, remota) -> Tool:
    def funcao(conn, **kwargs):  # conn: contrato do registry; a tool remota não usa o banco local
        return chamar(servidor, log, remota.name, kwargs)

    esquema = dict(remota.input_schema or {"type": "object", "properties": {}})
    esquema.setdefault("type", "object")
    esquema.setdefault("properties", {})
    return Tool(
        nome=remota.name,
        descricao=f"[MCP {servidor.nome}] {remota.description or remota.name}",
        parametros=esquema,
        funcao=funcao,
        externa=True,
    )


def descobrir(
    servidores: list[Servidor], log_dir: Path, nomes_locais: set[str], status
) -> list[Tool]:
    """Tools remotas liberadas. Servidor fora do ar vira aviso: o chat abre sem ele."""
    registradas: list[Tool] = []
    usados = set(nomes_locais)
    for servidor in servidores:
        log = Path(log_dir) / f"mcp-{servidor.nome}.log"
        try:
            remotas = {t.name: t for t in listar_tools(servidor, log)}
        except FalhaMCP as e:
            status.add(f"MCP: {e}")
            continue
        for nome in servidor.tools:
            if nome not in remotas:
                status.add(f"MCP `{servidor.nome}`: tool `{nome}` da allowlist não existe no servidor")
            elif nome in usados:
                status.add(f"MCP `{servidor.nome}`: `{nome}` colide com uma tool já registrada; ignorada")
            else:
                registradas.append(_tool_remota(servidor, log, remotas[nome]))
                usados.add(nome)
    return registradas


def remotas_da_config(mcp_path: Path, log_dir: Path, status) -> list[Tool]:
    """As tools de `mcp.yaml` que entram no chat. Config inválida vira aviso, não derruba o chat."""
    try:
        servidores = carregar(mcp_path)
    except ConfigMCPInvalida as exc:
        status.add(f"mcp.yaml ignorado: {exc}")
        return []
    return descobrir(servidores, log_dir, {t.nome for t in TOOLS}, status)
