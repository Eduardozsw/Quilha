"""Servidor MCP stdio de teste, no contrato que o Mirante vai expor (fase 7).

Roda como processo de verdade: o teste exercita o protocolo MCP inteiro (spawn, handshake,
tools/list, tools/call), não um mock do cliente. Nenhuma rede, nenhum dado real.
"""

import sys

from mcp.server.mcpserver import MCPServer

servidor = MCPServer("mirante-falso")

ARTIGOS = [
    {"titulo": "Selic mantida em 15%", "fonte": "Valor", "data": "2026-09-22", "relevancia": 4},
    {"titulo": "Operadoras de saúde ampliam telemedicina", "fonte": "Folha", "data": "2026-09-22",
     "relevancia": 3},
]


@servidor.tool()
def news_today(limite: int = 10) -> list[dict]:
    """Artigos analisados hoje, do mais relevante para o menos."""
    return ARTIGOS[:limite]


@servidor.tool()
def search_news(consulta: str, dias: int = 7) -> list[dict]:
    """Busca nos artigos dos últimos `dias` dias."""
    return [a for a in ARTIGOS if consulta.lower() in a["titulo"].lower()]


@servidor.tool()
def apagar_tudo() -> str:
    """Tool que o Hermes não pode registrar: fora da allowlist."""
    return "não deveria ter sido chamada"


@servidor.tool()
def quebra() -> str:
    """Falha de propósito, para testar o erro do lado do servidor."""
    raise RuntimeError("banco do Mirante indisponível")


if __name__ == "__main__":
    if "--morrer" in sys.argv:
        sys.exit(3)
    servidor.run("stdio")
