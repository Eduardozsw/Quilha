"""Ponto de entrada do backend congelado: a mesma CLI (`quilha serve`, `quilha mcp serve`, `quilha comp seed`…)."""

import multiprocessing

from hermes.cli import app

if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows: subprocesso de binário congelado não reexecuta a CLI
    app(prog_name="quilha-backend")
