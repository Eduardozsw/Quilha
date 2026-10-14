import asyncio
import os
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


def test_serve_fala_mcp_pelo_stdio_e_nada_mais(banco, vault, tmp_path):
    env = {**os.environ, "HERMES_DB": str(tmp_path / "hermes.db"), "VAULT_PATH": str(vault)}
    env.pop("LLM_MODEL", None)
    parametros = StdioServerParameters(command=sys.executable, args=["-m", "hermes.cli", "mcp", "serve"], env=env)
    log = tmp_path / "stderr.log"

    async def rodar():
        with log.open("w", encoding="utf-8") as errlog:
            async with Client(stdio_client(parametros, errlog=errlog), read_timeout_seconds=30) as cliente:
                nomes = {t.name for t in (await cliente.list_tools()).tools}
                r = await cliente.call_tool("list_competencies", {})
                return nomes, r

    nomes, r = asyncio.run(rodar())

    assert "cv_generate" in nomes
    assert not r.is_error
