"""Estudos: só o que você declara vira sessão; commit é sinal; o plano sai das lacunas das vagas."""

import json
import subprocess
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from hermes.domain import atividade, competencias, estudos
from hermes.run_status import RunStatus
from hermes.vault import writer

# ------------------------------------------------------------------- semana ISO


def test_semana_iso_na_virada_do_ano():
    assert estudos.semana_iso(date(2026, 1, 1)) == "2026-W01"
    assert estudos.semana_iso(date(2027, 1, 1)) == "2026-W53"


def test_semana_fora_do_formato_recusa(banco):
    with pytest.raises(estudos.EstudoRecusado, match="ISO"):
        estudos.resumo_semana(banco, "2026-39")


# ---------------------------------------------------------------------- log


def test_log_grava_sessao_declarada(banco):
    r = estudos.log_study(banco, 45, "  exercícios de JOIN  ", slug="sql", dificuldade=3)
    linha = banco.execute("SELECT minutos, o_que_fez, data FROM study_sessions").fetchone()
    assert (linha["minutos"], linha["o_que_fez"]) == (45, "exercícios de JOIN")
    assert linha["data"] == date.today().isoformat()
    assert r["competencia"] == "sql"


@pytest.mark.parametrize(
    "kwargs, erro",
    [
        ({"minutos": 0, "o_que_fez": "x"}, "maior que zero"),
        ({"minutos": 13 * 60, "o_que_fez": "x"}, "sessão só"),
        ({"minutos": 30, "o_que_fez": "  "}, "o que você fez"),
        ({"minutos": 30, "o_que_fez": "x", "slug": "cobol"}, "não existe"),
        ({"minutos": 30, "o_que_fez": "x", "dificuldade": 9}, "1 a 5"),
        ({"minutos": 30, "o_que_fez": "x", "data": "ontem"}, "AAAA-MM-DD"),
        ({"minutos": 30, "o_que_fez": "x", "data": (date.today() + timedelta(days=1)).isoformat()},
         "futuro"),
    ],
)
def test_log_recusa_registro_invalido(banco, kwargs, erro):
    with pytest.raises(estudos.EstudoRecusado, match=erro):
        estudos.log_study(banco, **kwargs)
    assert banco.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0] == 0


def test_resumo_da_semana_soma_por_competencia(banco):
    hoje = date.today()
    estudos.log_study(banco, 30, "a", slug="sql")
    estudos.log_study(banco, 20, "b", slug="sql")
    estudos.log_study(banco, 15, "c")
    estudos.log_study(banco, 99, "semana passada", data=(hoje - timedelta(days=7)).isoformat())

    r = estudos.resumo_semana(banco)
    assert r["minutos"] == 65
    assert r["por_competencia"] == {"sql": 50, "(sem competência)": 15}
    assert r["plano"] is None


# ------------------------------------------------------------------- git


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path):
    """Dois repositórios reais: um com commits seus e de outra pessoa, um vazio."""
    raiz = tmp_path / "Projetos"
    meu = raiz / "doc-qa-agent"
    vazio = raiz / "vazio"
    for r in (meu, vazio):
        r.mkdir(parents=True)
        _git(r, "init", "-q")
        _git(r, "config", "user.email", "eu@exemplo.com")
        _git(r, "config", "user.name", "Eu")
    (raiz / "nao-e-repo").mkdir()
    for i, autor in enumerate(["eu@exemplo.com", "eu@exemplo.com", "bot@exemplo.com"]):
        (meu / f"a{i}.txt").write_text(str(i))
        _git(meu, "add", ".")
        _git(meu, "-c", f"user.email={autor}", "commit", "-q", "-m", f"commit {i}",
             f"--author=Alguém <{autor}>")
    return raiz


def test_descobre_so_pastas_com_git(repos):
    assert [r.name for r in atividade.descobrir_repos(repos)] == ["doc-qa-agent", "vazio"]


def test_commit_vira_sinal_e_so_os_seus(banco, repos):
    status = RunStatus()
    r = atividade.git_activity(banco, 1, repos_conhecidos=tuple(atividade.descobrir_repos(repos)),
                               status=status)

    assert r["sinais_novos"] == 2  # o commit do bot não é sinal de estudo seu
    assert [s["resumo"] for s in r["pendentes"]["doc-qa-agent"]] == ["commit 1", "commit 0"]
    assert status.warnings == []  # repositório sem commit não é erro
    # commit nunca vira estudo sozinho
    assert banco.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0] == 0
    estados = {e for (e,) in banco.execute("SELECT estado FROM activity_signals")}
    assert estados == {"perguntado"}


def test_ler_de_novo_nao_duplica_sinal(banco, repos):
    conhecidos = tuple(atividade.descobrir_repos(repos))
    atividade.git_activity(banco, 1, repos_conhecidos=conhecidos)
    segunda = atividade.git_activity(banco, 1, repos_conhecidos=conhecidos)
    assert segunda["sinais_novos"] == 0
    assert banco.execute("SELECT COUNT(*) FROM activity_signals").fetchone()[0] == 2


def test_repositorio_desconhecido_vira_aviso(banco, repos):
    status = RunStatus()
    atividade.git_activity(banco, 1, ["nao-existe"],
                           repos_conhecidos=tuple(atividade.descobrir_repos(repos)), status=status)
    assert any("nao-existe" in a for a in status.warnings)


def test_confirmar_cria_uma_sessao_com_os_minutos_declarados(banco, repos):
    atividade.git_activity(banco, 1, repos_conhecidos=tuple(atividade.descobrir_repos(repos)))
    ids = [i for (i,) in banco.execute("SELECT id FROM activity_signals")]

    sessao = atividade.confirmar(banco, ids, 90, "refatorei o worker", slug="python")

    assert banco.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0] == 1
    assert sessao["minutos"] == 90
    linhas = banco.execute("SELECT estado, session_id FROM activity_signals").fetchall()
    assert {(l["estado"], l["session_id"]) for l in linhas} == {("confirmado", sessao["id"])}

    with pytest.raises(atividade.AtividadeRecusada, match="já resolvido"):
        atividade.confirmar(banco, ids[:1], 10, "de novo")


def test_ignorar_tira_da_lista(banco, repos):
    conhecidos = tuple(atividade.descobrir_repos(repos))
    atividade.git_activity(banco, 1, repos_conhecidos=conhecidos)
    ids = [i for (i,) in banco.execute("SELECT id FROM activity_signals")]
    assert atividade.ignorar(banco, ids)["ignorados"] == 2
    assert atividade.git_activity(banco, 1, repos_conhecidos=conhecidos)["pendentes"] == {}


def test_confirmar_sinal_inexistente_recusa(banco):
    with pytest.raises(atividade.AtividadeRecusada, match="inexistente"):
        atividade.confirmar(banco, [42], 30, "x")


# ------------------------------------------------------------------- plano


def _resposta(conteudo):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(conteudo), tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=200),
    )


@pytest.fixture
def provedor(mocker):
    import litellm

    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    return mocker.patch.object(litellm, "completion")


@pytest.fixture
def com_vaga(banco):
    """Uma vaga aberta pedindo sql (obrigatório) e inglês (desejável), ambos abaixo do nível 2."""
    from hermes.db import store

    with banco:
        job = banco.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Aurora Saúde Digital', 'FDE', 'colado', 'x', 'h', ?)", (store.utcnow(),)
        ).lastrowid
        for texto, tipo, slug in (("SQL", "obrigatorio", "sql"), ("Inglês", "desejavel", "ingles"),
                                  ("Python", "obrigatorio", "python")):
            banco.execute(
                "INSERT INTO job_requirements (job_id, texto, tipo, competency_id)"
                " VALUES (?, ?, ?, (SELECT id FROM competencies WHERE slug = ?))",
                (job, texto, tipo, slug),
            )
    # python já sustentado: não é lacuna. sql em nível 1: lacuna de estudo, não de registro
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    competencias.avaliar(banco, "sql", 1, "só fiz tutorial")
    return job


def test_lacunas_vem_das_vagas_abertas(com_vaga, banco):
    lacunas = estudos.lacunas_de_vagas(banco)
    assert [g["slug"] for g in lacunas] == ["sql", "ingles"]  # obrigatória primeiro
    assert lacunas[0]["obrigatorio_em"] == [com_vaga]


def test_plano_valida_o_que_o_modelo_propos(com_vaga, banco, provedor):
    provedor.return_value = _resposta({
        "objetivo": "Fechar SQL",
        "itens": [
            {"competencia": "sql", "descricao": "10 exercícios de JOIN", "recurso": None, "minutos": 90},
            {"competencia": "python", "descricao": "não é lacuna", "minutos": 30},
            {"competencia": "ingles", "descricao": "estourar o teto", "minutos": 200},
            {"competencia": "ingles", "descricao": "podcast técnico", "recurso": "null", "minutos": 60},
        ],
    })
    status = RunStatus()
    plano = estudos.plan_week(banco, 180, "2026-W40", status=status)

    assert [i["descricao"] for i in plano["itens"]] == ["10 exercícios de JOIN", "podcast técnico"]
    assert plano["minutos_alvo"] == 150
    assert plano["itens"][0]["job_id"] == com_vaga
    assert plano["itens"][1]["recurso"] is None
    assert any("`python` não é uma lacuna de estudo" in a for a in status.warnings)
    assert any("cortado" in a for a in status.warnings)
    n = banco.execute("SELECT COUNT(*) FROM plan_items").fetchone()[0]
    assert n == 2


def test_nunca_avaliada_com_fato_no_vault_vira_item_de_registro(com_vaga, banco, provedor):
    """`ingles` nunca avaliada e sem fato: estuda. `sql` nunca avaliada com ^sql-ddl no vault:
    o item é ligar a evidência e declarar, não reaprender SQL."""
    with banco:  # desfaz o nível 1 do fixture: sql volta a "nunca avaliada"
        banco.execute("DELETE FROM competency_state WHERE competency_id ="
                      " (SELECT id FROM competencies WHERE slug='sql')")
    provedor.return_value = _resposta(
        {"objetivo": "o", "itens": [{"competencia": "ingles", "descricao": "podcast", "minutos": 60}]})

    plano = estudos.plan_week(banco, 120, "2026-W40")

    sql = next(i for i in plano["itens"] if i["competencia"] == "sql")
    assert "^sql-ddl" in sql["descricao"] and "comp evidence sql" in sql["descricao"]
    assert sql["minutos_alvo"] == estudos.MINUTOS_DECLARAR
    prompt = provedor.call_args.kwargs["messages"][1]["content"]
    assert "- sql" not in prompt and "- ingles" in prompt  # o modelo só vê lacuna de estudo
    assert plano["minutos_alvo"] == estudos.MINUTOS_DECLARAR + 60


def test_so_lacuna_de_registro_nao_chama_o_modelo(banco, provedor):
    from hermes.db import store

    with banco:
        job = banco.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('T', 'X', 'colado', 'x', 'h2', ?)", (store.utcnow(),)).lastrowid
        banco.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id)"
                      " VALUES (?, 'Python', 'obrigatorio', (SELECT id FROM competencies WHERE slug='python'))",
                      (job,))
    plano = estudos.plan_week(banco, 60, "2026-W40")

    provedor.assert_not_called()
    assert plano["usou_modelo"] is False
    assert [i["competencia"] for i in plano["itens"]] == ["python"]
    assert "^pipeline" in plano["itens"][0]["descricao"]


def test_evidencia_ligada_sem_nivel_vira_item_de_declarar(banco, provedor):
    from hermes.db import store

    competencias.ligar_evidencia(banco, "sql", "sql-ddl", forca=3)
    with banco:
        job = banco.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('T', 'X', 'colado', 'x', 'h3', ?)", (store.utcnow(),)).lastrowid
        banco.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id)"
                      " VALUES (?, 'SQL', 'obrigatorio', (SELECT id FROM competencies WHERE slug='sql'))",
                      (job,))
    plano = estudos.plan_week(banco, 60, "2026-W40")

    provedor.assert_not_called()
    assert plano["itens"][0]["descricao"].startswith("Declarar o nível de `sql`")
    assert "^sql-ddl" in plano["itens"][0]["descricao"]


def test_candidatos_casam_tag_com_parte_do_slug_e_pulam_os_ligados(banco):
    assert [c["block_id"] for c in competencias.fatos_candidatos(banco, "sql")] == ["sql-ddl"]
    competencias.ligar_evidencia(banco, "sql", "sql-ddl", forca=3)
    assert competencias.fatos_candidatos(banco, "sql") == []
    assert competencias.fatos_candidatos(banco, "ingles") == []


def test_plano_repetido_exige_substituir(com_vaga, banco, provedor):
    provedor.return_value = _resposta(
        {"objetivo": "o", "itens": [{"competencia": "sql", "descricao": "d", "minutos": 60}]})
    estudos.plan_week(banco, 120, "2026-W40")
    with pytest.raises(estudos.EstudoRecusado, match="substituir"):
        estudos.plan_week(banco, 120, "2026-W40")
    estudos.plan_week(banco, 120, "2026-W40", substituir=True)
    assert banco.execute("SELECT COUNT(*) FROM plan_items").fetchone()[0] == 1
    assert provedor.call_count == 2


def test_plano_sem_lacuna_nao_gasta(banco, provedor):
    with pytest.raises(estudos.EstudoRecusado, match="nenhuma lacuna"):
        estudos.plan_week(banco, 120)
    provedor.assert_not_called()


def test_resumo_compara_com_o_plano(com_vaga, banco, provedor):
    semana = estudos.semana_iso()
    provedor.return_value = _resposta(
        {"objetivo": "o", "itens": [{"competencia": "sql", "descricao": "JOINs", "minutos": 60}]})
    estudos.plan_week(banco, 120, semana)
    estudos.log_study(banco, 40, "JOINs", slug="sql")

    r = estudos.resumo_semana(banco, semana)
    assert r["minutos_alvo"] == 60
    assert r["plano"]["itens"][0]["minutos_feitos"] == 40


def test_markdown_do_plano_e_o_que_foi_gravado():
    plano = {"semana": "2026-W40", "objetivo": "SQL", "minutos_alvo": 60, "minutos_disponiveis": 120,
             "itens": [{"competencia": "sql", "descricao": "JOINs", "recurso": None, "minutos_alvo": 60}]}
    md = estudos.markdown_do_plano(plano)
    assert "- [ ] (60 min, `sql`) JOINs" in md
    assert "Total: 60 de 120" in md


# ------------------------------------------------------------------- vault


def test_writer_so_acrescenta(tmp_path):
    writer.acrescentar(tmp_path, "Diario", "2026-W40", "primeiro", titulo="Semana 2026-W40")
    r = writer.acrescentar(tmp_path, "Diario", "2026-W40", "segundo")
    texto = (tmp_path / "Diario" / "2026-W40.md").read_text()
    assert texto == "# Semana 2026-W40\n\nprimeiro\n\nsegundo\n"
    assert r["criada"] is False


@pytest.mark.parametrize("pasta, nome", [("Carreira", "x"), ("Diario", "../Carreira/x"),
                                         ("Diario", ".oculta"), ("Diario", "")])
def test_writer_recusa_fora_das_pastas_liberadas(tmp_path, pasta, nome):
    with pytest.raises(writer.EscritaRecusada):
        writer.acrescentar(tmp_path, pasta, nome, "x")
    assert not (tmp_path / "Carreira").exists()


# ------------------------------------------------------------- roteiro de entrevista


def test_roteiro_usa_as_lacunas_da_vaga(com_vaga, banco, provedor):
    from hermes.domain import candidaturas

    cid = candidaturas.registrar_do_cv(banco, com_vaga, None, None)
    provedor.return_value = _resposta({"roteiro": [
        {"tema": "SQL", "o_que_revisar": "JOIN e GROUP BY", "pergunta_provavel": "Como você acharia duplicados?"},
        {"tema": "", "o_que_revisar": "sem tema", "pergunta_provavel": "ignorado"},
        "não é objeto",
    ]})
    r = estudos.roteiro_entrevista(banco, cid)
    assert r["candidatura_id"] == cid
    assert r["lacunas"] == ["SQL", "Inglês"]  # python já sustentado não entra
    assert [i["tema"] for i in r["roteiro"]] == ["SQL"]
    entrada = provedor.call_args.kwargs["messages"][1]["content"]
    assert "SQL" in entrada and "Python" not in entrada


def test_roteiro_recusa_candidatura_sem_vaga(banco, provedor):
    from hermes.domain import candidaturas

    cid = candidaturas.registrar_manual(banco, "Orla Tech", "geral")
    with pytest.raises(estudos.EstudoRecusado, match="ligue a candidatura a uma vaga"):
        estudos.roteiro_entrevista(banco, cid)
    provedor.assert_not_called()


def test_roteiro_recusa_vaga_sem_lacunas(com_vaga, banco, provedor):
    from hermes.domain import candidaturas

    for slug in ("sql", "ingles"):
        competencias.ligar_evidencia(banco, slug, "pipeline", forca=3)
        competencias.avaliar(banco, slug, 2, "usado no pipeline")
    cid = candidaturas.registrar_do_cv(banco, com_vaga, None, None)
    with pytest.raises(estudos.EstudoRecusado, match="não tem lacunas"):
        estudos.roteiro_entrevista(banco, cid)
    provedor.assert_not_called()


def test_roteiro_sem_tema_valido_mantem_o_anterior(com_vaga, banco, provedor):
    from hermes.domain import candidaturas

    cid = candidaturas.registrar_do_cv(banco, com_vaga, None, None)
    provedor.return_value = _resposta({"roteiro": [{"tema": "SQL", "o_que_revisar": "JOINs", "pergunta_provavel": "?"}]})
    estudos.roteiro_entrevista(banco, cid)
    provedor.return_value = _resposta({"roteiro": [{"tema": ""}, "lixo"]})
    with pytest.raises(estudos.EstudoRecusado, match="roteiro anterior"):
        estudos.roteiro_entrevista(banco, cid)
    salvo = banco.execute("SELECT roteiro FROM candidaturas WHERE id = ?", (cid,)).fetchone()[0]
    assert "SQL" in salvo


def test_primeiro_roteiro_vazio_nao_fala_de_anterior(com_vaga, banco, provedor):
    from hermes.domain import candidaturas as cand

    cid = cand.registrar_do_cv(banco, com_vaga, None, None)
    provedor.return_value = _resposta({"roteiro": [{"tema": ""}]})
    with pytest.raises(estudos.EstudoRecusado) as exc:
        estudos.roteiro_entrevista(banco, cid)
    assert "anterior" not in str(exc.value) and "tente" in str(exc.value).lower()
