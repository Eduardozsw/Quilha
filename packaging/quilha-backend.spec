# Backend congelado do Quilha (PyInstaller, modo onedir). Gerar da raiz do repositório:
#   uv run --group empacotamento pyinstaller packaging/quilha-backend.spec --noconfirm
# Saída em dist/quilha-backend/ — a pasta inteira vai para o Tauri como recurso.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent
PADROES = ["competencias.yaml", "curriculos.example.yaml", "fontes.example.yaml",
           "mcp.example.yaml", "denylist.example.yaml"]

datas = [(str(RAIZ / nome), "hermes/dados") for nome in PADROES]
datas += collect_data_files("hermes", includes=["sql/**/*", "templates/**/*"])
datas += collect_data_files("litellm")       # preços e tokenizers em JSON
datas += collect_data_files("tiktoken_ext")
datas += collect_data_files("certifi")

hiddenimports = (
    collect_submodules("hermes")
    + collect_submodules("uvicorn")
    + collect_submodules("tiktoken_ext")
    + ["typesafe_sdk"]
)

a = Analysis(
    [str(RAIZ / "packaging" / "backend.py")],
    pathex=[str(RAIZ)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)
# O hook do googleapiclient leva os ~600 documentos de descoberta (~100 MB); o Quilha só usa o do Gmail.
DESCOBERTA = "googleapiclient/discovery_cache/documents/"
a.datas = [d for d in a.datas
           if not d[0].replace("\\", "/").startswith(DESCOBERTA) or d[0].endswith("/gmail.v1.json")]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="quilha-backend", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="quilha-backend", upx=False)
