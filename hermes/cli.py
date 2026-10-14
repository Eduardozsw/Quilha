"""CLI do Hermes.

Os comandos determinísticos (`check`, `index`, `stats`, `comp`) não chamam LLM e
não custam nada. O `chat` é o único que gasta crédito.
"""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from hermes.agent import loop as agent_loop
from hermes.agent import session as agent_session
from hermes.agent import mcp_client
from hermes.agent.registry import TOOLS, Registry, Tool
from hermes.config import load_config
from hermes.db import store
from hermes.domain import (
    atividade,
    candidaturas,
    coletor,
    competencias,
    curriculo,
    estudos,
    perfis_cv,
    triagem_email,
    vaga,
)
from hermes.domain.competencias import RegraViolada
from hermes import caminhos, runs
from hermes.run_status import RunStatus
from hermes.runs import Execucao
from hermes.vault.check import (
    Problem,
    check_curriculos,
    check_notes,
    check_orphan_evidence,
    exit_code,
    load_denylist,
)
from hermes.vault import indice, writer
from hermes.vault.reader import read_notes

app = typer.Typer(
    help="Quilha — agente de carreira: vagas, currículo e estudos, a partir do seu vault.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _inicio() -> None:
    """Fora do checkout (app instalado ou `HERMES_HOME`), põe os padrões na base antes de qualquer comando."""
    caminhos.preparar()


comp_app = typer.Typer(
    help="Competências: taxonomia, evidência do vault e nível.", no_args_is_help=True
)
cv_app = typer.Typer(help="Currículo: gera a partir dos fatos do vault.", no_args_is_help=True)
app.add_typer(comp_app, name="comp")
job_app = typer.Typer(
    help="Vagas: requisitos extraídos, score de aderência e lacunas.", no_args_is_help=True
)
app.add_typer(cv_app, name="cv")
app.add_typer(job_app, name="job")
study_app = typer.Typer(
    help="Estudos: o que você declarou, commits como sinal e o plano da semana.",
    no_args_is_help=True,
)
app.add_typer(study_app, name="study")
mcp_app = typer.Typer(help="Servidores MCP: tools externas no chat (ex.: um servidor de notícias).",
                      no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")
email_app = typer.Typer(help="E-mails de processo seletivo: triagem com o Jev e ligação às candidaturas.",
                        no_args_is_help=True)
app.add_typer(email_app, name="email")
app_app = typer.Typer(help="Candidaturas: o que foi enviado, com qual perfil, e a nota de cada perfil.",
                      no_args_is_help=True)
app.add_typer(app_app, name="app")
console = Console()

CORES = {"erro": "red", "aviso": "yellow"}
SEED_PADRAO = "competencias.yaml"  # na base de `hermes.caminhos`


def _mostra_problemas(problemas: list[Problem]) -> None:
    if not problemas:
        console.print("[green]Nenhum problema encontrado.[/green]")
        return
    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("nível")
    tabela.add_column("nota")
    tabela.add_column("linha", justify="right")
    tabela.add_column("problema")
    for p in sorted(problemas, key=lambda p: (p.nivel != "erro", p.nota, p.linha or 0)):
        cor = CORES.get(p.nivel, "white")
        tabela.add_row(
            f"[{cor}]{p.nivel}[/{cor}]",
            p.nota,
            str(p.linha) if p.linha else "",
            p.mensagem,
        )
    console.print(tabela)
    erros = sum(1 for p in problemas if p.nivel == "erro")
    console.print(f"{erros} erro(s), {len(problemas) - erros} aviso(s).")


@contextmanager
def executando(cfg, comando: str):
    """Abre o banco, executa e grava uma linha em `runs` no finally — haja erro ou não."""
    conn = store.connect(cfg.db_path)
    execucao = Execucao(conn, comando)
    try:
        yield execucao
    except typer.Exit:
        raise
    except RegraViolada as exc:
        execucao.crashed = True
        execucao.erro = str(exc)
        console.print(f"[red]recusado:[/red] {exc}")
    except Exception as exc:  # noqa: BLE001 — o status precisa ser gravado sempre
        execucao.crashed = True
        execucao.erro = str(exc)
        console.print(f"[red]falha:[/red] {exc}")
    finally:
        runs.gravar(execucao)
        conn.close()
    if execucao.crashed:
        raise typer.Exit(1)


@app.command()
def check(
    strict: bool = typer.Option(False, "--strict", help="Aviso também faz sair com código 1."),
    vault: Optional[Path] = typer.Option(None, help="Caminho do vault (default: VAULT_PATH)."),
) -> None:
    """Valida o vault: frontmatter, block ids, número sem fonte, denylist."""
    cfg = load_config(vault_path=vault)
    if not cfg.vault_path.is_dir():
        console.print(f"[red]Vault não encontrado:[/red] {cfg.vault_path}")
        raise typer.Exit(1)

    notas = read_notes(cfg.vault_path)
    console.print(f"Vault: {cfg.vault_path} — {len(notas)} nota(s) em Carreira/")
    problemas = check_notes(notas, load_denylist(cfg.denylist_path))
    problemas += check_curriculos(cfg.perfis_cv_path, notas)

    if cfg.db_path.is_file():
        conn = store.connect(cfg.db_path)
        try:
            problemas += check_orphan_evidence(store.orphan_evidence(conn))
        finally:
            conn.close()

    _mostra_problemas(problemas)
    raise typer.Exit(exit_code(problemas, strict))


TRECHO_MCP = """
Para usar pelo Claude Code:
  claude mcp add quilha -- uvx quilha mcp serve

Claude Desktop / Cursor (JSON de servidores MCP):
  "quilha": {"command": "uvx", "args": ["quilha", "mcp", "serve"]}
"""


@app.command()
def init(
    vault: Optional[Path] = typer.Option(None, help="Pasta do vault (padrão: pergunta, sugerindo VAULT_PATH)."),
    sem_llm: bool = typer.Option(False, "--sem-llm", help="Não perguntar sobre LLM próprio."),
) -> None:
    """Primeiro uso sem o app: vault, competências, índice e, se quiser, um LLM próprio."""
    from hermes.domain import configuracao, saude
    from hermes.vault.reader import CAREER_DIR

    cfg = load_config()
    console.print(f"[dim]dados do Quilha em {caminhos.base()}[/dim]")
    destino = vault or Path(typer.prompt("Pasta do vault", default=str(cfg.vault_path)))
    destino = destino.expanduser()
    if not (destino / CAREER_DIR).is_dir():
        if not typer.confirm(f"{destino} não tem {CAREER_DIR}/. Criar com uma nota de exemplo?", default=True):
            console.print(f"Nada feito. Aponte para a pasta que tem {CAREER_DIR}/ ou aceite criar.")
            raise typer.Exit(1)
        for criado in configuracao.criar_vault_exemplo(destino):
            console.print(f"[green]criado[/green] {criado}")
    cfg = configuracao.gravar(cfg, {"VAULT_PATH": str(destino)})

    conn = store.connect(cfg.db_path)
    try:
        criadas = configuracao.inicializar(conn, cfg)
        status = RunStatus()
        indice.reindexar(conn, cfg.vault_path, load_denylist(cfg.denylist_path), status)
        fatos = conn.execute("SELECT count(*) FROM facts").fetchone()[0]
    finally:
        conn.close()
    console.print(f"competências novas: {criadas} · fatos indexados: {fatos}")
    for aviso in status.warnings:
        console.print(f"[yellow]aviso:[/yellow] {aviso}")

    if not sem_llm and saude._falta_llm(cfg):
        console.print("Sem LLM próprio, o modelo do seu cliente MCP escreve os textos e o Quilha valida.")
        if typer.confirm("Configurar um LLM no Quilha agora?", default=False):
            modelo = typer.prompt("Modelo (ex.: gpt-4o-mini, ollama/llama3.1)")
            chave = typer.prompt("Chave da API (vazio para modelo local)", default="", hide_input=True,
                                 show_default=False)
            cfg = configuracao.gravar(cfg, {"LLM_MODEL": modelo, "LLM_API_KEY": chave or None})
            console.print("[green]LLM gravado no .env[/green]")
    console.print(TRECHO_MCP)


@app.command()
def index(
    vault: Optional[Path] = typer.Option(None, help="Caminho do vault (default: VAULT_PATH)."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Reconstrói o índice de fatos do vault no SQLite. O índice é descartável."""
    cfg = load_config(vault_path=vault, db_path=db)
    with executando(cfg, "index") as execucao:
        try:
            r = indice.reindexar(execucao.conn, cfg.vault_path, load_denylist(cfg.denylist_path),
                                 execucao.status)
        except indice.IndiceBloqueado as exc:
            _mostra_problemas(exc.bloqueios)
            raise RuntimeError(str(exc)) from None
        execucao.delivered = True
        console.print(f"[green]{r['fatos']} fato(s) indexado(s)[/green] de {r['notas']} nota(s).")
        if r["orfas"]:
            _mostra_problemas(check_orphan_evidence(r["orfas"]))
        for aviso in execucao.status.warnings:
            console.print(f"[yellow]aviso[/yellow] {aviso}")


@app.command()
def stats(
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Números do banco: fatos indexados, competências e últimas execuções."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        fatos = Table(title="Fatos indexados", show_header=True, header_style="bold")
        fatos.add_column("tipo")
        fatos.add_column("notas", justify="right")
        fatos.add_column("fatos", justify="right")
        fatos.add_column("indexado em")
        linhas = conn.execute(
            "SELECT tipo, COUNT(DISTINCT nota) n, COUNT(*) f, MAX(indexado_em) q"
            " FROM facts GROUP BY tipo"
        ).fetchall()
        for row in linhas:
            fatos.add_row(row["tipo"], str(row["n"]), str(row["f"]), row["q"] or "")
        console.print(fatos if linhas else "Nenhum fato indexado. Rode `quilha index`.")

        resumo = competencias.cobertura(conn)
        if resumo["total"]:
            console.print(
                f"Competências: {resumo['prontas']}/{resumo['total']} prontas para o currículo."
            )

        runs = conn.execute(
            "SELECT started_at, comando, status, llm_calls, cost_usd"
            " FROM runs ORDER BY started_at DESC, id DESC LIMIT 5"
        ).fetchall()
        if runs:
            tabela = Table(title="Últimas execuções", show_header=True, header_style="bold")
            for col in ("início", "comando", "status", "llm", "custo"):
                tabela.add_column(col)
            for row in runs:
                custo = "—" if row["cost_usd"] is None else f"{row['cost_usd']:.6f}"
                tabela.add_row(
                    row["started_at"], row["comando"], row["status"], str(row["llm_calls"]), custo
                )
            console.print(tabela)
    finally:
        conn.close()


# --------------------------------------------------------------------------- comp


# ---------------------------------------------------------------- chat (fase 2)


def _tem_terminal() -> bool:
    """Isolada para poder ser trocada no teste: o CliRunner substitui `sys.stdin`."""
    return sys.stdin.isatty()


def _confirmador(auto: bool):
    """Guarda das tools que gravam. O registry não conhece terminal; este callback sim."""

    def confirmar(tool: Tool, argumentos: dict) -> bool:
        if auto:
            return True
        args = ", ".join(f"{k}={v!r}" for k, v in argumentos.items())
        console.print(f"[yellow]gravar[/yellow] {tool.nome}({args})")
        return typer.confirm("  confirma?", default=False)

    return confirmar


def _mostrador(verboso: bool):
    """Eventos do turno no terminal. A resposta sai em trechos, conforme o modelo escreve; `on_evento.escreveu`
    diz se algum trecho saiu (para não imprimir a resposta inteira de novo no fim)."""
    def on_evento(tipo: str, dados: dict) -> None:
        if tipo == "trecho":
            on_evento.escreveu = True
            console.print(dados["texto"], end="", soft_wrap=True, markup=False, highlight=False)
            return
        if tipo == "chamando_modelo" and on_evento.escreveu:
            console.print()  # o texto antes de uma ferramenta termina a linha
        if tipo == "tool":
            console.print(f"[dim]· {dados['nome']} {dados.get('argumentos', '')}[/dim]")
        elif tipo == "tool_resultado" and not dados["ok"]:
            console.print(f"[dim yellow]· {dados['nome']} falhou[/dim yellow]")
        elif tipo == "chamando_modelo" and verboso:
            console.print(f"[dim]· modelo (iteração {dados['iteracao']})[/dim]")
        elif tipo == "teto_custo":
            console.print(f"[red]{dados['mensagem']}[/red]")

    on_evento.escreveu = False
    return on_evento


def _com_parar(rodar):
    """Roda um turno com o Ctrl+C como "Parar": o primeiro para o turno (o texto que já saiu fica gravado) e a
    conversa continua; o segundo, no mesmo turno, sai como antes."""
    import signal
    import threading

    parar = threading.Event()
    anterior = signal.getsignal(signal.SIGINT)

    def ao_ctrl_c(sinal, quadro):
        if parar.is_set():
            signal.signal(signal.SIGINT, anterior)
            raise KeyboardInterrupt
        parar.set()
        console.print("\n[yellow]parando… (Ctrl+C de novo sai)[/yellow]")

    signal.signal(signal.SIGINT, ao_ctrl_c)
    try:
        return rodar(parar)
    finally:
        signal.signal(signal.SIGINT, anterior)


def _rodape(status: RunStatus, sessao_id: int) -> str:
    custo = status.cost_usd
    valor = "custo desconhecido" if custo is None else f"US$ {custo:.4f}"
    return (
        f"[dim]sessão {sessao_id} · {status.llm_calls} chamada(s) · "
        f"{status.prompt_tokens}+{status.completion_tokens} tokens · {valor}[/dim]"
    )


@app.command()
def chat(
    pergunta: Optional[str] = typer.Argument(
        None, help="Pergunta única. Sem ela, abre a conversa interativa."
    ),
    continuar: bool = typer.Option(
        False, "--continue", "-c", help="Retoma a última sessão em vez de abrir uma nova."
    ),
    sessao_id: Optional[int] = typer.Option(None, "--session", help="Retoma uma sessão pelo id."),
    modelo: Optional[str] = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL."),
    teto_usd: Optional[float] = typer.Option(
        None, "--max-cost", help="Teto de custo da sessão em dólares."
    ),
    sim: bool = typer.Option(
        False, "--yes", "-y", help="Não pede confirmação para gravar. Use com cuidado."
    ),
    verboso: bool = typer.Option(False, "--verbose", "-v", help="Mostra cada chamada ao modelo."),
) -> None:
    """Conversa com o Hermes. Este é o único comando que custa dinheiro."""
    if pergunta is None and not _tem_terminal():
        # sem TTY o REPL leria EOF na primeira pergunta e sairia calado
        console.print(
            '[red]sem terminal interativo.[/red] Passe a pergunta como argumento: '
            'quilha chat "quais competências já sustentam currículo?"'
        )
        raise typer.Exit(2)

    cfg = load_config()
    model = modelo or cfg.llm_model
    teto = cfg.max_cost_usd if teto_usd is None else teto_usd

    with executando(cfg, "chat") as ex:
        ex.model = model
        sessao = (
            agent_session.continuar(ex.conn, sessao_id)
            if (continuar or sessao_id is not None)
            else agent_session.abrir(ex.conn, model)
        )
        ex.session_id = sessao.id
        remotas = _tools_mcp(cfg, ex.status)
        registry = Registry(
            tools=TOOLS + tuple(remotas),
            conn=ex.conn,
            confirmar=_confirmador(sim),
            status=ex.status,
            model=model,
            denylist=tuple(load_denylist(cfg.denylist_path)),
            repos_conhecidos=tuple(atividade.descobrir_repos(cfg.repos_dir)),
            cfg=cfg,
            sem_confirmacao=frozenset() if sim else cfg.sem_confirmacao,
        )
        on_evento = _mostrador(verboso)

        anteriores = len(sessao.mensagens())
        console.print(
            f"[dim]Hermes · {model} · sessão {sessao.id}"
            + (f" ({anteriores} mensagens anteriores)" if anteriores else "")
            + (" · sair com Ctrl-D" if pergunta is None else "")
            + "[/dim]"
        )

        if remotas:
            console.print(f"[dim]MCP: {', '.join(t.nome for t in remotas)}[/dim]")
        for aviso in ex.status.warnings:
            console.print(f"[yellow]aviso:[/yellow] {aviso}")

        perguntas = [pergunta] if pergunta else _perguntas_do_terminal()
        for texto in perguntas:
            on_evento.escreveu = False
            turno = _com_parar(lambda parar: agent_loop.responder(
                sessao,
                registry,
                texto,
                status=ex.status,
                teto_usd=teto,
                model=model,
                on_evento=on_evento,
                parar=parar,
            ))
            if on_evento.escreveu:
                console.print()  # fecha a linha da resposta que saiu em trechos
            elif turno.resposta:
                console.print(turno.resposta)
            ex.delivered = turno.completo
            if turno.parou_por == "teto_custo":
                break
            if turno.parou_por:
                console.print(f"[yellow]turno encerrado: {turno.parou_por}[/yellow]")

        if sessao.mensagens():
            sessao.fechar(model, ex.status.cost_usd)
            console.print(_rodape(ex.status, sessao.id))
        else:
            ex.session_id = None  # antes de apagar: `runs.session_id` é FK
            sessao.apagar()


def _perguntas_do_terminal():
    """Gera as perguntas do REPL até Ctrl-D, Ctrl-C ou `sair`."""
    while True:
        try:
            texto = typer.prompt("\nvocê", prompt_suffix=" ")
        except (EOFError, KeyboardInterrupt, typer.Abort):
            return
        if texto.strip().lower() in {"sair", "exit", "quit"}:
            return
        if texto.strip():
            yield texto


# ------------------------------------------------------------- currículo (fase 3)


_OPC_IDIOMA = typer.Option(list(curriculo.IDIOMAS), "--idioma", "-i", help="pt, en, ou ambos (padrão).")
_OPC_SAIDA = typer.Option(None, "--saida", help="Onde gravar os arquivos (default: HERMES_SAIDA).")
_OPC_LIMITE = typer.Option(None, "--limite",
                           help=f"Máximo de fatos (padrão: o do perfil, ou {curriculo.MAX_FATOS}).")
_OPC_MODELO = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL.")
_OPC_JOB = typer.Option(None, "--job", help="Sob medida para uma vaga: só fatos das competências que ela pede.")
_OPC_PERFIL = typer.Option(None, "--perfil", "-p", help="Recorte de `curriculos.yaml` (veja `quilha cv perfis`).")
_OPC_FORCAR = typer.Option(False, "--forcar",
                           help="Redige de novo mesmo se a seleção não mudou (gasta crédito).")


def _gerar_cv(cfg, ex, idioma, saida, limite, model, job_id, perfil, forcar) -> tuple[list[dict], object]:
    """O que `cv draft` e `cv pdf` têm em comum: recorte, geração e a tabela do que saiu."""
    recorte = None
    if perfil:
        try:
            todos = perfis_cv.carregar(cfg.perfis_cv_path)
            perfis_cv.validar(ex.conn, todos)
            recorte = perfis_cv.buscar(todos, perfil)
        except perfis_cv.PerfilInvalido as exc:
            raise RegraViolada(str(exc)) from None
    try:
        resultados = curriculo.gerar(
            ex.conn,
            cfg.vault_path,
            saida,
            ex.status,
            idiomas=tuple(idioma),
            model=model,
            limite=limite,
            job_id=job_id,
            perfil=recorte,
            forcar=forcar,
            nomes=perfis_cv.carregar_nomes(cfg.perfis_cv_path),
        )
    except vaga.VagaRecusada as exc:
        console.print(f"[red]recusado:[/red] {exc}")
        raise typer.Exit(1) from None
    except curriculo.SemFatos as exc:
        console.print(f"[yellow]nada a gerar:[/yellow] {exc}")
        _cobertura_resumida(ex.conn)
        raise typer.Exit(1) from None

    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("idioma")
    tabela.add_column("arquivo")
    tabela.add_column("palavras", justify="right")
    tabela.add_column("fatos", justify="right")
    for r in resultados:
        palavras = str(r["palavras"])
        tabela.add_row(
            r["idioma"] + (" [dim](guardada)[/dim]" if r["reaproveitado"] else ""),
            str(r["caminho"]),
            f"[yellow]{palavras}[/yellow]" if r["palavras"] > 450 else palavras,
            str(len(r["fatos"])),
        )
    console.print(tabela)
    return resultados, recorte


def _fecha_cv(ex, resultados) -> None:
    if any(r["palavras"] > 450 for r in resultados):
        console.print("[yellow]acima de 450 palavras: corte com `--limite`.[/yellow]")
    for aviso in ex.status.warnings:
        console.print(f"[yellow]aviso:[/yellow] {aviso}")
    console.print(_rodape(ex.status, 0).replace("sessão 0 · ", ""))


@cv_app.command("draft")
def cv_draft(
    idioma: list[str] = _OPC_IDIOMA,
    saida: Optional[Path] = _OPC_SAIDA,
    limite: Optional[int] = _OPC_LIMITE,
    modelo: Optional[str] = _OPC_MODELO,
    job_id: Optional[int] = _OPC_JOB,
    perfil: Optional[str] = _OPC_PERFIL,
    forcar: bool = _OPC_FORCAR,
) -> None:
    """Gera o currículo a partir dos fatos que já sustentam nível 2 ou mais.

    Uma chamada ao modelo por idioma; a seleção dos fatos é a mesma para todos. Seleção igual a
    uma já redigida reaproveita a versão guardada, sem custo.
    """
    cfg = load_config()
    model = modelo or cfg.llm_model

    with executando(cfg, "cv draft") as ex:
        ex.model = model
        resultados, _ = _gerar_cv(cfg, ex, idioma, saida or cfg.saida_dir, limite, model, job_id, perfil, forcar)
        _fecha_cv(ex, resultados)
        ex.delivered = True


@cv_app.command("pdf")
def cv_pdf(
    idioma: list[str] = _OPC_IDIOMA,
    saida: Optional[Path] = _OPC_SAIDA,
    limite: Optional[int] = _OPC_LIMITE,
    modelo: Optional[str] = _OPC_MODELO,
    job_id: Optional[int] = _OPC_JOB,
    perfil: Optional[str] = _OPC_PERFIL,
    forcar: bool = _OPC_FORCAR,
) -> None:
    """Gera o currículo (como `cv draft`) e o PDF, com checagem de páginas.

    Passou do limite do perfil (1 página): o PDF fica gravado, o comando sai com 1 e diz o que
    ocupa mais espaço. Cortar é decisão sua — `--limite` ou menos bullets no vault.
    """
    from hermes.domain import pdf

    cfg = load_config()
    model = modelo or cfg.llm_model

    with executando(cfg, "cv pdf") as ex:
        ex.model = model
        resultados, recorte = _gerar_cv(cfg, ex, idioma, saida or cfg.saida_dir, limite, model, job_id, perfil, forcar)
        paginas = recorte.paginas if recorte is not None else 1
        estourou = False
        for r in resultados:
            destino = Path(r["caminho"]).with_suffix(".pdf")
            try:
                feito = pdf.compilar(r["estrutura"], destino, paginas)
            except pdf.PaginasDemais as exc:
                estourou = True
                console.print(f"[red]{r['idioma']}: {exc.paginas} páginas[/red] (limite {exc.limite}) — {exc.destino}")
                tabela = Table("entrada", "seção", "linhas (≈)", header_style="bold")
                for e in exc.entradas:
                    tabela.add_row(e["titulo"], e["secao"], str(e["linhas"]))
                console.print(tabela)
                continue
            plural = "página" if feito["paginas"] == 1 else "páginas"
            console.print(f"[green]{r['idioma']}:[/green] {destino} ({feito['paginas']} {plural})")
        _fecha_cv(ex, resultados)
        if estourou:
            console.print("[yellow]corte com `--limite` ou tire bullets no vault; nada foi cortado sozinho.[/yellow]")
            raise typer.Exit(1)
        ex.delivered = True


@cv_app.command("perfis")
def cv_perfis() -> None:
    """Perfis de `curriculos.yaml`: cargo, foco e quantas versões já foram geradas."""
    cfg = load_config()
    conn = store.connect(cfg.db_path)
    try:
        todos = perfis_cv.carregar(cfg.perfis_cv_path)
        if not todos:
            console.print(f"Nenhum perfil em {cfg.perfis_cv_path.name}.")
            return
        perfis_cv.validar(conn, todos)
        tabela = Table(show_header=True, header_style="bold")
        for col in ("perfil", "cargo", "foco", "versões"):
            tabela.add_column(col)
        for grupo in curriculo.galeria(conn, todos):
            if grupo["perfil"] is None or grupo["cargo"] is None:
                continue
            tabela.add_row(grupo["perfil"], grupo["cargo"]["pt"], grupo["foco"][:60],
                           str(len(grupo["versoes"])))
        console.print(tabela)
    except perfis_cv.PerfilInvalido as exc:
        _recusa(exc)
    finally:
        conn.close()


def _cobertura_resumida(conn) -> None:
    """Depois de um `nada a gerar`, mostrar o que falta vale mais que o erro."""
    resumo = competencias.cobertura(conn)
    console.print(
        f"{resumo['prontas']} de {resumo['total']} competências sustentam currículo. "
        "Veja `quilha comp coverage`."
    )


# ------------------------------------------------------------------ vagas (fase 4)


def _ler_texto_da_vaga(arquivo: Optional[Path]) -> Optional[str]:
    if arquivo is None:
        return None if _tem_terminal() else sys.stdin.read()
    if str(arquivo) == "-":
        return sys.stdin.read()
    return arquivo.read_text(encoding="utf-8")


def _tabela_requisitos(requisitos: list[dict]) -> Table:
    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("id", justify="right")
    tabela.add_column("tipo")
    tabela.add_column("requisito")
    tabela.add_column("competência")
    tabela.add_column("conf.", justify="right")
    for r in requisitos:
        tabela.add_row(
            str(r["id"]),
            "obrig." if r["tipo"] == "obrigatorio" else "desej.",
            r["texto"],
            r["competencia"] or "[yellow]—[/yellow]",
            "—" if r["confianca"] is None else f"{r['confianca']:.2f}",
        )
    return tabela


@job_app.command("add")
def job_add(
    arquivo: Optional[Path] = typer.Argument(
        None, help="Arquivo com o texto da vaga; `-` ou sem argumento lê da entrada padrão."
    ),
    url: Optional[str] = typer.Option(None, "--url", help="Busca a descrição na URL."),
    empresa: Optional[str] = typer.Option(None, help="Sobrepõe a empresa extraída."),
    titulo: Optional[str] = typer.Option(None, help="Sobrepõe o título extraído."),
    modelo: Optional[str] = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL."),
) -> None:
    """Grava uma vaga e extrai os requisitos. Uma chamada ao modelo; vaga repetida sai de graça."""
    texto = None if url else _ler_texto_da_vaga(arquivo)
    if not url and not (texto or "").strip():
        console.print(
            "[red]sem texto da vaga.[/red] Passe um arquivo, `--url`, ou cole pela entrada padrão:"
            " wl-paste | quilha job add -"
        )
        raise typer.Exit(2)

    cfg = load_config()
    model = modelo or cfg.llm_model
    with executando(cfg, "job add") as ex:
        ex.model = model
        try:
            resultado = vaga.parse_job(
                ex.conn,
                texto=texto,
                url=url,
                empresa=empresa,
                titulo=titulo,
                status=ex.status,
                model=model,
                denylist=tuple(load_denylist(cfg.denylist_path)),
            )
        except vaga.VagaRecusada as exc:
            console.print(f"[red]recusado:[/red] {exc}")
            raise typer.Exit(1) from None

        cabecalho = f"vaga {resultado['job_id']} · {resultado['titulo']} — {resultado['empresa']}"
        if resultado["duplicada"]:
            console.print(
                f"[yellow]já gravada[/yellow], nada foi gasto: {cabecalho}"
                f" (para extrair de novo: quilha job extrair {resultado['job_id']})"
            )
        else:
            console.print(f"[green]gravada[/green]: {cabecalho}")
        _mostra_extracao(resultado, ex.status, gastou=not resultado["duplicada"])
        ex.delivered = True


def _mostra_extracao(resultado: dict, status: RunStatus, gastou: bool) -> None:
    console.print(_tabela_requisitos(resultado["requisitos"]))
    if resultado["sugeridos_fora"]:
        console.print(
            "[yellow]o modelo sugeriu competências que não existem:[/yellow] "
            + ", ".join(resultado["sugeridos_fora"])
        )
    for aviso in status.warnings:
        console.print(f"[yellow]aviso:[/yellow] {aviso}")
    if gastou:
        console.print(_rodape(status, 0).replace("sessão 0 · ", ""))


@job_app.command("extrair")
def job_extrair(
    job_id: int = typer.Argument(..., help="Id da vaga."),
    modelo: Optional[str] = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL."),
) -> None:
    """Extrai (ou refaz) os requisitos de uma vaga gravada, a partir do texto guardado.

    Uma chamada ao modelo. Substitui os requisitos anteriores e desfaz o que foi feito com `job map`.
    """
    cfg = load_config()
    model = modelo or cfg.llm_model
    with executando(cfg, "job extrair") as ex:
        ex.model = model
        try:
            resultado = vaga.extrair_requisitos(
                ex.conn, job_id, status=ex.status, model=model,
                denylist=tuple(load_denylist(cfg.denylist_path)),
            )
        except vaga.VagaRecusada as exc:
            console.print(f"[red]recusado:[/red] {exc}")
            raise typer.Exit(1) from None
        acao = "requisitos reextraídos" if resultado["reextraida"] else "requisitos extraídos"
        console.print(
            f"[green]{acao}[/green]: vaga {resultado['job_id']} · "
            f"{resultado['titulo']} — {resultado['empresa']}"
        )
        _mostra_extracao(resultado, ex.status, gastou=True)
        ex.delivered = True


@job_app.command("list")
def job_list(
    status_vaga: Optional[str] = typer.Option(None, "--status", help="novo, analisado, aplicado, descartado."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Vagas gravadas, com o score de aderência calculado agora (fórmula, sem modelo)."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        linhas = vaga.listar(conn, status_vaga)
        if not linhas:
            console.print("Nenhuma vaga. Grave uma com `quilha job add`.")
            return
        tabela = Table(show_header=True, header_style="bold")
        for col, just in (("id", "right"), ("empresa", "left"), ("título", "left"),
                          ("status", "left"), ("req.", "right"), ("score", "right"),
                          ("coletada", "left")):
            tabela.add_column(col, justify=just)
        for l in linhas:
            tabela.add_row(
                str(l["id"]), l["empresa"], l["titulo"], l["status"], str(l["n_requisitos"]),
                "—" if l["score"] is None else str(l["score"]), l["coletado_em"][:10],
            )
        console.print(tabela)
    finally:
        conn.close()


@job_app.command("show")
def job_show(
    job_id: int = typer.Argument(..., help="Id da vaga."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Requisitos extraídos de uma vaga e o mapeamento para competências."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        v = vaga.buscar(conn, job_id)
        console.print(f"[bold]{v['titulo']}[/bold] — {v['empresa']} ({v['status']})")
        extras = [x for x in (v["senioridade"], v["local"], v["url"]) if x]
        if extras:
            console.print(" · ".join(extras))
        console.print(_tabela_requisitos(vaga.requisitos(conn, job_id)))
    except vaga.VagaRecusada as exc:
        console.print(f"[red]recusado:[/red] {exc}")
        raise typer.Exit(1) from None
    finally:
        conn.close()


@job_app.command("map")
def job_map(
    requisito_id: int = typer.Argument(..., help="Id do requisito (veja `quilha job show`)."),
    slug: Optional[str] = typer.Argument(None, help="Competência. Sem ela, desfaz o mapeamento."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Corrige o mapeamento de um requisito para uma competência. Custo zero."""
    cfg = load_config(db_path=db)
    with executando(cfg, "job map") as ex:
        try:
            r = vaga.mapear(ex.conn, requisito_id, slug)
        except vaga.VagaRecusada as exc:
            console.print(f"[red]recusado:[/red] {exc}")
            raise typer.Exit(1) from None
        destino = r["competencia"] or "nenhuma competência"
        console.print(f"requisito {requisito_id} (vaga {r['job_id']}) → {destino}")
        ex.delivered = True


@job_app.command("match")
def job_match(
    job_id: int = typer.Argument(..., help="Id da vaga."),
    sem_texto: bool = typer.Option(
        False, "--sem-texto", help="Só o score e as lacunas, sem chamar o modelo. Custo zero."
    ),
    modelo: Optional[str] = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL."),
) -> None:
    """Score de aderência (fórmula v1, sem LLM) + lacunas e riscos de entrevista."""
    cfg = load_config()
    model = modelo or cfg.llm_model
    with executando(cfg, "job match") as ex:
        if not sem_texto:
            ex.model = model
        try:
            r = vaga.match_job(
                ex.conn, job_id, redigir=not sem_texto, status=ex.status, model=model
            )
        except vaga.VagaRecusada as exc:
            console.print(f"[red]recusado:[/red] {exc}")
            raise typer.Exit(1) from None

        console.print(f"[bold]{r['titulo']}[/bold] — {r['empresa']}")
        console.print(
            f"[bold]score {r['score']}/100[/bold] · fórmula {r['formula']} · "
            f"N={r['n_requisitos']} requisitos, {r['mapeados']} mapeados, "
            f"{r['obrigatorios_descobertos']} de {r['obrigatorios']} obrigatórios descobertos"
        )
        console.print(
            "[dim]score = Σ(peso × cobertura) / Σ(peso); peso 2 obrigatório, 1 desejável; "
            "cobertura por nível 0→0 · 1→0.25 · 2→0.60 · 3→0.85 · 4→1[/dim]"
        )

        tabela = Table(show_header=True, header_style="bold")
        for col, just in (("tipo", "left"), ("requisito", "left"), ("competência", "left"),
                          ("nível", "right"), ("evid.", "right"), ("cob.", "right")):
            tabela.add_column(col, justify=just)
        for i in r["cobertura"]:
            tabela.add_row(
                "obrig." if i["tipo"] == "obrigatorio" else "desej.",
                i["texto"],
                i["competencia"] or "[yellow]—[/yellow]",
                "—" if i["nivel"] is None else str(i["nivel"]),
                str(len(i["evidencias"])),
                f"{i['cobertura']:.2f}",
            )
        console.print(tabela)

        if r["lacunas"]:
            console.print("\n[bold]Lacunas[/bold]")
            for f in r["lacunas"]:
                linha = f"- [{f['requisito_id']}] {f['texto']} ({f['motivo']})"
                if f.get("ligadas"):
                    refs = ", ".join(f"^{b}" for b in f["ligadas"])
                    linha += f"\n    [cyan]já ligado:[/cyan] {refs} — declare com `quilha comp assess`"
                elif f.get("candidatos"):
                    refs = ", ".join(f"^{c['block_id']}" for c in f["candidatos"])
                    linha += f"\n    [cyan]no vault:[/cyan] {refs} — ligue com `quilha comp evidence`"
                if f.get("comentario"):
                    linha += f"\n    {f['comentario']}"
                console.print(linha)
        if r["riscos"]:
            console.print("\n[bold]Riscos em entrevista[/bold]")
            for risco in r["riscos"]:
                console.print(f"- {risco}")
        for aviso in ex.status.warnings:
            console.print(f"[yellow]aviso:[/yellow] {aviso}")
        if not sem_texto:
            console.print(_rodape(ex.status, 0).replace("sessão 0 · ", ""))
        ex.delivered = True


# ---------------------------------------------------------------- estudos (fase 5)


def _recusa(exc: Exception | str) -> None:
    console.print(f"[red]recusado:[/red] {exc}")
    raise typer.Exit(1)


@study_app.command("log")
def study_log(
    minutos: int = typer.Argument(..., help="Minutos estudados."),
    o_que_fez: str = typer.Argument(..., help="O que você fez, numa frase."),
    comp: Optional[str] = typer.Option(None, "--comp", "-c", help="Competência estudada."),
    data: Optional[str] = typer.Option(None, help="AAAA-MM-DD; padrão hoje."),
    dificuldade: Optional[int] = typer.Option(None, "--dificuldade", "-d", help="1 a 5."),
    travou: Optional[str] = typer.Option(None, "--travou", help="Onde travou, se travou."),
) -> None:
    """Registra uma sessão de estudo que você fez. Custo zero."""
    cfg = load_config()
    with executando(cfg, "study log") as ex:
        try:
            r = estudos.log_study(ex.conn, minutos, o_que_fez, slug=comp, data=data,
                                  dificuldade=dificuldade, travou_em=travou)
        except estudos.EstudoRecusado as exc:
            _recusa(exc)
        alvo = f" em `{r['competencia']}`" if r["competencia"] else ""
        console.print(f"[green]registrado[/green]: {r['minutos']} min{alvo} em {r['data']} (sessão {r['id']})")
        ex.delivered = True


@study_app.command("week")
def study_week(
    semana: Optional[str] = typer.Option(None, help="ISO, ex: 2026-W39; padrão a atual."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Minutos declarados na semana, por competência, contra o plano."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        try:
            r = estudos.resumo_semana(conn, semana)
        except estudos.EstudoRecusado as exc:
            _recusa(exc)
        meta = f" de {r['minutos_alvo']} planejados" if r["plano"] else " (sem plano para a semana)"
        console.print(f"[bold]{r['semana']}[/bold] ({r['inicio']} a {r['fim']}): "
                      f"{r['minutos']} min declarados{meta}, {len(r['sessoes'])} sessão(ões)")
        for comp_, minutos in sorted(r["por_competencia"].items()):
            console.print(f"  {comp_}: {minutos} min")
        if r["plano"]:
            console.print(f"\n[bold]Plano:[/bold] {r['plano']['objetivo']}")
            for i in r["plano"]["itens"]:
                console.print(f"  - ({i['minutos_feitos']}/{i['minutos_alvo']} min, {i['competencia']}) "
                              f"{i['descricao']}")
        if r["sinais_pendentes"]:
            console.print(f"[yellow]{r['sinais_pendentes']} commit(s) sem resposta[/yellow]:"
                          " `quilha study git` para ver")
    finally:
        conn.close()


@study_app.command("git")
def study_git(
    dias: int = typer.Option(1, help="Janela em dias (1 a 31)."),
    repo: list[str] = typer.Option([], "--repo", help="Só estes repositórios (nome da pasta)."),
) -> None:
    """Commits recentes como sinal. Nada vira estudo sem você confirmar com `study confirm`."""
    cfg = load_config()
    with executando(cfg, "study git") as ex:
        try:
            r = atividade.git_activity(
                ex.conn, dias, repo or None,
                repos_conhecidos=tuple(atividade.descobrir_repos(cfg.repos_dir)),
                status=ex.status,
            )
        except atividade.AtividadeRecusada as exc:
            _recusa(exc)
        console.print(f"{len(r['repos_lidos'])} repositório(s) em {cfg.repos_dir}, "
                      f"{r['sinais_novos']} commit(s) novo(s).")
        if not r["pendentes"]:
            console.print("Nenhum commit esperando resposta.")
        for nome, sinais in r["pendentes"].items():
            console.print(f"\n[bold]{nome}[/bold]")
            for s_ in sinais:
                console.print(f"  [{s_['id']}] {s_['data']} {s_['sha']} {s_['resumo']}")
        if r["pendentes"]:
            console.print("\nFoi estudo? `quilha study confirm <ids> <minutos> \"o que fez\"`."
                          " Não foi? `quilha study ignore <ids>`.")
        for aviso in ex.status.warnings:
            console.print(f"[yellow]aviso:[/yellow] {aviso}")
        ex.delivered = True


def _ids(texto: str) -> list[int]:
    try:
        return [int(x) for x in texto.replace(" ", "").split(",") if x]
    except ValueError:
        raise typer.BadParameter("use ids separados por vírgula, ex: 12,13") from None


@study_app.command("confirm")
def study_confirm(
    sinais: str = typer.Argument(..., help="Ids dos commits, separados por vírgula."),
    minutos: int = typer.Argument(..., help="Minutos que você estudou (não a contagem de commits)."),
    o_que_fez: str = typer.Argument(..., help="O que você estudou."),
    comp: Optional[str] = typer.Option(None, "--comp", "-c", help="Competência estudada."),
    dificuldade: Optional[int] = typer.Option(None, "--dificuldade", "-d", help="1 a 5."),
) -> None:
    """Transforma commits em uma sessão de estudo, com o que você declarou."""
    cfg = load_config()
    with executando(cfg, "study confirm") as ex:
        try:
            r = atividade.confirmar(ex.conn, _ids(sinais), minutos, o_que_fez,
                                    slug=comp, dificuldade=dificuldade)
        except (atividade.AtividadeRecusada, estudos.EstudoRecusado) as exc:
            _recusa(exc)
        console.print(f"[green]sessão {r['id']}[/green]: {r['minutos']} min em {r['data']}, "
                      f"ligada a {len(r['sinais'])} commit(s)")
        ex.delivered = True


@study_app.command("ignore")
def study_ignore(sinais: str = typer.Argument(..., help="Ids separados por vírgula.")) -> None:
    """Commits que não foram estudo saem da lista de perguntas."""
    cfg = load_config()
    with executando(cfg, "study ignore") as ex:
        r = atividade.ignorar(ex.conn, _ids(sinais))
        console.print(f"{r['ignorados']} commit(s) ignorado(s).")
        ex.delivered = True


@study_app.command("plan")
def study_plan(
    minutos: int = typer.Option(..., "--minutos", "-m", help="Minutos disponíveis na semana."),
    semana: Optional[str] = typer.Option(None, help="ISO; padrão a próxima semana."),
    substituir: bool = typer.Option(False, "--substituir", help="Refaz o plano da semana."),
    diario: bool = typer.Option(True, "--diario/--sem-diario", help="Acrescenta o plano em Diario/."),
    sim: bool = typer.Option(False, "--yes", "-y", help="Grava no vault sem perguntar."),
    modelo: Optional[str] = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL."),
) -> None:
    """Plano da semana a partir das lacunas das vagas abertas. Uma chamada ao modelo."""
    from datetime import date, timedelta

    from hermes.vault import writer

    cfg = load_config()
    model = modelo or cfg.llm_model
    with executando(cfg, "study plan") as ex:
        ex.model = model
        try:
            plano = estudos.plan_week(ex.conn, minutos, semana, substituir,
                                      status=ex.status, model=model)
        except estudos.EstudoRecusado as exc:
            _recusa(exc)
        inicio = date.fromisocalendar(*map(int, plano["semana"].split("-W")), 1)
        anterior = estudos.resumo_semana(ex.conn, estudos.semana_iso(inicio - timedelta(days=7)))
        trecho = estudos.markdown_do_plano(plano, anterior)
        console.print(trecho)
        for aviso in ex.status.warnings:
            console.print(f"[yellow]aviso:[/yellow] {aviso}")
        console.print(_rodape(ex.status, 0).replace("sessão 0 · ", ""))

        if diario:
            destino = f"Diario/{plano['semana']}.md"
            if sim or typer.confirm(f"acrescentar este trecho em {destino}?", default=False):
                try:
                    r = writer.acrescentar(cfg.vault_path, "Diario", plano["semana"], trecho,
                                           titulo=f"Semana {plano['semana']}")
                except writer.EscritaRecusada as exc:
                    _recusa(exc)
                console.print(f"{'criado' if r['criada'] else 'acrescentado'}: {r['caminho']}")
            else:
                console.print("[dim]plano gravado no banco; nada escrito no vault[/dim]")
        ex.delivered = True


# ---------------------------------------------------------------- coletor (fase 6)


@job_app.command("collect")
def job_collect(
    forcar: bool = typer.Option(False, "--forcar", help="Ignora o intervalo e o backoff da fila."),
    extrair: int = typer.Option(
        0, "--extrair", help="Extrai os requisitos de até N vagas novas (1 chamada cada)."
    ),
    fontes: Optional[Path] = typer.Option(None, help="YAML das fontes (default: HERMES_FONTES)."),
    modelo: Optional[str] = typer.Option(None, "--model", help="Sobrepõe LLM_MODEL."),
) -> None:
    """Coleta vagas das fontes de `fontes.yaml` (Greenhouse, Lever, Gupy). Sem `--extrair`, custo zero."""
    from hermes import llm

    cfg = load_config()
    model = modelo or cfg.llm_model
    try:
        lista = coletor.carregar_fontes(fontes or cfg.fontes_path)
    except coletor.ColetaRecusada as exc:
        _recusa(exc)

    with executando(cfg, "job collect") as ex:
        r = coletor.coletar(ex.conn, lista, ex.started_at, ex.status, forcar=forcar)

        tabela = Table(show_header=True, header_style="bold")
        for col, just in (("fonte", "left"), ("board", "left"), ("status", "left"),
                          ("vistas", "right"), ("filtro", "right"), ("novas", "right"),
                          ("dup.", "right"), ("ms", "right")):
            tabela.add_column(col, justify=just)
        cores = {"ok": "green", "falhou": "red", "bloqueada": "yellow"}
        for c in r["resultados"]:
            n = lambda v: "—" if v is None else str(v)  # noqa: E731
            cor = cores[c["status"]]
            tabela.add_row(c["fonte"], c["board"], f"[{cor}]{c['status']}[/{cor}]",
                           n(c["vagas_vistas"]), n(c["vagas_filtradas"]), n(c["vagas_novas"]),
                           n(c["duplicadas"]), str(c["duracao_ms"]))
        if r["resultados"]:
            console.print(tabela)
        console.print(
            f"{r['processadas']} de {r['fontes']} fonte(s) processada(s)"
            + (f", {r['adiadas']} adiada(s) pela fila (use --forcar)" if r["adiadas"] else "")
            + f"; {r['vagas_novas']} vaga(s) nova(s)."
        )

        if extrair and r["ids_novos"]:
            ex.model = model
            denylist = tuple(load_denylist(cfg.denylist_path))
            for job_id in r["ids_novos"][:extrair]:
                try:
                    llm.check_cost_limit(ex.status, cfg.max_cost_usd)
                except llm.CostLimitError as e:
                    ex.status.add(str(e))
                    break
                try:
                    e_ = vaga.extrair_requisitos(ex.conn, job_id, status=ex.status, model=model,
                                                 denylist=denylist)
                    console.print(f"  vaga {job_id}: {len(e_['requisitos'])} requisito(s) extraído(s)")
                except vaga.VagaRecusada as e:
                    ex.status.add(f"vaga {job_id}: {e}")
            console.print(_rodape(ex.status, 0).replace("sessão 0 · ", ""))
        elif r["ids_novos"]:
            console.print("[dim]requisitos não extraídos: `quilha job extrair <id>` ou `--extrair N`[/dim]")

        for aviso in ex.status.warnings:
            console.print(f"[yellow]aviso:[/yellow] {aviso}")
        # entregue = nenhuma fonte devida falhou; falha parcial aparece como aviso (run `partial`)
        ex.delivered = r["processadas"] == 0 or r["ok"] > 0


@job_app.command("fila")
def job_fila(
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Estado da fila do coletor: última coleta boa, falhas seguidas e próxima tentativa."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        linhas = coletor.fila(conn)
        if not linhas:
            console.print("Fila vazia. Rode `quilha job collect`.")
            return
        tabela = Table(show_header=True, header_style="bold")
        for col in ("fonte", "board", "estado", "falhas", "próxima", "última ok", "erro"):
            tabela.add_column(col)
        for l in linhas:
            tabela.add_row(l["fonte"], l["board"], l["estado"], str(l["tentativas"]),
                           l["proximo_em"][:16], (l["ultima_ok_em"] or "—")[:16],
                           (l["ultimo_erro"] or "")[:60])
        console.print(tabela)
    finally:
        conn.close()


# ---------------------------------------------------------------------- MCP (fase 7)


def _tools_mcp(cfg, status: RunStatus) -> list[Tool]:
    return mcp_client.remotas_da_config(cfg.mcp_path, cfg.db_path.parent, status)


@mcp_app.command("list")
def mcp_list() -> None:
    """Servidores de `mcp.yaml`, as tools que cada um expõe e quais estão liberadas. Custo zero."""
    cfg = load_config()
    try:
        servidores = mcp_client.carregar(cfg.mcp_path)
    except mcp_client.ConfigMCPInvalida as exc:
        _recusa(exc)
    if not servidores:
        console.print(f"Nenhum servidor em {cfg.mcp_path.name}. Veja mcp.example.yaml.")
        return
    for servidor in servidores:
        log = cfg.db_path.parent / f"mcp-{servidor.nome}.log"
        console.print(f"[bold]{servidor.nome}[/bold]: {' '.join(servidor.comando)}")
        try:
            remotas = mcp_client.listar_tools(servidor, log)
        except mcp_client.FalhaMCP as exc:
            console.print(f"  [red]fora do ar:[/red] {exc}")
            continue
        for t in remotas:
            liberada = t.name in servidor.tools
            marca = "[green]liberada[/green]" if liberada else "[dim]fora da allowlist[/dim]"
            console.print(f"  {t.name}: {marca} — {(t.description or '').splitlines()[0] if t.description else ''}")
        for faltando in sorted(set(servidor.tools) - {t.name for t in remotas}):
            console.print(f"  [yellow]{faltando}: na allowlist, mas o servidor não expõe[/yellow]")


@mcp_app.command("call")
def mcp_call(
    tool: str = typer.Argument(..., help="Nome da tool."),
    argumentos: str = typer.Argument("{}", help="Argumentos em JSON, ex: '{\"limite\": 5}'."),
) -> None:
    """Chama uma tool liberada direto, sem LLM. Serve para conferir o servidor."""
    import json

    cfg = load_config()
    try:
        args = json.loads(argumentos)
    except json.JSONDecodeError as exc:
        _recusa(f"argumentos não são JSON válido: {exc}")
    with executando(cfg, "mcp call") as ex:
        remotas = {t.nome: t for t in _tools_mcp(cfg, ex.status)}
        if tool not in remotas:
            for aviso in ex.status.warnings:
                console.print(f"[yellow]aviso:[/yellow] {aviso}")
            _recusa(f"`{tool}` não está liberada (veja `quilha mcp list`)")
        try:
            resultado = remotas[tool].funcao(None, **args)
        except mcp_client.FalhaMCP as exc:
            _recusa(exc)
        console.print_json(json.dumps(resultado, ensure_ascii=False, default=str))
        ex.delivered = True


def _tabela_competencias(linhas: list[dict], titulo: str) -> Table:
    tabela = Table(title=titulo, show_header=True, header_style="bold")
    for col, just in (
        ("slug", "left"),
        ("nome", "left"),
        ("cat.", "left"),
        ("peso", "right"),
        ("nível", "right"),
        ("evid.", "right"),
        ("situação", "left"),
    ):
        tabela.add_column(col, justify=just)
    cores = {
        "ok": "green",
        "nunca avaliada": "yellow",
        "sem evidencia": "red",
        "evidencia insuficiente": "red",
    }
    for linha in linhas:
        cor = cores.get(linha["situacao"], "white")
        tabela.add_row(
            linha["slug"],
            linha["nome"],
            linha["categoria"],
            str(linha["peso"]),
            "—" if linha["nivel"] is None else str(linha["nivel"]),
            str(linha["n_evidencias"]),
            f"[{cor}]{linha['situacao']}[/{cor}]",
        )
    return tabela


@comp_app.command("seed")
def comp_seed(
    arquivo: Optional[Path] = typer.Option(None, help=f"YAML da taxonomia (default: {SEED_PADRAO})."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Carrega a taxonomia de competências do YAML. Idempotente por slug."""
    cfg = load_config(db_path=db)
    caminho = arquivo or caminhos.base() / SEED_PADRAO
    with executando(cfg, "comp seed") as execucao:
        criadas, atualizadas = competencias.seed(execucao.conn, caminho)
        execucao.delivered = True
        console.print(
            f"[green]{criadas} criada(s)[/green], {atualizadas} atualizada(s) a partir de {caminho.name}."
        )


@comp_app.command("list")
def comp_list(
    categoria: Optional[str] = typer.Option(None, help="Filtra por categoria."),
    lacunas: bool = typer.Option(False, "--lacunas", help="Só o que ainda não sustenta currículo."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Lista as competências com nível vigente e contagem de evidências."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        linhas = competencias.listar(conn, categoria=categoria, so_lacunas=lacunas)
        if not linhas:
            console.print("Nenhuma competência. Rode `quilha comp seed`.")
            return
        titulo = "Lacunas" if lacunas else "Competências"
        console.print(_tabela_competencias(linhas, titulo))
    finally:
        conn.close()


@comp_app.command("remove")
def comp_remove(
    slug: str = typer.Argument(..., help="Slug da competência."),
    sim: bool = typer.Option(False, "--yes", "-y", help="Não pede confirmação."),
) -> None:
    """Tira uma competência sem histórico do banco e do YAML da taxonomia."""
    cfg = load_config()
    if not sim and not typer.confirm(f"Remover `{slug}` do banco e de {cfg.competencias_path.name}?"):
        raise typer.Exit(1)
    with executando(cfg, "comp remove") as ex:
        r = competencias.remover(ex.conn, slug)
        no_seed = competencias.tirar_do_seed(cfg.competencias_path, slug)
        console.print(f"`{slug}` ({r['nome']}) removida" + (f" do banco e de {cfg.competencias_path.name}."
                      if no_seed else f"; não estava em {cfg.competencias_path.name}."))
        if r["requisitos_desligados"] or r["estudos_desligados"]:
            console.print(f"[dim]{r['requisitos_desligados']} requisito(s) de vaga e "
                          f"{r['estudos_desligados']} estudo(s) ficaram sem competência.[/dim]")
        ex.delivered = True


@comp_app.command("show")
def comp_show(
    slug: str = typer.Argument(..., help="Slug da competência."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Mostra nível, justificativa e as evidências ligadas a uma competência."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        comp = competencias.buscar(conn, slug)
        nivel = "—" if comp["nivel"] is None else f"{comp['nivel']} — {competencias.NIVEIS[comp['nivel']]}"
        console.print(f"[bold]{comp['nome']}[/bold] ({comp['slug']}, peso {comp['peso']})")
        console.print(f"Nível: {nivel}")
        if comp["justificativa"]:
            console.print(f"Justificativa: {comp['justificativa']}")
        provas = competencias.evidencias(conn, slug)
        if not provas:
            console.print("[yellow]Sem evidência.[/yellow] Ligue um fato: `quilha comp evidence"
                          f" {slug} <nota.md#block-id>`")
            return
        tabela = Table(show_header=True, header_style="bold")
        tabela.add_column("block id", no_wrap=True)
        tabela.add_column("nota", no_wrap=True)
        tabela.add_column("força", justify="right")
        tabela.add_column("métrica")
        tabela.add_column("texto")
        for p in provas:
            texto = p["texto"] or "[red]fato sumiu do vault[/red]"
            tabela.add_row(
                f"^{p['block_id']}",
                Path(p["nota"]).name,
                str(p["forca"]),
                "sim" if p["tem_metrica"] else "não",
                texto[:60] + ("…" if len(texto) > 60 else ""),
            )
        console.print(tabela)
    except RegraViolada as exc:
        console.print(f"[red]recusado:[/red] {exc}")
        raise typer.Exit(1)
    finally:
        conn.close()


@comp_app.command("evidence")
def comp_evidence(
    slug: str = typer.Argument(..., help="Slug da competência."),
    referencia: str = typer.Argument(..., help="`nota.md#block-id` ou só `block-id`, se for único."),
    forca: int = typer.Option(2, "--forca", "-f", help="1 fraca, 2 média, 3 forte."),
    obs: Optional[str] = typer.Option(None, "--obs", help="Observação livre."),
    metrica: Optional[bool] = typer.Option(
        None, "--metrica/--sem-metrica", help="Sobrescreve a detecção automática de número medido."
    ),
    remover: bool = typer.Option(False, "--remover", help="Desfaz o vínculo em vez de criá-lo."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Liga (ou desliga, com --remover) uma competência a um fato do vault."""
    cfg = load_config(db_path=db)
    if remover:
        with executando(cfg, "comp evidence") as execucao:
            r = competencias.remover_evidencia(execucao.conn, slug, referencia)
            execucao.delivered = True
            console.print(f"[green]removido[/green] {slug} → {r['nota']}#{r['block_id']}")
            if r["nivel_sem_base"]:
                console.print(f"[yellow]{r['nivel_sem_base']}.[/yellow] Reavalie: "
                              f"`quilha comp assess {slug} <nivel> -j '...'`")
            _atualiza_nota_gerada(cfg, execucao.conn)
        return
    with executando(cfg, "comp evidence") as execucao:
        r = competencias.ligar_evidencia(
            execucao.conn, slug, referencia, forca=forca, tem_metrica=metrica, observacao=obs
        )
        execucao.delivered = True
        marca = "com métrica" if r["tem_metrica"] else "sem métrica"
        console.print(f"[green]ligado[/green] {slug} → {r['nota']}#{r['block_id']} ({marca})")
        console.print(f"  {r['texto'][:100]}")
        _atualiza_nota_gerada(cfg, execucao.conn)


@comp_app.command("assess")
def comp_assess(
    slug: str = typer.Argument(..., help="Slug da competência."),
    nivel: int = typer.Argument(..., help="0 a 4. Veja `quilha comp niveis`."),
    justificativa: str = typer.Option(
        ..., "--justificativa", "-j", help="O que você diria numa entrevista."
    ),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Declara seu nível numa competência. Recusado se a evidência não sustentar."""
    cfg = load_config(db_path=db)
    with executando(cfg, "comp assess") as execucao:
        r = competencias.avaliar(execucao.conn, slug, nivel, justificativa)
        execucao.delivered = True
        console.print(
            f"[green]{slug} → nível {r['nivel']}[/green] ({competencias.NIVEIS[r['nivel']]}),"
            f" {r['n_evidencias']} evidência(s)."
        )
        _atualiza_nota_gerada(cfg, execucao.conn)


def _atualiza_nota_gerada(cfg, conn) -> None:
    try:
        nota = competencias.atualizar_nota_exportada(conn, cfg.vault_path)
    except (OSError, writer.EscritaRecusada) as exc:  # a nota é espelho; falhar nela não desfaz a gravação
        console.print(f"[yellow]aviso:[/yellow] {competencias.NOTA_EXPORTADA}.md não foi atualizada — {exc}")
        return
    if nota:
        console.print(f"[dim]{nota.name} atualizada no vault.[/dim]")


@comp_app.command("export")
def comp_export(
    vault: Optional[Path] = typer.Option(None, help="Caminho do vault (default: VAULT_PATH)."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Escreve `Competencias.md` na raiz do vault: níveis e evidências com link para os fatos.

    É um espelho só de leitura; depois da primeira vez, `comp evidence` e `comp assess` o mantêm em dia.
    """
    cfg = load_config(vault_path=vault, db_path=db)
    with executando(cfg, "comp export") as execucao:
        try:
            r = writer.substituir_gerada(cfg.vault_path, competencias.NOTA_EXPORTADA,
                                         competencias.exportar_markdown(execucao.conn))
        except writer.EscritaRecusada as exc:
            raise RegraViolada(str(exc)) from exc
        execucao.delivered = True
        console.print(f"[green]{'criada' if r['criada'] else 'atualizada'}[/green] {r['caminho']}")


@app.command()
def backup(
    destino: Optional[Path] = typer.Option(
        None, help="Pasta das cópias (default: HERMES_BACKUP_DIR ou data/backups)."
    ),
    manter: int = typer.Option(10, help="Quantas cópias guardar; as mais antigas são apagadas."),
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Copia o banco. Evidências, níveis, vagas e estudos só existem nele — o vault não os reconstrói."""
    cfg = load_config(db_path=db)
    with executando(cfg, "backup") as execucao:
        caminho = store.backup(execucao.conn, destino or cfg.backup_dir, manter=manter)
        execucao.delivered = True
        console.print(f"[green]cópia gravada[/green] {caminho}")


@app.command()
def diagnostico() -> None:
    """Confere a instalação sem LLM e sem tocar no banco: caminhos, schema e PDF. Falha sai com 1."""
    from hermes.domain import diagnostico as diag

    itens = diag.rodar(load_config())
    tabela = Table(show_header=False)
    for i in itens:
        tabela.add_row("[green]ok[/green]" if i["ok"] else "[red]falha[/red]", i["item"], i["detalhe"])
    console.print(tabela)
    if not all(i["ok"] for i in itens):
        raise typer.Exit(1)


@app.command()
def serve(
    porta: int = typer.Option(8765, "--port", help="Porta em 127.0.0.1."),
) -> None:
    """API local do app desktop. Só escuta em 127.0.0.1 e exige o token de `HERMES_API_TOKEN`.

    Sem a variável, gera um token e mostra (útil para testar com curl). O app desktop passa o
    token pelo ambiente, nunca pela linha de comando, onde ele apareceria no `ps`.
    """
    import os
    import secrets

    import uvicorn

    from hermes.api.app import criar_app

    token = os.environ.get("HERMES_API_TOKEN") or ""
    if not token:
        token = secrets.token_urlsafe(32)
        console.print(f"[dim]token desta execução:[/dim] {token}")
    from hermes.domain import configuracao

    cfg = load_config()
    conn = store.connect(cfg.db_path)
    try:
        configuracao.inicializar(conn, cfg)
    finally:
        conn.close()
    uvicorn.run(criar_app(cfg, token), host="127.0.0.1", port=porta, log_level="warning")


@comp_app.command("niveis")
def comp_niveis() -> None:
    """A escala de níveis e o que cada um exige de evidência."""
    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("nível", justify="right")
    tabela.add_column("significado")
    tabela.add_column("exige")
    exigencias = {
        0: "—",
        1: "—",
        2: "1 evidência",
        3: "2 evidências, uma com número medido e fonte",
        4: "uma evidência com métrica E período (rodou em operação)",
    }
    for n, texto in competencias.NIVEIS.items():
        tabela.add_row(str(n), texto, exigencias[n])
    console.print(tabela)


@comp_app.command("coverage")
def comp_coverage(
    db: Optional[Path] = typer.Option(None, help="Caminho do banco (default: HERMES_DB)."),
) -> None:
    """Relatório de cobertura: o que já sustenta currículo e o que é lacuna."""
    cfg = load_config(db_path=db)
    conn = store.connect(cfg.db_path)
    try:
        resumo = competencias.cobertura(conn)
        if not resumo["total"]:
            console.print("Nenhuma competência. Rode `quilha comp seed`.")
            return
        console.print(
            f"[bold]{resumo['prontas']} de {resumo['total']}[/bold] competências sustentam currículo"
            " (nível ≥ 2 com evidência)."
        )
        for peso in (3, 2, 1):
            dados = resumo["por_peso"][peso]
            if dados["total"]:
                console.print(f"  peso {peso}: {dados['prontas']}/{dados['total']}")
        if resumo["lacunas"]:
            console.print(_tabela_competencias(resumo["lacunas"], "Lacunas (maior peso primeiro)"))
    finally:
        conn.close()


# ------------------------------------------------------------ candidaturas e e-mail (fase 10)


def _perfil_valido(cfg, slug: str) -> str:
    """`geral` ou um slug de `curriculos.yaml`; recusa dizendo quais existem."""
    if slug == candidaturas.GERAL:
        return slug
    try:
        perfis_cv.buscar(perfis_cv.carregar(cfg.perfis_cv_path), slug)
    except perfis_cv.PerfilInvalido as exc:
        _recusa(f"{exc} (ou `{candidaturas.GERAL}`)")
    return slug


@contextmanager
def _banco(cfg):
    conn = store.connect(cfg.db_path)
    try:
        yield conn
    except candidaturas.CandidaturaRecusada as exc:
        _recusa(exc)
    finally:
        conn.close()


@email_app.command("sync")
def email_sync(
    dias: int = typer.Option(30, help="Janela de busca no Gmail."),
    maximo: int = typer.Option(200, "--max", help="Máximo de e-mails lidos."),
    rotular: bool = typer.Option(False, "--rotular", help="Também aplica labels `Vagas/...` no Gmail."),
) -> None:
    """Lê o Gmail, classifica só os e-mails novos (LLM do usuário ou Jev) e liga cada um à candidatura."""
    from hermes.integracoes import caixa as caixas

    cfg = load_config()
    try:
        with triagem_email.classificador_configurado() as (classificador, modelo):
            with executando(cfg, "email sync") as ex:
                ex.model = modelo
                try:
                    caixa = caixas.abrir(cfg, rotular=rotular)
                except caixas.Indisponivel as exc:
                    ex.erro = str(exc)
                    _recusa(exc)
                try:
                    _sync_e_mostra(ex, caixa, classificador, dias, maximo, rotular)
                finally:
                    if hasattr(caixa, "fechar"):
                        caixa.fechar()
    except triagem_email.TriagemRecusada as exc:
        _recusa(exc)


def _sync_e_mostra(ex, caixa, classificador, dias: int, maximo: int, rotular: bool) -> None:
    r = triagem_email.sincronizar(ex.conn, caixa, classificador, dias, maximo, ex.status, rotular=rotular)
    console.print(f"{r['lidos']} lido(s), {r['ja_vistos']} já visto(s), {r['novos']} classificado(s); "
                  f"{r['ligados']} ligado(s) a candidatura.")
    for categoria, n in sorted(r["por_categoria"].items()):
        console.print(f"  {categoria:<22} {n}")
    if r["pendentes"]:
        console.print(f"[yellow]{r['pendentes']} e-mail(s) pendente(s):[/yellow] `quilha email pendentes`")
    for aviso in triagem_email.resumir_avisos(ex.status.warnings):
        console.print(f"[yellow]aviso:[/yellow] {aviso}", soft_wrap=True)
    if ex.status.tool_errors:
        console.print(f"[dim]{ex.status.tool_errors} e-mail(s) com erro não foram gravados: entram no próximo sync.[/dim]")
    if r["lidos"] >= maximo:
        console.print(f"[yellow]chegou ao --max {maximo}: e-mails mais antigos da janela ficaram de fora.[/yellow]")
    ex.delivered = r["novos"] > 0 or ex.status.tool_errors == 0


@email_app.command("testar")
def email_testar() -> None:
    """Conecta na caixa de EMAIL_ORIGEM (gmail ou imap) e conta os e-mails da semana. Custo zero."""
    from hermes.integracoes import caixa as caixas

    r = caixas.testar(load_config())
    console.print(f"[{'green' if r['ok'] else 'red'}]{r['origem']}:[/] {r['mensagem']}")
    if not r["ok"]:
        raise typer.Exit(1)


@email_app.command("corpos")
def email_corpos() -> None:
    """Busca no Gmail o corpo dos e-mails gravados antes de o banco guardar o texto. Não usa o Jev."""
    from hermes.integracoes.gmail import CaixaGmail, SemCredenciais

    cfg = load_config()
    with executando(cfg, "email corpos") as ex:
        try:
            caixa = CaixaGmail(cfg.gmail_dir)
        except SemCredenciais as exc:
            ex.erro = str(exc)
            _recusa(exc)
        r = triagem_email.preencher_corpos(ex.conn, caixa, ex.status)
        console.print(f"{r['preenchidos']} de {r['faltando']} e-mail(s) sem corpo preenchido(s).")
        for aviso in triagem_email.resumir_avisos(ex.status.warnings):
            console.print(f"[yellow]aviso:[/yellow] {aviso}", soft_wrap=True)
        ex.delivered = True


@email_app.command("pendentes")
def email_pendentes() -> None:
    """E-mails `revisar` e de processo sem candidatura ligada."""
    cfg = load_config()
    with _banco(cfg) as conn:
        linhas = candidaturas.emails_pendentes(conn)
        if not linhas:
            console.print("Nenhum e-mail pendente.")
            return
        tabela = Table("id", "data", "categoria", "empresa", "de", "assunto", header_style="bold")
        for l in linhas:
            tabela.add_row(str(l["id"]), l["recebido_em"][:10], l["categoria"], l["empresa_extraida"] or "—",
                           l["de"][:30], l["assunto"][:60])
        console.print(tabela)
        console.print("[dim]`quilha email corrigir <id> <categoria>` · `quilha email ligar <id> <candidatura>`[/dim]")


@email_app.command("ligar")
def email_ligar(email_id: int, candidatura_id: int) -> None:
    """Liga um e-mail a uma candidatura à mão."""
    cfg = load_config()
    with _banco(cfg) as conn:
        candidaturas.ligar_manual(conn, email_id, candidatura_id)
        console.print(f"e-mail {email_id} ligado à candidatura {candidatura_id}.")


@email_app.command("corrigir")
def email_corrigir(email_id: int, categoria: str) -> None:
    """Corrige a categoria do Jev (avanco, pendencia, inscricao_confirmada, reprovado, outro)."""
    cfg = load_config()
    with _banco(cfg) as conn:
        cid = candidaturas.corrigir(conn, email_id, categoria)
        destino = f"candidatura {cid}" if cid else "nenhuma candidatura (continua pendente se for processo)"
        console.print(f"e-mail {email_id} → {categoria}; {destino}.")


@email_app.command("avaliar")
def email_avaliar() -> None:
    """Acurácia do Jev contra as suas correções."""
    cfg = load_config()
    with _banco(cfg) as conn:
        r = triagem_email.avaliar(conn)
        if not r["rotuladas"]:
            console.print("Nenhum e-mail corrigido ainda: use `quilha email corrigir`.")
            return
        console.print(f"Rotulados: {r['rotuladas']} · para revisão: {r['revisao']}")
        if r["decididas"]:
            console.print(f"Acurácia nas decididas: {r['certas']}/{r['decididas']} = "
                          f"{r['certas'] / r['decididas']:.1%}")
        if r["p50"] is not None:
            console.print(f"Latência p50: {r['p50']} ms · p95: {r['p95']} ms")
        for e in r["erros"]:
            console.print(f"  [{e['final']} → {e['rotulo_manual']}] {e['assunto'][:80]}")


@app_app.command("list")
def app_list(
    status_: Optional[str] = typer.Option(None, "--status", help="enviada, em_processo, reprovada, cancelada."),
    pingadas: bool = typer.Option(False, "--pingadas", help="Só as sem perfil ou sem empresa."),
) -> None:
    """Candidaturas, da mais recente para a mais antiga."""
    cfg = load_config()
    with _banco(cfg) as conn:
        linhas = candidaturas.listar(conn, status_, pingadas)
        if not linhas:
            console.print("Nenhuma candidatura.")
            return
        tabela = Table("id", "enviada", "empresa", "título", "perfil", "status", "avanço", "e-mails",
                       header_style="bold")
        for l in linhas:
            tabela.add_row(str(l["id"]), l["enviada_em"][:10], l["empresa"] or "—", (l["titulo"] or "—")[:40],
                           l["perfil"] or "[yellow]?[/yellow]", l["status"], "sim" if l["teve_avanco"] else "",
                           str(l["n_emails"]))
        console.print(tabela)


@app_app.command("add")
def app_add(
    empresa: str = typer.Option(..., "--empresa"),
    perfil: str = typer.Option(..., "--perfil", help="Slug de curriculos.yaml ou `geral`."),
    titulo: Optional[str] = typer.Option(None, "--titulo"),
    data: Optional[str] = typer.Option(None, "--data", help="AAAA-MM-DD; padrão agora."),
) -> None:
    """Registra um envio feito fora do Hermes."""
    cfg = load_config()
    _perfil_valido(cfg, perfil)
    with _banco(cfg) as conn:
        cid = candidaturas.registrar_manual(conn, empresa, perfil, titulo, data)
        console.print(f"candidatura {cid}: {empresa} com `{perfil}`.")


@app_app.command("perfil")
def app_perfil(candidatura_id: int, perfil: str) -> None:
    """Diz qual currículo foi enviado (resolve uma pingada)."""
    cfg = load_config()
    _perfil_valido(cfg, perfil)
    with _banco(cfg) as conn:
        candidaturas.definir_perfil(conn, candidatura_id, perfil)
        console.print(f"candidatura {candidatura_id} → `{perfil}`.")


@app_app.command("cancelar")
def app_cancelar(candidatura_id: int) -> None:
    """Não foi enviada: sai da nota."""
    cfg = load_config()
    with _banco(cfg) as conn:
        candidaturas.cancelar(conn, candidatura_id)
        console.print(f"candidatura {candidatura_id} cancelada.")


@app_app.command("notas")
def app_notas() -> None:
    """Nota 0–5 de cada perfil pela taxa de avanço sobre envios maturados (21 dias ou com resposta)."""
    from datetime import date

    cfg = load_config()
    with _banco(cfg) as conn:
        r = candidaturas.notas_por_perfil(conn, date.today())
        if not r["perfis"]:
            console.print("Nenhuma candidatura com perfil ainda.")
        else:
            tabela = Table("perfil", "enviados", "maturados", "avanços", "taxa", "nota", "falta",
                           header_style="bold")
            for p in r["perfis"]:
                taxa = "—" if p["taxa"] is None else f"{p['taxa']:.0%}"
                valor = "—" if p["nota"] is None else str(p["nota"])
                tabela.add_row(p["perfil"], str(p["enviados"]), str(p["maturados"]), str(p["avancos"]),
                               taxa, valor, p["falta"])
            console.print(tabela)
        if r["pingadas"]:
            console.print(f"[yellow]{r['pingadas']} candidatura(s) sem perfil fora da nota:[/yellow] "
                          "`quilha app list --pingadas`")


if __name__ == "__main__":
    app()
