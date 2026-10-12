import pytest
from typer.testing import CliRunner

from hermes.cli import app
from hermes.config import load_config
from hermes.db import store

runner = CliRunner()


@pytest.fixture
def cfg_tmp(tmp_path, vault, monkeypatch):
    """Banco e vault isolados: nenhum teste toca o Obsidian ou o hermes.db reais."""
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "chave-de-teste")
    return load_config()


def test_check_vault_valido_sai_zero(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    resultado = runner.invoke(app, ["check", "--vault", str(vault)])
    assert resultado.exit_code == 0


def test_check_strict_falha_com_aviso(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    resultado = runner.invoke(app, ["check", "--vault", str(vault), "--strict"])
    assert resultado.exit_code == 1  # a nota sem fatos é aviso


def test_check_avisa_habilidade_do_perfil_sem_nota(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    yaml_cv = tmp_path / "curriculos.yaml"
    yaml_cv.write_text(
        "perfis:\n  - slug: x\n    cargo: {pt: a, en: b}\n    habilidades:\n"
        "      - rotulo: {pt: A, en: B}\n        itens: [Python, PyTorch]\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_CURRICULOS", str(yaml_cv))
    resultado = runner.invoke(app, ["check", "--vault", str(vault)])
    assert "PyTorch" in resultado.stdout
    assert "`Python`" not in resultado.stdout  # está no stack do Mirante


def test_check_com_curriculos_yaml_invalido_e_erro(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DB", str(tmp_path / "hermes.db"))
    yaml_cv = tmp_path / "curriculos.yaml"
    yaml_cv.write_text("perfis:\n  - cargo: {pt: a, en: b}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_CURRICULOS", str(yaml_cv))
    resultado = runner.invoke(app, ["check", "--vault", str(vault)])
    assert resultado.exit_code == 1
    assert "slug" in resultado.stdout


def test_check_vault_inexistente(tmp_path):
    resultado = runner.invoke(app, ["check", "--vault", str(tmp_path / "nao-existe")])
    assert resultado.exit_code == 1
    assert "não encontrado" in resultado.stdout


def test_index_grava_fatos_e_run(vault, tmp_path):
    db = tmp_path / "hermes.db"
    resultado = runner.invoke(app, ["index", "--vault", str(vault), "--db", str(db)])
    assert resultado.exit_code == 0
    conn = store.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 4
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        assert run["comando"] == "index"
        assert run["status"] == "success"
    finally:
        conn.close()


def test_index_sem_block_id_indexa_o_resto_e_fica_partial(vault, tmp_path):
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    nota.write_text(nota.read_text().replace(" ^pipeline", ""), encoding="utf-8")
    db = tmp_path / "hermes.db"
    resultado = runner.invoke(app, ["index", "--vault", str(vault), "--db", str(db)])
    assert resultado.exit_code == 0
    conn = store.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 3
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        assert run["status"] == "partial"
    finally:
        conn.close()


def test_index_bloqueado_pela_denylist(vault, tmp_path, monkeypatch):
    lista = tmp_path / "denylist.yaml"
    lista.write_text("termos:\n  - SistemaInterno\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_DENYLIST", str(lista))
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    nota.write_text(nota.read_text() + "\nUsa o SistemaInterno.\n", encoding="utf-8")

    db = tmp_path / "hermes.db"
    resultado = runner.invoke(app, ["index", "--vault", str(vault), "--db", str(db)])
    assert resultado.exit_code == 1
    conn = store.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        assert run["status"] == "failed"
    finally:
        conn.close()


def test_stats_roda_com_banco_vazio(tmp_path):
    resultado = runner.invoke(app, ["stats", "--db", str(tmp_path / "hermes.db")])
    assert resultado.exit_code == 0


# ------------------------------------------------------------------ chat


def _resposta(content="oi", prompt=10, completion=5):
    from types import SimpleNamespace

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


@pytest.fixture
def provedor(mocker):
    import litellm

    mocker.patch.object(litellm, "completion", return_value=_resposta())
    mocker.patch.object(litellm, "completion_cost", return_value=0.002)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    return litellm


def test_chat_pergunta_unica_responde_e_mostra_o_custo(cfg_tmp, provedor):
    resultado = runner.invoke(app, ["chat", "quem sou eu?"])
    assert resultado.exit_code == 0
    assert "oi" in resultado.output
    assert "US$ 0.0020" in resultado.output


def test_chat_grava_sessao_mensagens_e_run(cfg_tmp, provedor):
    runner.invoke(app, ["chat", "quem sou eu?"])
    conn = store.connect(cfg_tmp.db_path)

    sessao = conn.execute("SELECT * FROM agent_sessions").fetchone()
    assert sessao["finished_at"] and sessao["cost_usd"] == pytest.approx(0.002)

    papeis = [r["role"] for r in conn.execute("SELECT role FROM agent_messages ORDER BY idx")]
    assert papeis == ["user", "assistant"]

    run = conn.execute("SELECT * FROM runs WHERE comando = 'chat'").fetchone()
    assert run["status"] == "success"
    assert run["llm_calls"] == 1
    assert run["session_id"] == sessao["id"]
    assert run["model"]
    conn.close()


def test_chat_continue_retoma_a_sessao_anterior(cfg_tmp, provedor):
    runner.invoke(app, ["chat", "primeira"])
    runner.invoke(app, ["chat", "--continue", "segunda"])
    conn = store.connect(cfg_tmp.db_path)
    assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0] == 4
    conn.close()


def test_chat_sem_continue_abre_sessao_nova(cfg_tmp, provedor):
    runner.invoke(app, ["chat", "primeira"])
    runner.invoke(app, ["chat", "segunda"])
    conn = store.connect(cfg_tmp.db_path)
    assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 2
    conn.close()


def test_chat_registra_falha_do_provedor_na_tabela_runs(cfg_tmp, provedor, mocker):
    mocker.patch.object(provedor, "completion", side_effect=Exception("401 chave inválida"))
    resultado = runner.invoke(app, ["chat", "oi"])
    assert resultado.exit_code == 1

    conn = store.connect(cfg_tmp.db_path)
    run = conn.execute("SELECT * FROM runs WHERE comando = 'chat'").fetchone()
    assert run["status"] == "failed"
    assert "401" in run["error"]
    conn.close()


def test_chat_sem_pergunta_e_sem_terminal_recusa(cfg_tmp):
    """Sem TTY o REPL leria EOF na primeira pergunta e sairia calado, com código 0."""
    resultado = runner.invoke(app, ["chat"])
    assert resultado.exit_code == 2
    assert "sem terminal interativo" in resultado.output

    conn = store.connect(cfg_tmp.db_path)
    assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0  # nada executou
    conn.close()


def test_repl_encerrado_sem_pergunta_nao_deixa_sessao_vazia(cfg_tmp, provedor, mocker):
    mocker.patch("hermes.cli._tem_terminal", return_value=True)
    resultado = runner.invoke(app, ["chat"], input="")  # Ctrl-D na primeira pergunta
    assert resultado.exit_code == 0

    conn = store.connect(cfg_tmp.db_path)
    assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 0
    # a execução continua registrada, mas sem apontar para uma sessão que não existe mais
    run = conn.execute("SELECT * FROM runs WHERE comando = 'chat'").fetchone()
    assert run is not None and run["session_id"] is None
    conn.close()


def test_repl_com_perguntas_mantem_a_sessao(cfg_tmp, provedor, mocker):
    mocker.patch("hermes.cli._tem_terminal", return_value=True)
    resultado = runner.invoke(app, ["chat"], input="quem sou eu?\nsair\n")
    assert resultado.exit_code == 0

    conn = store.connect(cfg_tmp.db_path)
    assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0] == 2
    conn.close()


# ------------------------------------------------------------------ cv draft


def test_cv_draft_gera_pt_e_en_e_registra_as_versoes(cfg_tmp, banco, provedor, tmp_path, mocker):
    from hermes.domain import competencias, perfil

    (cfg_tmp.vault_path / perfil.ARQUIVO).write_text(perfil.TEMPLATE, encoding="utf-8")
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline que roda")

    ref = "Carreira/Projetos/Mirante.md#pipeline"
    mocker.patch.object(
        provedor,
        "completion",
        return_value=_resposta(
            '{"resumo": "Resumo.", "bullets": {"%s": "Construiu pipeline diário."}}' % ref
        ),
    )
    resultado = runner.invoke(app, ["cv", "draft", "--saida", str(tmp_path / "out")])
    assert resultado.exit_code == 0, resultado.output

    conn = store.connect(cfg_tmp.db_path)
    idiomas = [r["idioma"] for r in conn.execute("SELECT idioma FROM cv_versions ORDER BY idioma")]
    assert idiomas == ["en", "pt"]
    assert conn.execute("SELECT status FROM runs WHERE comando='cv draft'").fetchone()[0] == "success"
    conn.close()

    gerado = (tmp_path / "out" / "cv-pt.md").read_text(encoding="utf-8")
    assert "- Construiu pipeline diário. <!-- ^pipeline @ Carreira/Projetos/Mirante.md -->" in gerado


def test_cv_pdf_gera_markdown_json_e_pdf(cfg_tmp, banco, provedor, tmp_path, mocker):
    from hermes.domain import competencias, perfil

    (cfg_tmp.vault_path / perfil.ARQUIVO).write_text(perfil.TEMPLATE, encoding="utf-8")
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline que roda")
    mocker.patch.object(provedor, "completion",
                        return_value=_resposta('{"resumo": "Resumo.", "bullets": {}}'))

    resultado = runner.invoke(app, ["cv", "pdf", "--idioma", "pt", "--saida", str(tmp_path / "out")])
    assert resultado.exit_code == 0, resultado.output
    for nome in ("cv-pt.md", "cv-pt.json", "cv-pt.pdf"):
        assert (tmp_path / "out" / nome).is_file(), nome
    assert "1 página" in resultado.output


def test_cv_pdf_acima_do_limite_sai_com_1_e_diz_o_que_cortar(cfg_tmp, banco, provedor, tmp_path, mocker):
    from hermes.domain import competencias, pdf, perfil

    (cfg_tmp.vault_path / perfil.ARQUIVO).write_text(perfil.TEMPLATE, encoding="utf-8")
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline que roda")
    mocker.patch.object(provedor, "completion",
                        return_value=_resposta('{"resumo": "Resumo.", "bullets": {}}'))
    entradas = [{"secao": "projetos", "titulo": "Mirante", "linhas": 80}]
    mocker.patch.object(pdf, "compilar", side_effect=pdf.PaginasDemais(2, 1, entradas, tmp_path / "x.pdf"))

    resultado = runner.invoke(app, ["cv", "pdf", "--idioma", "pt", "--saida", str(tmp_path / "out")])
    assert resultado.exit_code == 1
    assert "Mirante" in resultado.output and "80" in resultado.output


def test_cv_draft_sem_fatos_recusa_e_mostra_a_cobertura(cfg_tmp, banco, provedor, tmp_path):
    from hermes.domain import perfil

    (cfg_tmp.vault_path / perfil.ARQUIVO).write_text(perfil.TEMPLATE, encoding="utf-8")
    resultado = runner.invoke(app, ["cv", "draft", "--saida", str(tmp_path / "out")])

    assert resultado.exit_code == 1
    assert "nada a gerar" in resultado.output
    assert "comp assess" in resultado.output
    assert "sustentam currículo" in resultado.output
    assert not (tmp_path / "out").exists()  # não cria pasta para não gerar nada


def test_cv_draft_sem_perfil_diz_o_que_criar(cfg_tmp, banco, provedor, tmp_path):
    resultado = runner.invoke(app, ["cv", "draft", "--saida", str(tmp_path / "out")])
    assert resultado.exit_code == 1
    assert "Perfil.md" in resultado.output


# ------------------------------------------------------------------------ vagas


@pytest.fixture
def vaga_arquivo(tmp_path):
    from pathlib import Path

    origem = Path(__file__).parent / "fixtures" / "vagas" / "aurora.txt"
    destino = tmp_path / "aurora.txt"
    destino.write_text(origem.read_text(encoding="utf-8"), encoding="utf-8")
    return destino


@pytest.fixture
def extracao(mocker):
    import litellm

    conteudo = (
        '{"empresa": "Aurora Saúde Digital", "titulo": "Analista de Automação", "requisitos": ['
        '{"texto": "Python básico", "tipo": "obrigatorio", "competencia_sugerida": "python", "confianca": 0.9},'
        '{"texto": "SQL básico", "tipo": "obrigatorio", "competencia_sugerida": "sql", "confianca": 0.9},'
        '{"texto": "Inglês", "tipo": "desejavel", "competencia_sugerida": "idioma-x", "confianca": 0.5}]}'
    )
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    return mocker.patch.object(litellm, "completion", return_value=_resposta(conteudo))


def test_job_add_grava_e_repetir_nao_gasta(cfg_tmp, banco, vaga_arquivo, extracao):
    primeira = runner.invoke(app, ["job", "add", str(vaga_arquivo)])
    assert primeira.exit_code == 0, primeira.output
    assert "gravada" in primeira.output and "Aurora Saúde Digital" in primeira.output
    assert "idioma-x" in primeira.output  # sugestão fora da taxonomia aparece

    segunda = runner.invoke(app, ["job", "add", str(vaga_arquivo)])
    assert segunda.exit_code == 0
    assert "já gravada" in segunda.output
    assert extracao.call_count == 1

    conn = store.connect(cfg_tmp.db_path)
    comandos = [r[0] for r in conn.execute("SELECT comando FROM runs ORDER BY id")]
    conn.close()
    assert comandos.count("job add") == 2


def test_job_add_sem_texto_explica_como_colar(cfg_tmp, mocker):
    mocker.patch("hermes.cli._tem_terminal", return_value=True)
    resultado = runner.invoke(app, ["job", "add"])
    assert resultado.exit_code == 2
    assert "hermes job add -" in resultado.output


def test_job_match_sem_texto_imprime_n_e_formula(cfg_tmp, banco, vaga_arquivo, extracao):
    runner.invoke(app, ["job", "add", str(vaga_arquivo)])
    extracao.reset_mock()

    resultado = runner.invoke(app, ["job", "match", "1", "--sem-texto"])

    assert resultado.exit_code == 0, resultado.output
    assert "score 0/100" in resultado.output
    assert "fórmula v1" in resultado.output
    assert "N=3 requisitos, 2 mapeados" in resultado.output
    assert "2 de 2 obrigatórios" in resultado.output  # o rich quebra a linha antes de "descobertos"
    extracao.assert_not_called()

    lista = runner.invoke(app, ["job", "list"])
    assert "analisado" in lista.output


def test_job_map_e_show(cfg_tmp, banco, vaga_arquivo, extracao):
    runner.invoke(app, ["job", "add", str(vaga_arquivo)])
    resultado = runner.invoke(app, ["job", "map", "3", "ingles"])
    assert resultado.exit_code == 0, resultado.output

    show = runner.invoke(app, ["job", "show", "1"])
    assert "ingles" in show.output

    recusa = runner.invoke(app, ["job", "map", "3", "cobol"])
    assert recusa.exit_code == 1
    assert "não existe" in recusa.output


def test_job_extrair_refaz_e_mostra_o_custo(cfg_tmp, banco, vaga_arquivo, extracao):
    runner.invoke(app, ["job", "add", str(vaga_arquivo)])
    repetida = runner.invoke(app, ["job", "add", str(vaga_arquivo)])
    assert "hermes job extrair 1" in repetida.output

    resultado = runner.invoke(app, ["job", "extrair", "1"])

    assert resultado.exit_code == 0, resultado.output
    assert "requisitos reextraídos" in resultado.output
    assert "US$" in resultado.output
    assert extracao.call_count == 2


# ---------------------------------------------------------------------- estudos


def test_study_log_e_week(cfg_tmp, banco):
    r = runner.invoke(app, ["study", "log", "40", "exercícios de JOIN", "--comp", "sql"])
    assert r.exit_code == 0, r.output
    assert "40 min em `sql`" in r.output

    semana = runner.invoke(app, ["study", "week"])
    assert "40 min declarados (sem plano para a semana)" in semana.output


def test_study_log_invalido_sai_com_erro(cfg_tmp, banco):
    r = runner.invoke(app, ["study", "log", "0", "nada"])
    assert r.exit_code == 1
    assert "maior que zero" in r.output


def test_study_git_e_confirm(cfg_tmp, banco, tmp_path, monkeypatch):
    import subprocess

    repo = tmp_path / "Projetos" / "meu-repo"
    repo.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "eu@x.com"], ["config", "user.name", "Eu"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "worker com retry"], check=True)
    monkeypatch.setenv("HERMES_REPOS_DIR", str(tmp_path / "Projetos"))

    git = runner.invoke(app, ["study", "git"])
    assert git.exit_code == 0, git.output
    assert "worker com retry" in git.output
    assert "hermes study confirm" in git.output

    confirma = runner.invoke(app, ["study", "confirm", "1", "60", "retry com backoff", "-c", "python"])
    assert confirma.exit_code == 0, confirma.output
    assert "ligada a 1 commit(s)" in confirma.output


def test_study_plan_grava_no_diario_so_com_confirmacao(cfg_tmp, banco, mocker):
    import litellm

    from hermes.db import store as store_mod

    with banco:
        job = banco.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('T', 'FDE', 'colado', 'x', 'h', ?)", (store_mod.utcnow(),)).lastrowid
        banco.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id)"
                      " VALUES (?, 'SQL', 'obrigatorio', (SELECT id FROM competencies WHERE slug='sql'))",
                      (job,))
    from hermes.domain import competencias

    competencias.avaliar(banco, "sql", 1, "só tutorial")  # lacuna de estudo, não de registro
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    mocker.patch.object(litellm, "completion", return_value=_resposta(
        '{"objetivo": "SQL", "itens": [{"competencia": "sql", "descricao": "JOINs", "minutos": 60}]}'))

    recusado = runner.invoke(app, ["study", "plan", "-m", "120", "--semana", "2026-W40"], input="n\n")
    assert recusado.exit_code == 0, recusado.output
    assert "nada escrito no vault" in recusado.output
    assert not (cfg_tmp.vault_path / "Diario" / "2026-W40.md").exists()

    aceito = runner.invoke(app, ["study", "plan", "-m", "120", "--semana", "2026-W40", "--substituir"],
                           input="y\n")
    assert aceito.exit_code == 0, aceito.output
    nota = (cfg_tmp.vault_path / "Diario" / "2026-W40.md").read_text()
    assert "- [ ] (60 min, `sql`) JOINs" in nota


# ---------------------------------------------------------------------- coletor


@pytest.fixture
def fontes_yaml(tmp_path, monkeypatch):
    caminho = tmp_path / "fontes.yaml"
    caminho.write_text(
        "fontes:\n  - {tipo: greenhouse, board: acme, empresa: Acme}\n"
        "  - {tipo: lever, board: beta, empresa: Beta}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_FONTES", str(caminho))
    return caminho


@pytest.fixture
def ats(mocker):
    """Greenhouse com uma vaga, Lever fora do ar. Tudo local."""
    import httpx

    mocker.patch("time.sleep")
    gh = {"jobs": [{"title": "Automation Engineer", "absolute_url": "https://acme.test/1",
                    "location": {"name": "Remote"},
                    "content": "&lt;p&gt;" + "Build RPA flows in Python. " * 20 + "&lt;/p&gt;"}]}

    def responder(url, **_):
        if "greenhouse" in url and "robots" not in url:
            return httpx.Response(200, json=gh, request=httpx.Request("GET", url))
        if "lever" in url and "robots" not in url:
            return httpx.Response(503, text="fora", request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    return mocker.patch.object(httpx, "get", side_effect=responder)


def test_job_collect_registra_run_parcial_e_fila(cfg_tmp, banco, fontes_yaml, ats):
    r = runner.invoke(app, ["job", "collect"])
    assert r.exit_code == 0, r.output
    assert "2 de 2 fonte(s) processada(s); 1 vaga(s) nova(s)" in r.output
    assert "hermes job extrair" in r.output

    conn = store.connect(cfg_tmp.db_path)
    run = conn.execute("SELECT status, started_at FROM runs WHERE comando = 'job collect'").fetchone()
    coletas = conn.execute("SELECT board, status FROM coletas WHERE execucao = ?",
                           (run["started_at"],)).fetchall()
    conn.close()
    assert run["status"] == "partial"  # uma fonte falhou: entregue, com aviso
    assert {(c["board"], c["status"]) for c in coletas} == {("acme", "ok"), ("beta", "falhou")}

    fila = runner.invoke(app, ["job", "fila"])
    assert "beta" in fila.output and "falhou" in fila.output


def test_job_collect_extrair_respeita_o_limite(cfg_tmp, banco, fontes_yaml, ats, extracao):
    r = runner.invoke(app, ["job", "collect", "--extrair", "1"])
    assert r.exit_code == 0, r.output
    assert "vaga 1: 3 requisito(s) extraído(s)" in r.output
    assert extracao.call_count == 1


def test_job_collect_sem_fontes_yaml(cfg_tmp, banco, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FONTES", str(tmp_path / "nao-existe.yaml"))
    r = runner.invoke(app, ["job", "collect"])
    assert r.exit_code == 1
    assert "fontes.example.yaml" in r.output


# ------------------------------------------------------------------------- MCP


@pytest.fixture
def mcp_yaml(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    servidor = Path(__file__).parent / "fixtures" / "mcp_servidor_falso.py"
    caminho = tmp_path / "mcp.yaml"
    caminho.write_text(
        "servidores:\n"
        f"  - {{nome: mirante, comando: [{sys.executable}, {servidor}], tools: [news_today, nao_existe]}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_MCP", str(caminho))
    return caminho


def test_mcp_list_mostra_allowlist(cfg_tmp, mcp_yaml):
    r = runner.invoke(app, ["mcp", "list"])
    assert r.exit_code == 0, r.output
    assert "news_today: liberada" in r.output
    assert "apagar_tudo: fora da allowlist" in r.output
    assert "nao_existe: na allowlist, mas o servidor não expõe" in r.output


def test_mcp_call_sem_llm(cfg_tmp, mcp_yaml):
    r = runner.invoke(app, ["mcp", "call", "news_today", '{"limite": 1}'])
    assert r.exit_code == 0, r.output
    assert "Selic mantida" in r.output

    recusa = runner.invoke(app, ["mcp", "call", "apagar_tudo"])
    assert recusa.exit_code == 1
    assert "não está liberada" in recusa.output


def test_chat_registra_as_tools_mcp(cfg_tmp, mcp_yaml, provedor):
    r = runner.invoke(app, ["chat", "oi"])
    assert r.exit_code == 0, r.output
    assert "MCP: news_today" in r.output
    enviadas = [t["function"]["name"] for t in provedor.completion.call_args.kwargs["tools"]]
    assert "news_today" in enviadas and "apagar_tudo" not in enviadas


def test_index_em_pasta_sem_carreira_recusa_e_nao_zera(vault, tmp_path):
    db = tmp_path / "hermes.db"
    assert runner.invoke(app, ["index", "--vault", str(vault), "--db", str(db)]).exit_code == 0
    outra = tmp_path / "outra"
    outra.mkdir()
    resultado = runner.invoke(app, ["index", "--vault", str(outra), "--db", str(db)])
    assert resultado.exit_code == 1
    assert "Carreira/" in resultado.output
    conn = store.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 4
    finally:
        conn.close()


def test_chat_mostra_a_resposta_enquanto_chega_sem_repetir(cfg_tmp, provedor, mocker):
    from tests.streaming import chunk

    impressos = []
    mocker.patch.object(provedor, "completion", return_value=iter([chunk("Olá, "), chunk("tudo certo.", finish="stop")]))
    from hermes import cli as cli_mod
    original = cli_mod.console.print
    mocker.patch.object(cli_mod.console, "print", side_effect=lambda *a, **k: (impressos.append((a, k)), original(*a, **k)))
    resultado = runner.invoke(app, ["chat", "oi"])
    assert resultado.exit_code == 0
    assert resultado.output.count("Olá, tudo certo.") == 1
    trechos = [a[0] for a, k in impressos if k.get("end") == ""]
    assert trechos == ["Olá, ", "tudo certo."]  # saíram um a um, não só no fim


def test_chat_ctrl_c_para_o_turno_sem_sair(cfg_tmp, provedor, mocker):
    import os
    import signal

    from tests.streaming import chunk

    def chunks():
        yield chunk("Comparando ")
        os.kill(os.getpid(), signal.SIGINT)
        yield chunk("as vagas.", finish="stop")

    mocker.patch.object(provedor, "completion", return_value=chunks())
    resultado = runner.invoke(app, ["chat", "compara"])
    assert resultado.exit_code == 0, resultado.output
    assert "parado" in resultado.output
    conn = store.connect(cfg_tmp.db_path)
    assert [r["content"] for r in conn.execute("SELECT content FROM agent_messages ORDER BY idx")] == ["compara", "Comparando "]
    conn.close()
