"""Vaga: dedup e denylist antes de gastar, extração saneada, score determinístico (fórmula v1).

A fixture da Aurora Saúde Digital é a descrição da vaga reescrita a partir das notas do portfólio, não a
página original copiada: serve para exercitar o fluxo, não para medir a extração do modelo.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes.domain import competencias, vaga
from hermes.run_status import RunStatus

AURORA = (Path(__file__).parent / "fixtures" / "vagas" / "aurora.txt").read_text(encoding="utf-8")

EXTRACAO = {
    "empresa": "Aurora Saúde Digital",
    "titulo": "Analista de Automação (RPA)",
    "senioridade": "junior",
    "local": None,
    "requisitos": [
        {"texto": "Python, JavaScript ou C# básico", "tipo": "obrigatorio",
         "competencia_sugerida": "python", "confianca": 0.9},
        {"texto": "SQL e bancos relacionais básicos", "tipo": "obrigatorio",
         "competencia_sugerida": "sql", "confianca": 1.4},
        {"texto": "Familiaridade com APIs", "tipo": "desejavel",
         "competencia_sugerida": "integracao-apis", "confianca": 0.8},
        {"texto": "Inglês", "tipo": "diferencial", "competencia_sugerida": "ingles", "confianca": 0.9},
    ],
}


def _resposta(conteudo):
    texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=texto, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=800, completion_tokens=200),
    )


@pytest.fixture
def provedor(mocker):
    import litellm

    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["response_format"])
    return mocker.patch.object(litellm, "completion", return_value=_resposta(EXTRACAO))


@pytest.fixture
def vaga_gravada(banco, provedor):
    return vaga.parse_job(banco, texto=AURORA, status=RunStatus())


# ---------------------------------------------------------------- texto bruto


def test_hash_ignora_caixa_e_espaco():
    assert vaga.hash_texto("Python  básico\n\nSQL") == vaga.hash_texto("python básico sql ")
    assert vaga.hash_texto("Python") != vaga.hash_texto("SQL")


def test_texto_de_html_descarta_script_e_estilo():
    html = """<html><head><title>x</title><style>.a{}</style></head><body>
      <h1>Analista</h1><script>var segredo = 1;</script>
      <ul><li>Python</li><li>SQL</li></ul><p>Remoto&nbsp;total</p></body></html>"""
    texto = vaga.texto_de_html(html)
    assert texto.splitlines() == ["Analista", "- Python", "- SQL", "Remoto total"]
    assert "segredo" not in texto


# ------------------------------------------------------------------- parse_job


def test_parse_grava_vaga_e_requisitos_saneados(vaga_gravada, banco):
    assert vaga_gravada["duplicada"] is False
    assert (vaga_gravada["empresa"], vaga_gravada["titulo"]) == (
        "Aurora Saúde Digital", "Analista de Automação (RPA)")

    por_texto = {r["texto"]: r for r in vaga_gravada["requisitos"]}
    assert por_texto["Python, JavaScript ou C# básico"]["competencia"] == "python"
    assert por_texto["SQL e bancos relacionais básicos"]["confianca"] == 1.0  # 1.4 limitado a 1
    # slug que não existe na taxonomia não é criado: fica sem competência e vira aviso
    assert por_texto["Familiaridade com APIs"]["competencia"] is None
    # confiança é do mapeamento: sem competência, o 0.8 do modelo não significa nada
    assert por_texto["Familiaridade com APIs"]["confianca"] is None
    assert vaga_gravada["sugeridos_fora"] == ["integracao-apis"]
    # tipo fora do contrato vira obrigatório, nunca some
    assert por_texto["Inglês"]["tipo"] == "obrigatorio"

    linha = banco.execute("SELECT fonte, status, url FROM jobs").fetchone()
    assert (linha["fonte"], linha["status"], linha["url"]) == ("colado", "novo", None)


def test_parse_avisa_requisito_sem_competencia(banco, provedor):
    status = RunStatus()
    vaga.parse_job(banco, texto=AURORA, status=status)
    assert any("1 requisito(s) sem competência" in a for a in status.warnings)
    assert any("tipo `diferencial` inválido" in a for a in status.warnings)


def test_vaga_repetida_nao_chama_o_modelo_de_novo(vaga_gravada, banco, provedor):
    reformatado = "  " + AURORA.upper().replace("\n", "\n\n")
    segunda = vaga.parse_job(banco, texto=reformatado, status=RunStatus())

    assert segunda["duplicada"] is True
    assert segunda["job_id"] == vaga_gravada["job_id"]
    assert provedor.call_count == 1
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_denylist_bloqueia_antes_de_sair_da_maquina(banco, provedor):
    with pytest.raises(vaga.TextoBloqueado, match="aurora"):
        vaga.parse_job(banco, texto=AURORA, denylist=("aurora",))
    provedor.assert_not_called()
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_texto_curto_recusado_sem_gastar(banco, provedor):
    with pytest.raises(vaga.VagaRecusada, match="descrição inteira"):
        vaga.parse_job(banco, texto="Vaga de Python")
    provedor.assert_not_called()


def test_texto_e_url_juntos_recusados(banco, provedor):
    with pytest.raises(vaga.VagaRecusada, match="um dos dois"):
        vaga.parse_job(banco, texto=AURORA, url="https://exemplo.com/vaga")


def test_url_com_pouco_texto_pede_para_colar(banco, provedor, mocker):
    mocker.patch.object(vaga, "baixar", return_value="<div id='app'></div><script>x()</script>")
    with pytest.raises(vaga.PaginaSemTexto, match="cole o texto"):
        vaga.parse_job(banco, url="https://exemplo.com/vaga")
    provedor.assert_not_called()


def test_url_grava_fonte_e_deduplica_pela_url(banco, provedor, mocker):
    html = "<p>" + AURORA.replace("\n", "</p><p>") + "</p>"
    mocker.patch.object(vaga, "baixar", return_value=html)
    primeira = vaga.parse_job(banco, url="https://exemplo.com/vaga")
    segunda = vaga.parse_job(banco, url="https://exemplo.com/vaga")

    assert segunda["duplicada"] and segunda["job_id"] == primeira["job_id"]
    assert banco.execute("SELECT fonte FROM jobs").fetchone()[0] == "url"
    assert provedor.call_count == 1


def test_prompt_pede_todos_os_itens_no_idioma_original(banco, provedor):
    vaga.parse_job(banco, texto=AURORA)
    prompt = provedor.call_args.kwargs["messages"][1]["content"]
    assert "sem pular nenhum" in prompt
    assert "Não traduza" in prompt


# ------------------------------------------------------------------- reextrair


NOVA_EXTRACAO = {
    "empresa": "Aurora Saúde Digital",
    "titulo": "Analista de Automação (RPA)",
    "requisitos": [
        {"texto": "SQL básico", "tipo": "obrigatorio", "competencia_sugerida": "sql", "confianca": 0.9},
        {"texto": "Background in healthtech", "tipo": "desejavel", "competencia_sugerida": None,
         "confianca": 0.7},
    ],
}


def test_reextrair_substitui_os_requisitos(vaga_gravada, banco, provedor):
    provedor.return_value = _resposta(NOVA_EXTRACAO)
    status = RunStatus()
    r = vaga.extrair_requisitos(banco, vaga_gravada["job_id"], status=status)

    assert r["reextraida"] is True
    assert r["job_id"] == vaga_gravada["job_id"]
    assert [q["texto"] for q in r["requisitos"]] == ["SQL básico", "Background in healthtech"]
    assert provedor.call_count == 2
    assert status.llm_calls == 1
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_reextrair_usa_o_texto_guardado(vaga_gravada, banco, provedor):
    provedor.return_value = _resposta(NOVA_EXTRACAO)
    vaga.extrair_requisitos(banco, vaga_gravada["job_id"])
    prompt = provedor.call_args.kwargs["messages"][1]["content"]
    assert AURORA.strip() in prompt


def test_reextrair_avisa_que_desfaz_job_map_e_pede_novo_match(vaga_gravada, banco, provedor):
    apis = next(q for q in vaga_gravada["requisitos"] if q["texto"] == "Familiaridade com APIs")
    vaga.mapear(banco, apis["id"], "python")
    vaga.match_job(banco, vaga_gravada["job_id"], redigir=False)
    assert banco.execute("SELECT status FROM jobs").fetchone()[0] == "analisado"

    provedor.return_value = _resposta(NOVA_EXTRACAO)
    status = RunStatus()
    vaga.extrair_requisitos(banco, vaga_gravada["job_id"], status=status)

    assert any("1 mapeamento(s) feitos com `job map`" in a for a in status.warnings)
    assert banco.execute("SELECT status FROM jobs").fetchone()[0] == "novo"


def test_reextrair_vazio_mantem_os_requisitos_anteriores(vaga_gravada, banco, provedor):
    provedor.return_value = _resposta({"empresa": "X", "titulo": "Y", "requisitos": []})
    with pytest.raises(vaga.VagaRecusada, match="anteriores foram mantidos"):
        vaga.extrair_requisitos(banco, vaga_gravada["job_id"])
    assert len(vaga.requisitos(banco, vaga_gravada["job_id"])) == len(vaga_gravada["requisitos"])


def test_reextrair_nao_troca_empresa_e_titulo(vaga_gravada, banco, provedor):
    """Empresa e título vêm do coletor ou de você; o modelo só preenche o que estava vazio."""
    provedor.return_value = _resposta({**NOVA_EXTRACAO, "titulo": "Outro título", "local": "remoto"})
    r = vaga.extrair_requisitos(banco, vaga_gravada["job_id"])
    assert r["titulo"] == "Analista de Automação (RPA)"
    assert banco.execute("SELECT local FROM jobs").fetchone()[0] == "remoto"


def test_extrair_respeita_a_denylist_atual(vaga_gravada, banco, provedor):
    provedor.reset_mock()
    with pytest.raises(vaga.TextoBloqueado):
        vaga.extrair_requisitos(banco, vaga_gravada["job_id"], denylist=("aurora",))
    provedor.assert_not_called()


def test_extrair_vaga_inexistente_recusa_sem_gastar(banco, provedor):
    with pytest.raises(vaga.VagaRecusada, match="não existe"):
        vaga.extrair_requisitos(banco, 999)
    provedor.assert_not_called()


# ---------------------------------------------------------------------- baixar


def _http(status_code, texto="<p>ok</p>"):
    import httpx

    return httpx.Response(status_code, text=texto, request=httpx.Request("GET", "https://x"))


def test_baixar_refaz_em_5xx(mocker):
    import httpx

    mocker.patch("time.sleep")  # o backoff do tenacity não precisa esperar no teste
    get = mocker.patch.object(httpx, "get", side_effect=[_http(503), _http(200, "<p>vaga</p>")])
    assert vaga.baixar("https://x") == "<p>vaga</p>"
    assert get.call_count == 2


def test_baixar_nao_refaz_em_404(mocker):
    import httpx

    get = mocker.patch.object(httpx, "get", return_value=_http(404))
    with pytest.raises(vaga.FalhaDeRede, match="404"):
        vaga.baixar("https://x")
    assert get.call_count == 1


def test_baixar_desiste_depois_das_tentativas(mocker):
    import httpx

    mocker.patch("time.sleep")
    get = mocker.patch.object(httpx, "get", side_effect=httpx.ConnectTimeout("lento"))
    with pytest.raises(vaga.FalhaDeRede, match="3 tentativas"):
        vaga.baixar("https://x")
    assert get.call_count == vaga.TENTATIVAS_URL


# ----------------------------------------------------------------------- score


def _item(tipo, competencia, nivel):
    cobertura = vaga.COBERTURA_NIVEL[nivel or 0] if competencia else 0.0
    return {"requisito_id": 0, "texto": "x", "tipo": tipo, "competencia": competencia,
            "nivel": nivel, "evidencias": [], "cobertura": cobertura}


def test_formula_v1_bate_com_a_especificacao():
    itens = [
        _item("obrigatorio", "python", 2),   # 2 × 0.60 = 1.2
        _item("obrigatorio", None, None),    # 2 × 0    = 0   (não mapeado)
        _item("desejavel", "ingles", 4),     # 1 × 1.00 = 1.0
    ]
    placar = vaga.calcular_score(itens)
    assert placar["score"] == 44  # round(100 × 2.2 / 5)
    assert placar["formula"] == "v1"
    assert (placar["n_requisitos"], placar["mapeados"]) == (3, 2)
    assert (placar["obrigatorios"], placar["obrigatorios_descobertos"]) == (2, 1)


def test_score_sem_requisito_e_zero_e_nao_divide_por_zero():
    assert vaga.calcular_score([])["score"] == 0


def test_nivel_1_cobre_um_pouco_mas_continua_lacuna():
    itens = [_item("obrigatorio", "sql", 1)]
    assert vaga.calcular_score(itens)["score"] == 25
    assert vaga.lacunas(itens)[0]["motivo"] == "nível 1"


# ----------------------------------------------------------------------- match


@pytest.fixture
def python_nivel_2(banco):
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    return banco


def test_match_sem_texto_nao_chama_o_modelo(python_nivel_2, vaga_gravada, provedor):
    provedor.reset_mock()
    r = vaga.match_job(python_nivel_2, vaga_gravada["job_id"], redigir=False)

    provedor.assert_not_called()
    # python 2×0.60 · sql 2×0 (nunca avaliada) · APIs 1×0 (não mapeado) · inglês 2×0
    assert r["score"] == round(100 * 1.2 / 7)
    assert r["obrigatorios_descobertos"] == 2
    motivos = {l["texto"]: l["motivo"] for l in r["lacunas"]}
    assert motivos["Familiaridade com APIs"] == "não mapeado"
    assert motivos["SQL e bancos relacionais básicos"] == "nível nunca avaliado"

    python = next(i for i in r["cobertura"] if i["competencia"] == "python")
    assert python["evidencias"] == ["Carreira/Projetos/Mirante.md#pipeline"]

    linha = python_nivel_2.execute("SELECT score, formula, model, cost_usd FROM job_matches").fetchone()
    assert (linha["score"], linha["formula"], linha["model"], linha["cost_usd"]) == (r["score"], "v1", None, None)
    status_vaga = python_nivel_2.execute("SELECT status FROM jobs").fetchone()[0]
    assert status_vaga == "analisado"


def test_match_com_texto_so_aceita_comentario_de_lacuna(python_nivel_2, vaga_gravada, provedor):
    ids = {r["texto"]: r["id"] for r in vaga_gravada["requisitos"]}
    provedor.return_value = _resposta({
        "lacunas": {
            str(ids["SQL e bancos relacionais básicos"]): "Ligue o fato ^sql-ddl e declare nível.",
            str(ids["Python, JavaScript ou C# básico"]): "isto não é lacuna",
        },
        "riscos": ["Explique por que o pipeline não usa ORM."],
    })
    status = RunStatus()
    status.record_usage(10, 10, 0.5)  # custo de antes, de outra chamada do mesmo turno
    r = vaga.match_job(python_nivel_2, vaga_gravada["job_id"], status=status, model="gpt-4o-mini")

    comentarios = {l["texto"]: l.get("comentario") for l in r["lacunas"]}
    assert comentarios["SQL e bancos relacionais básicos"].startswith("Ligue o fato")
    assert any("não é lacuna" in a for a in status.warnings)
    assert r["riscos"] == ["Explique por que o pipeline não usa ORM."]
    # o score não passou pelo modelo: é o mesmo do cálculo sem texto
    assert r["score"] == round(100 * 1.2 / 7)

    linha = python_nivel_2.execute("SELECT model, cost_usd FROM job_matches").fetchone()
    assert linha["model"] == "gpt-4o-mini"
    assert linha["cost_usd"] == pytest.approx(0.001)  # só esta chamada, não o turno inteiro


def test_mapear_requisito_muda_o_score(python_nivel_2, vaga_gravada):
    competencias.ligar_evidencia(python_nivel_2, "sql", "sql-ddl", forca=3)
    competencias.avaliar(python_nivel_2, "sql", 2, "DDL à mão")
    apis = next(r for r in vaga_gravada["requisitos"] if r["texto"] == "Familiaridade com APIs")

    antes = vaga.match_job(python_nivel_2, vaga_gravada["job_id"], redigir=False)["score"]
    vaga.mapear(python_nivel_2, apis["id"], "sql")  # mapeamento torto, só para mover o número
    depois = vaga.match_job(python_nivel_2, vaga_gravada["job_id"], redigir=False)

    assert depois["score"] > antes
    assert depois["mapeados"] == 4
    mapeado = next(r for r in vaga.requisitos(python_nivel_2, vaga_gravada["job_id"]) if r["id"] == apis["id"])
    assert mapeado["confianca"] is None  # decisão sua, não palpite do modelo


def test_mapear_competencia_inexistente_recusa(vaga_gravada, banco):
    requisito = vaga_gravada["requisitos"][0]["id"]
    with pytest.raises(vaga.VagaRecusada, match="não existe"):
        vaga.mapear(banco, requisito, "cobol")


def test_match_de_vaga_inexistente_recusa(banco):
    with pytest.raises(vaga.VagaRecusada, match="não existe"):
        vaga.match_job(banco, 999, redigir=False)


# ----------------------------------------------------------- currículo sob medida


def test_curriculo_sob_medida_so_usa_competencias_da_vaga(python_nivel_2, vaga_gravada):
    from hermes.domain import curriculo

    # sql em nível 2, mas a vaga não pede sql depois de desmapeado: não entra
    competencias.ligar_evidencia(python_nivel_2, "sql", "sql-ddl", forca=3)
    competencias.avaliar(python_nivel_2, "sql", 2, "DDL à mão")
    sql = next(r for r in vaga_gravada["requisitos"] if r["competencia"] == "sql")
    vaga.mapear(python_nivel_2, sql["id"], None)

    base = {f["block_id"] for f in curriculo.selecionar(python_nivel_2)}
    sob_medida = curriculo.selecionar(python_nivel_2, job_id=vaga_gravada["job_id"])

    assert base == {"pipeline", "sql-ddl"}
    assert [f["block_id"] for f in sob_medida] == ["pipeline"]
    assert sob_medida[0]["forca"] == 2 * 3  # peso do requisito obrigatório × força da evidência


# ------------------------------------------------- bloqueios e fatos candidatos


def test_match_aponta_fato_candidato_e_bloqueio_para_o_modelo(vaga_gravada, banco, provedor):
    """sql nunca avaliada com ^sql-ddl no vault: a lacuna é de registro. Obrigatório sem
    competência é bloqueio possível, e os dois chegam ao modelo."""
    provedor.return_value = _resposta({"lacunas": {}, "riscos": ["r1", "r2"]})
    apis = next(r for r in vaga_gravada["requisitos"] if r["texto"] == "Familiaridade com APIs")
    vaga.mapear(banco, apis["id"], None)
    with banco:
        banco.execute("UPDATE job_requirements SET tipo = 'obrigatorio' WHERE id = ?", (apis["id"],))

    r = vaga.match_job(banco, vaga_gravada["job_id"], model="gpt-4o-mini")

    sql = next(f for f in r["lacunas"] if f["competencia"] == "sql")
    assert [c["block_id"] for c in sql["candidatos"]] == ["sql-ddl"]
    prompt = provedor.call_args.kwargs["messages"][1]["content"]
    assert "fatos candidatos: ^sql-ddl" in prompt
    bloqueios = prompt.split("Possíveis bloqueios")[1]
    assert "Familiaridade com APIs" in bloqueios


def test_sem_fato_candidato_a_lacuna_fica_sem_sugestao(vaga_gravada, banco):
    r = vaga.match_job(banco, vaga_gravada["job_id"], redigir=False)
    ingles = next(f for f in r["lacunas"] if f["competencia"] == "ingles")
    assert "candidatos" not in ingles


def test_nunca_declarada_com_evidencia_ligada_pede_so_o_nivel(vaga_gravada, banco):
    competencias.ligar_evidencia(banco, "sql", "sql-ddl", forca=3)
    r = vaga.match_job(banco, vaga_gravada["job_id"], redigir=False)
    sql = next(f for f in r["lacunas"] if f["competencia"] == "sql")
    assert sql["motivo"] == "nível nunca declarado (1 evidência(s) já ligada(s))"
    assert sql["ligadas"] == ["sql-ddl"]
    assert "candidatos" not in sql


def test_comentario_que_cita_block_id_de_outra_lacuna_e_descartado(vaga_gravada, banco, provedor):
    """Caso real de 22/09/2026: o modelo copiou "^llm-layer já sustenta" para a lacuna de idioma."""
    competencias.ligar_evidencia(banco, "sql", "sql-ddl", forca=3)
    ids = {r["competencia"]: r["id"] for r in vaga_gravada["requisitos"]}
    provedor.return_value = _resposta({
        "lacunas": {str(ids["sql"]): "declarar o nível; ^sql-ddl já sustenta",
                    str(ids["ingles"]): "declarar o nível; ^sql-ddl já sustenta"},
        "riscos": ["r"],
    })
    status = RunStatus()
    r = vaga.match_job(banco, vaga_gravada["job_id"], status=status)

    comentarios = {f["competencia"]: f.get("comentario") for f in r["lacunas"]}
    assert comentarios["sql"] == "declarar o nível; ^sql-ddl já sustenta"
    assert comentarios["ingles"] is None
    assert any("não sustenta essa lacuna" in a for a in status.warnings)


def test_id_do_requisito_com_circunflexo_nao_conta_como_block_id(vaga_gravada, banco, provedor):
    """Caso real de 23/09/2026: o modelo escreveu "^12" para o requisito 12 e o guarda descartou."""
    ids = {r["competencia"]: r["id"] for r in vaga_gravada["requisitos"]}
    rid = ids["ingles"]
    provedor.return_value = _resposta({
        "lacunas": {str(rid): f"^{rid}: gravar um áudio em inglês e registrar no vault"},
        "riscos": ["r"],
    })
    status = RunStatus()
    r = vaga.match_job(banco, vaga_gravada["job_id"], status=status)

    ingles = next(f for f in r["lacunas"] if f["competencia"] == "ingles")
    assert ingles["comentario"].startswith(f"^{rid}:")
    assert not any("descartado" in a for a in status.warnings)


def test_curriculo_para_vaga_registra_a_candidatura(python_nivel_2, vaga_gravada, vault, tmp_path, monkeypatch):
    """Gerar para a vaga conta como envio; gerar de novo não duplica (Review Focus 5)."""
    from hermes.domain import curriculo
    from hermes.domain import perfil as perfil_mod

    (vault / perfil_mod.ARQUIVO).write_text(perfil_mod.TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(curriculo, "redigir", lambda *a, **k: {"resumo": "r", "bullets": {}})
    job = vaga_gravada["job_id"]

    curriculo.gerar(python_nivel_2, vault, tmp_path / "out", RunStatus(), job_id=job)
    curriculo.gerar(python_nivel_2, vault, tmp_path / "out", RunStatus(), job_id=job, forcar=True)

    linhas = python_nivel_2.execute("SELECT job_id, perfil, origem, cv_version_id FROM candidaturas").fetchall()
    assert len(linhas) == 1
    assert (linhas[0]["job_id"], linhas[0]["perfil"], linhas[0]["origem"]) == (job, "geral", "cv")
    assert linhas[0]["cv_version_id"] is not None


# --- avaliação ao vivo (tela Vagas da V3) --------------------------------------------


def _vaga_com_requisitos(conn, reqs, titulo="Desenvolvedor React"):
    """reqs: [(texto, tipo, slug|None)]"""
    from hermes.db import store
    with conn:
        job = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em, local, senioridade)"
            " VALUES ('Orla Tech', ?, 'colado', 'Time de produto de pagamentos.', ?, ?, 'remoto', 'pleno')",
            (titulo, f"h-{titulo}-{len(reqs)}", store.utcnow())).lastrowid
        for texto, tipo, slug in reqs:
            conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                         " (?, ?, ?, (SELECT id FROM competencies WHERE slug = ?))", (job, texto, tipo, slug))
    return job


def test_avaliacao_diz_a_fonte_ou_o_motivo(banco):
    from hermes.db import store
    with banco:
        banco.execute("INSERT INTO competencies (slug, nome, categoria, criado_em) VALUES"
                      " ('docker', 'Docker', 'automacao', ?)", (store.utcnow(),))
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")   # coberto
    competencias.avaliar(banco, "sql", 1, "tutorial")                   # nível baixo
    competencias.ligar_evidencia(banco, "ingles", "pipeline", forca=1)  # fato sem nível
    job = _vaga_com_requisitos(banco, [
        ("Python", "obrigatorio", "python"), ("SQL", "obrigatorio", "sql"),
        ("Inglês", "desejavel", "ingles"), ("Kafka", "desejavel", None), ("Docker", "desejavel", "docker"),
    ])
    a = vaga.avaliacao(banco, job)
    fontes = {r["texto"]: (r["coberto"], r["fonte"]) for r in a["requisitos"]}
    assert fontes["Python"][0] is True and fontes["Python"][1] and ".md" not in fontes["Python"][1]
    assert fontes["SQL"] == (False, "seu nível: 1 de 4")
    assert fontes["Inglês"] == (False, "falta declarar o nível")
    assert fontes["Kafka"] == (False, "sem competência ligada")
    assert fontes["Docker"] == (False, "sem evidência no vault")
    assert (a["cobertos"], a["total"]) == (1, 5)
    assert a["score"] == vaga.calcular_score(vaga.cobertura(banco, job))["score"]


def test_avaliacao_de_vaga_sem_requisitos_nao_quebra(banco):
    job = _vaga_com_requisitos(banco, [])
    # sem requisitos não há nota: `None`, como na lista (0 pareceria "nada coberto")
    assert vaga.avaliacao(banco, job) == {"score": None, "cobertos": 0, "total": 0, "requisitos": []}


def test_mais_de_duas_notas_vira_contagem():
    item = {"competencia": "react", "nivel": 3, "evidencias": ["a/painel.md#x", "b/agenda.md#y", "c/loja.md#z"]}
    assert vaga._fonte_ou_motivo(item) == "3 notas"
    item["evidencias"] = ["Carreira/Projetos/painel-vendas.md#x", "Carreira/Projetos/painel-vendas.md#y"]
    assert vaga._fonte_ou_motivo(item) == "painel-vendas"


def test_listar_traz_score_ao_vivo_e_nova_sem_n_mais_1(banco):
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    for i in range(30):
        _vaga_com_requisitos(banco, [(f"Req {i}", "obrigatorio", "python")], titulo=f"Vaga {i}")
    _vaga_com_requisitos(banco, [], titulo="Sem requisitos")
    consultas = []
    banco.set_trace_callback(consultas.append)
    vagas = vaga.listar(banco)
    banco.set_trace_callback(None)
    assert len(vagas) == 31 and all(v["nova"] for v in vagas)
    por_titulo = {v["titulo"]: v for v in vagas}
    assert por_titulo["Vaga 0"]["score"] > 0 and por_titulo["Sem requisitos"]["score"] is None
    assert {"senioridade", "local", "url"} <= set(por_titulo["Vaga 0"])
    assert len([c for c in consultas if c.lstrip().upper().startswith("SELECT")]) <= 2


def test_abrir_so_tira_o_selo_de_nova(banco):
    job = _vaga_com_requisitos(banco, [("Python", "obrigatorio", "python")])
    assert vaga.marcar_vista(banco, job) == "analisado"
    banco.execute("UPDATE jobs SET status = 'aplicado' WHERE id = ?", (job,))
    banco.commit()
    assert vaga.marcar_vista(banco, job) == "aplicado"  # candidatada não volta para analisado
    with pytest.raises(vaga.VagaRecusada, match="não existe"):
        vaga.marcar_vista(banco, 9999)


def test_descartar_e_desfazer_volta_ao_status_anterior(banco):
    job = _vaga_com_requisitos(banco, [("Python", "obrigatorio", "python")])
    r = vaga.definir_status(banco, job, "descartado")
    assert r == {"job_id": job, "status": "descartado", "anterior": "novo"}
    assert vaga.definir_status(banco, job, r["anterior"])["status"] == "novo"
    with pytest.raises(vaga.VagaRecusada, match="status"):
        vaga.definir_status(banco, job, "arquivada")
    with pytest.raises(vaga.VagaRecusada, match="não existe"):
        vaga.definir_status(banco, 9999, "descartado")


def test_listar_por_status_so_calcula_a_cobertura_das_vagas_desse_status(banco):
    competencias.ligar_evidencia(banco, "python", "pipeline", forca=3)
    competencias.avaliar(banco, "python", 2, "pipeline em produção")
    aberta = _vaga_com_requisitos(banco, [("Python", "obrigatorio", "python")], titulo="Aberta")
    descartada = _vaga_com_requisitos(banco, [("Python", "obrigatorio", "python")], titulo="Descartada")
    vaga.definir_status(banco, descartada, "descartado")
    linhas = []
    banco.set_trace_callback(linhas.append)
    so = vaga.listar(banco, "novo")
    banco.set_trace_callback(None)
    assert [v["id"] for v in so] == [aberta] and so[0]["score"] > 0
    cobertura = [c for c in linhas if "job_requirements r" in c and "json_group_array" in c]
    assert cobertura and all("status" in c for c in cobertura)  # filtrada pelo status, não todas as vagas


def test_coberto_pelo_nivel_sem_notas_diz_o_nivel():
    item = {"competencia": "react", "nivel": 3, "evidencias": []}
    assert vaga._fonte_ou_motivo(item) == "nível declarado: 3 de 4"
