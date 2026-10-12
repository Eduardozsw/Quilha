"""Seleção do currículo: determinística, sem LLM, e com a origem colada em cada fato."""

import pytest

from hermes.domain import competencias, curriculo


@pytest.fixture
def com_evidencias(banco):
    """python (peso 3) e sql (peso 2), ambas em nível 2, com fatos do vault ligados."""
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.ligar_evidencia(banco, "python", "testes", forca=2)
    competencias.ligar_evidencia(banco, "sql", "sql-ddl", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    competencias.avaliar(banco, "sql", 2, "DDL à mão")
    return banco


def test_sem_nivel_declarado_nao_entra_nada(banco):
    """Evidência ligada não basta: sem nível, o fato não sustenta currículo."""
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    assert curriculo.selecionar(banco) == []


def test_ordena_por_peso_da_competencia_vezes_forca_da_evidencia(com_evidencias):
    selecao = curriculo.selecionar(com_evidencias)
    forcas = [f["forca"] for f in selecao]
    assert forcas == sorted(forcas, reverse=True)
    assert selecao[0]["block_id"] == "pipeline"  # python(3) × forca(3) = 9
    assert selecao[0]["forca"] == 9


def test_todo_fato_carrega_a_origem_no_formato_do_prompt(com_evidencias):
    for fato in curriculo.selecionar(com_evidencias):
        assert fato["origem"] == f"^{fato['block_id']} @ {fato['nota']}"
        assert fato["referencia"] == f"{fato['nota']}#{fato['block_id']}"


def test_fato_que_prova_duas_competencias_entra_uma_vez_so(com_evidencias):
    competencias.ligar_evidencia(com_evidencias, "sql", "pipeline", forca=1)
    selecao = curriculo.selecionar(com_evidencias)

    pipeline = [f for f in selecao if f["block_id"] == "pipeline"]
    assert len(pipeline) == 1
    assert pipeline[0]["competencias"] == ["python", "sql"]
    assert pipeline[0]["forca"] == 9  # fica com a maior, não com a soma


def test_metrica_desempata(com_evidencias):
    """`testes` (python 3×2) e `sql-ddl` (sql 2×3) empatam em 6. Quem tem número com fonte
    passa na frente: num currículo de uma página, o bullet com N vale mais que o sem."""
    selecao = curriculo.selecionar(com_evidencias)
    empatados = [f["block_id"] for f in selecao if f["forca"] == 6]
    assert empatados == ["testes", "sql-ddl"]
    assert [f["tem_metrica"] for f in selecao if f["forca"] == 6] == [True, False]


def test_limite_corta_os_mais_fracos(com_evidencias):
    selecao = curriculo.selecionar(com_evidencias, limite=2)
    assert len(selecao) == 2
    assert [f["block_id"] for f in selecao] == ["pipeline", "testes"]


def test_evidencia_orfa_nao_entra(com_evidencias):
    """O block id sumiu do vault: a evidência continua no banco, o fato não existe mais."""
    from hermes.db import store

    store.reindex_facts(com_evidencias, [])
    assert curriculo.selecionar(com_evidencias) == []


def test_saida_e_estavel_entre_execucoes(com_evidencias):
    assert curriculo.selecionar(com_evidencias) == curriculo.selecionar(com_evidencias)


# --------------------------------------------------------- redação e montagem


@pytest.fixture
def perfil_dict():
    return {
        "nome": "Fulano de Tal",
        "cargo_alvo": "Desenvolvedor de Automação",
        "email": "fulano@exemplo.com",
        "cidade": "Curitiba, PR",
        "formacao": [{"curso": "Ciência da Computação", "instituicao": "UFPR", "periodo": "2024–2027"}],
        "idiomas": ["Português (nativo)"],
    }


def test_origem_de_todo_bullet_vem_do_codigo_nao_do_modelo(com_evidencias, perfil_dict):
    """O DoD da fase: todo bullet rastreável. Mesmo sem o modelo reescrever nada."""
    selecao = curriculo.selecionar(com_evidencias)
    markdown = curriculo.montar(perfil_dict, selecao, {"resumo": "", "bullets": {}}, "pt")

    bullets_de_fato = [l for l in markdown.splitlines() if l.startswith("- ") and "<!--" in l]
    assert len(bullets_de_fato) == len(selecao)
    for fato in selecao:
        assert f"<!-- {fato['origem']} -->" in markdown
        assert fato["texto"] in markdown  # sem redação, entra o texto do vault

    # formação não é fato do vault: não carrega origem porque não há o que auditar
    assert "- Ciência da Computação · UFPR · 2024–2027" in markdown


def test_montagem_respeita_o_idioma(com_evidencias, perfil_dict):
    selecao = curriculo.selecionar(com_evidencias)
    vazio = {"resumo": "", "bullets": {}}
    assert "## Projetos" in curriculo.montar(perfil_dict, selecao, vazio, "pt")
    assert "## Projects" in curriculo.montar(perfil_dict, selecao, vazio, "en")


def test_contagem_de_palavras_ignora_a_rastreabilidade(perfil_dict):
    markdown = "# Nome\n- Fez uma coisa <!-- ^muito-longo-id @ Carreira/Projetos/Nota.md -->\n"
    assert curriculo.contar_palavras(markdown) == 4  # "Nome", "Fez", "uma", "coisa"


def _resposta_json(texto):
    from types import SimpleNamespace

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=texto, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


@pytest.fixture
def provedor_redacao(mocker):
    import litellm

    mocker.patch.object(litellm, "completion_cost", return_value=0.0005)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["response_format"])
    return mocker.patch.object(litellm, "completion")


def test_redacao_do_modelo_substitui_o_texto(com_evidencias, perfil_dict, provedor_redacao):
    from hermes.run_status import RunStatus

    selecao = curriculo.selecionar(com_evidencias, limite=1)
    ref = selecao[0]["referencia"]
    provedor_redacao.return_value = _resposta_json(
        '{"resumo": "Resumo curto.", "bullets": {"%s": "Construiu pipeline diário em Python."}}' % ref
    )
    redacao = curriculo.redigir(selecao, perfil_dict, "pt", RunStatus())
    assert redacao["bullets"][ref] == "Construiu pipeline diário em Python."
    assert redacao["resumo"] == "Resumo curto."


def test_referencia_inventada_pelo_modelo_e_descartada(com_evidencias, perfil_dict, provedor_redacao):
    """O modelo reescreve fatos; não acrescenta. Bullet sem origem real não entra."""
    from hermes.run_status import RunStatus

    selecao = curriculo.selecionar(com_evidencias, limite=1)
    provedor_redacao.return_value = _resposta_json(
        '{"resumo": "", "bullets": {"Inventada.md#nao-existe": "Liderou equipe de 10 pessoas."}}'
    )
    status = RunStatus()
    redacao = curriculo.redigir(selecao, perfil_dict, "pt", status)

    assert redacao["bullets"] == {}
    assert any("referência desconhecida" in a for a in status.warnings)

    markdown = curriculo.montar(perfil_dict, selecao, redacao, "pt")
    assert "Liderou equipe" not in markdown
    assert selecao[0]["texto"] in markdown


def test_gerar_usa_uma_selecao_para_os_dois_idiomas(
    com_evidencias, tmp_path, provedor_redacao, monkeypatch
):
    import json

    from hermes.domain import perfil as perfil_mod
    from hermes.run_status import RunStatus

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    provedor_redacao.return_value = _resposta_json('{"resumo": "r", "bullets": {}}')

    resultados = curriculo.gerar(
        com_evidencias, vault, tmp_path / "out", RunStatus(), model="gpt-4o-mini"
    )

    assert [r["idioma"] for r in resultados] == ["pt", "en"]
    assert resultados[0]["fatos"] == resultados[1]["fatos"], "PT e EN divergiram na seleção"
    assert provedor_redacao.call_count == 2  # uma chamada por idioma, não por fato

    linhas = com_evidencias.execute(
        "SELECT idioma, caminho, fatos FROM cv_versions ORDER BY idioma"
    ).fetchall()
    assert [l["idioma"] for l in linhas] == ["en", "pt"]
    assert json.loads(linhas[0]["fatos"]) == resultados[0]["fatos"]
    assert (tmp_path / "out" / "cv-pt.md").is_file()


def test_gerar_sem_perfil_diz_o_que_criar(com_evidencias, tmp_path, provedor_redacao):
    from hermes.domain.perfil import PerfilAusente
    from hermes.run_status import RunStatus

    with pytest.raises(PerfilAusente, match="Perfil.md"):
        curriculo.gerar(com_evidencias, tmp_path, tmp_path / "out", RunStatus())


def test_gerar_sem_fato_que_sustente_recusa(banco, tmp_path, provedor_redacao):
    from hermes.domain import perfil as perfil_mod
    from hermes.run_status import RunStatus

    (tmp_path / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    with pytest.raises(curriculo.SemFatos, match="comp assess"):
        curriculo.gerar(banco, tmp_path, tmp_path / "out", RunStatus())


def test_idioma_invalido_falha_antes_de_gastar(com_evidencias, tmp_path, provedor_redacao):
    from hermes.run_status import RunStatus

    with pytest.raises(ValueError, match="idioma não suportado"):
        curriculo.gerar(
            com_evidencias, tmp_path, tmp_path / "out", RunStatus(), idiomas=("fr",)
        )
    provedor_redacao.assert_not_called()


# ------------------------------------------------ defeitos do teste real (23/09/2026)


def test_formacao_do_template_vazio_nao_vira_bullet_solto(com_evidencias, perfil_dict):
    perfil = {**perfil_dict, "formacao": [{"curso": None, "instituicao": None, "periodo": None}]}
    markdown = curriculo.montar(perfil, curriculo.selecionar(com_evidencias),
                                {"resumo": "", "bullets": {}}, "pt")
    assert "## Formação" not in markdown
    assert "\n- \n" not in markdown and not markdown.rstrip().endswith("-")


def test_projeto_aparece_pelo_nome_da_nota_nao_pelo_id(com_evidencias, perfil_dict, vault):
    entidades = curriculo._entidades(vault)
    assert entidades["mirante"]["titulo"] == "Mirante"
    assert entidades["acme"]["titulo"] == "Acme"  # experiência usa `empresa`

    markdown = curriculo.montar(perfil_dict, curriculo.selecionar(com_evidencias),
                                {"resumo": "", "bullets": {}}, "pt", entidades=entidades)
    assert "### Mirante" in markdown
    assert "### mirante" not in markdown


def test_nota_sem_nome_cai_para_o_id(tmp_path):
    from hermes.vault.reader import read_notes

    (tmp_path / "Carreira" / "Projetos").mkdir(parents=True)
    (tmp_path / "Carreira" / "Projetos" / "X.md").write_text(
        "---\ntype: project\nid: sem-nome\nnome:\n---\n\n## Fatos\n\n- fato ^f\n", encoding="utf-8")
    (nota,) = read_notes(tmp_path)
    assert nota.titulo == "sem-nome"


# --- V3: estrutura guardada e fonte de cada linha ------------------------------------


def _gerar(conn, tmp_path, provedor, resposta='{"resumo": "r", "bullets": {}}', forcar=False):
    from hermes.domain import perfil as perfil_mod
    from hermes.run_status import RunStatus

    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    provedor.return_value = _resposta_json(resposta)
    curriculo.gerar(conn, vault, tmp_path / "out", RunStatus(), model="gpt-4o-mini", forcar=forcar)
    return conn.execute("SELECT id, idioma FROM cv_versions ORDER BY id").fetchall()


def test_gerar_guarda_a_estrutura(com_evidencias, tmp_path, provedor_redacao):
    import json

    _gerar(com_evidencias, tmp_path, provedor_redacao)
    for (estrutura,) in com_evidencias.execute("SELECT estrutura FROM cv_versions"):
        dados = json.loads(estrutura)
        bullets = [b for e in dados["experiencias"] + dados["projetos"] for b in e["bullets"]]
        assert bullets and all(b["referencia"] for b in bullets)


def test_versao_traz_estrutura_e_fonte_de_cada_linha(com_evidencias, tmp_path, provedor_redacao):
    import json

    versoes = _gerar(com_evidencias, tmp_path, provedor_redacao)
    pt = next(v["id"] for v in versoes if v["idioma"] == "pt")
    d = curriculo.versao(com_evidencias, pt, tmp_path / "vault")
    gravada = json.loads(com_evidencias.execute("SELECT estrutura FROM cv_versions WHERE id = ?", (pt,)).fetchone()[0])
    assert d["estrutura"] == gravada
    ref = d["versao"]["fatos"][0]
    nota, bloco = ref.split("#")
    fato = com_evidencias.execute("SELECT texto FROM facts WHERE nota = ? AND block_id = ?", (nota, bloco)).fetchone()[0]
    fonte = d["fontes"][ref]
    assert (fonte["no_vault"], fonte["texto"], fonte["nota"], fonte["block_id"]) == (True, fato, nota, bloco)
    assert fonte["obsidian"].startswith("obsidian://open?vault=vault&file=")
    assert d["versao"]["irma_id"] == next(v["id"] for v in versoes if v["idioma"] == "en")


def test_fato_apagado_do_vault_aparece_como_fora(com_evidencias, tmp_path, provedor_redacao):
    versoes = _gerar(com_evidencias, tmp_path, provedor_redacao)
    d = curriculo.versao(com_evidencias, versoes[0]["id"], tmp_path / "vault")
    ref = d["versao"]["fatos"][0]
    nota, bloco = ref.split("#")
    with com_evidencias:
        com_evidencias.execute("DELETE FROM facts WHERE nota = ? AND block_id = ?", (nota, bloco))
    fonte = curriculo.versao(com_evidencias, versoes[0]["id"], tmp_path / "vault")["fontes"][ref]
    assert (fonte["no_vault"], fonte["texto"], fonte["obsidian"]) == (False, None, None)


def test_versao_antiga_sem_estrutura_cai_para_o_markdown(com_evidencias, tmp_path, provedor_redacao):
    versoes = _gerar(com_evidencias, tmp_path, provedor_redacao)
    with com_evidencias:
        com_evidencias.execute("UPDATE cv_versions SET estrutura = NULL")
    d = curriculo.versao(com_evidencias, versoes[0]["id"], tmp_path / "vault")
    assert d["estrutura"] is None and d["versao"]["conteudo"]


def test_versao_antiga_mantem_a_propria_estrutura(com_evidencias, tmp_path, provedor_redacao):
    """Review Focus 2: gerar de novo reescreve cv-pt.json no disco; a versão antiga não muda."""
    _gerar(com_evidencias, tmp_path, provedor_redacao, '{"resumo": "primeira", "bullets": {}}')
    primeira = com_evidencias.execute("SELECT id FROM cv_versions WHERE idioma = 'pt' ORDER BY id").fetchone()[0]
    _gerar(com_evidencias, tmp_path, provedor_redacao, '{"resumo": "segunda", "bullets": {}}', forcar=True)
    assert curriculo.versao(com_evidencias, primeira, tmp_path / "vault")["estrutura"]["resumo"] == "primeira"


def test_link_do_obsidian_codifica_o_nome_do_vault(com_evidencias, tmp_path, provedor_redacao):
    versoes = _gerar(com_evidencias, tmp_path, provedor_redacao)
    d = curriculo.versao(com_evidencias, versoes[0]["id"], tmp_path / "Meu Vault Ç")
    assert "vault=Meu%20Vault%20%C3%87&file=" in next(iter(d["fontes"].values()))["obsidian"]


def test_versao_inexistente_recusa(banco, tmp_path):
    with pytest.raises(curriculo.CurriculoRecusado, match="não existe"):
        curriculo.versao(banco, 999, tmp_path)


def test_pdf_da_versao_compila_de_verdade(com_evidencias, perfil_dict, tmp_path):
    import json
    from pathlib import Path

    pytest.importorskip("typst")
    selecao = curriculo.selecionar(com_evidencias, limite=3)
    estrutura = curriculo.estruturar(perfil_dict, selecao, {"resumo": "Resumo.", "bullets": {}}, "pt")
    with com_evidencias:
        vid = com_evidencias.execute(
            "INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo, estrutura) VALUES"
            " ('pt', ?, '[]', '2026-10-01', '# CV', ?)",
            (str(tmp_path / "cv-pt.md"), json.dumps(estrutura, ensure_ascii=False))).lastrowid
    feito = curriculo.pdf_da_versao(com_evidencias, vid, [])
    assert Path(feito["caminho"]).read_bytes()[:4] == b"%PDF" and feito["paginas"] >= 1


def test_gerar_so_em_ingles_para_a_vaga_mantem_a_versao_pt_na_candidatura(com_evidencias, tmp_path, provedor_redacao):
    from hermes.domain import perfil as perfil_mod
    from hermes.run_status import RunStatus

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    provedor_redacao.return_value = _resposta_json('{"resumo": "r", "bullets": {}}')
    job = com_evidencias.execute("INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
                                 " VALUES ('Q', 'Dev', 'colado', 'x', 'h', '2026-10-01')").lastrowid
    com_evidencias.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                           " (?, 'Python', 'obrigatorio', (SELECT id FROM competencies WHERE slug = 'python'))", (job,))
    com_evidencias.commit()
    curriculo.gerar(com_evidencias, vault, tmp_path / "out", RunStatus(), idiomas=("pt",), job_id=job, model="gpt-4o-mini")
    antes = com_evidencias.execute("SELECT cv_version_id FROM candidaturas WHERE job_id = ?", (job,)).fetchone()[0]
    curriculo.gerar(com_evidencias, vault, tmp_path / "out", RunStatus(), idiomas=("en",), job_id=job, model="gpt-4o-mini")
    depois = com_evidencias.execute("SELECT cv_version_id FROM candidaturas WHERE job_id = ?", (job,)).fetchone()[0]
    assert depois == antes
    assert com_evidencias.execute("SELECT idioma FROM cv_versions WHERE id = ?", (depois,)).fetchone()[0] == "pt"


def test_idiomas_em_ingles_primeiro_a_candidatura_aponta_o_portugues(com_evidencias, tmp_path, provedor_redacao):
    from hermes.domain import perfil as perfil_mod
    from hermes.run_status import RunStatus

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    provedor_redacao.return_value = _resposta_json('{"resumo": "r", "bullets": {}}')
    job = com_evidencias.execute("INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
                                 " VALUES ('Q', 'Dev', 'colado', 'x', 'h', '2026-10-01')").lastrowid
    com_evidencias.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                           " (?, 'Python', 'obrigatorio', (SELECT id FROM competencies WHERE slug = 'python'))", (job,))
    com_evidencias.commit()
    curriculo.gerar(com_evidencias, vault, tmp_path / "out", RunStatus(), idiomas=("en", "pt"), job_id=job,
                    model="gpt-4o-mini")
    versao = com_evidencias.execute("SELECT cv_version_id FROM candidaturas WHERE job_id = ?", (job,)).fetchone()[0]
    assert com_evidencias.execute("SELECT idioma FROM cv_versions WHERE id = ?", (versao,)).fetchone()[0] == "pt"


def test_irma_e_a_da_mesma_geracao_quando_o_id_empata(banco, tmp_path):
    """pt no meio de duas gerações em inglês com os mesmos fatos: a irmã é a gravada junto, não a de uma hora antes."""
    def inserir(idioma, criado_em):
        return banco.execute("INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo) VALUES"
                             " (?, 'x.md', '[]', ?, '#')", (idioma, criado_em)).lastrowid
    inserir("pt", "2026-10-01T10:00:00+00:00")
    en_antiga = inserir("en", "2026-10-01T10:00:02+00:00")
    pt = inserir("pt", "2026-10-01T11:00:00+00:00")
    en_junto = inserir("en", "2026-10-01T11:00:02+00:00")
    banco.commit()
    assert pt - en_antiga == en_junto - pt  # empate pelo id
    assert curriculo.versao(banco, pt, tmp_path)["versao"]["irma_id"] == en_junto
    assert curriculo.versao(banco, en_junto, tmp_path)["versao"]["irma_id"] == pt


def test_guardar_previa_aguenta_varias_threads(monkeypatch):
    import threading

    monkeypatch.setattr(curriculo, "_MAX_CACHE_PREVIA", 2)
    monkeypatch.setattr(curriculo, "_CACHE_PREVIA", {})
    erros = []

    def encher(n):
        try:
            for i in range(2000):
                curriculo._guardar_previa((n, str(i)), {})
        except Exception as exc:  # noqa: BLE001
            erros.append(exc)
    threads = [threading.Thread(target=encher, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert erros == [] and len(curriculo._CACHE_PREVIA) <= 2


def test_irma_desempata_pelo_horario_nos_dois_sentidos(banco, tmp_path):
    def inserir(idioma, criado_em):
        return banco.execute("INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo) VALUES"
                             " (?, 'x.md', '[]', ?, '#')", (idioma, criado_em)).lastrowid
    en_junto = inserir("en", "2026-10-01T11:00:00+00:00")
    pt = inserir("pt", "2026-10-01T11:00:02+00:00")
    en_outra = inserir("en", "2026-10-02T09:00:00+00:00")
    banco.commit()
    assert pt - en_junto == en_outra - pt
    assert curriculo.versao(banco, pt, tmp_path)["versao"]["irma_id"] == en_junto
