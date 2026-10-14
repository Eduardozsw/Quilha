import pytest

from hermes.domain import competencias as c
from hermes.domain.competencias import RegraViolada

NOTA = "Carreira/Projetos/Mirante.md"


def test_seed_cria_e_e_idempotente(conn, seed_yaml):
    assert c.seed(conn, seed_yaml) == (3, 0)
    assert c.seed(conn, seed_yaml) == (0, 3)
    assert len(c.listar(conn)) == 3


def test_seed_atualiza_peso_sem_duplicar(conn, seed_yaml):
    c.seed(conn, seed_yaml)
    seed_yaml.write_text(
        seed_yaml.read_text().replace("peso: 3", "peso: 1"), encoding="utf-8"
    )
    c.seed(conn, seed_yaml)
    python = c.buscar(conn, "python")
    assert python["peso"] == 1


def test_seed_recusa_categoria_invalida(conn, tmp_path):
    ruim = tmp_path / "ruim.yaml"
    ruim.write_text(
        "competencias:\n  - slug: x\n    nome: X\n    categoria: inventada\n", encoding="utf-8"
    )
    with pytest.raises(RegraViolada, match="categoria"):
        c.seed(conn, ruim)


def test_resolver_fato_por_nota_e_por_block_id(banco):
    assert c.resolver_fato(banco, f"{NOTA}#pipeline")["block_id"] == "pipeline"
    assert c.resolver_fato(banco, "pipeline")["nota"] == NOTA
    assert c.resolver_fato(banco, "^pipeline")["nota"] == NOTA


def test_resolver_fato_inexistente(banco):
    with pytest.raises(RegraViolada, match="quilha index"):
        c.resolver_fato(banco, "nao-existe")


def test_resolver_fato_ambiguo(banco):
    banco.execute(
        "INSERT INTO facts (nota, block_id, tipo, entidade, texto, tags, indexado_em)"
        " VALUES ('Carreira/Experiencias/Acme.md', 'pipeline', 'experience', 'acme',"
        " 'outro fato', '[]', '2026-01-01T00:00:00+00:00')"
    )
    with pytest.raises(RegraViolada, match="mais de uma nota"):
        c.resolver_fato(banco, "pipeline")


def test_evidencia_detecta_metrica_sozinha(banco):
    sem = c.ligar_evidencia(banco, "python", "pipeline")
    com = c.ligar_evidencia(banco, "python", "operacao")
    assert sem["tem_metrica"] is False
    assert com["tem_metrica"] is True


def test_evidencia_e_idempotente_e_atualiza_forca(banco):
    c.ligar_evidencia(banco, "python", "pipeline", forca=1)
    c.ligar_evidencia(banco, "python", "pipeline", forca=3)
    provas = c.evidencias(banco, "python")
    assert len(provas) == 1 and provas[0]["forca"] == 3


def test_nivel_0_e_1_nao_exigem_evidencia(banco):
    assert c.avaliar(banco, "python", 1, "fiz tutorial")["nivel"] == 1


def test_nivel_2_sem_evidencia_e_recusado(banco):
    with pytest.raises(RegraViolada, match="exige ao menos 1 evidência"):
        c.avaliar(banco, "python", 2, "uso direto")


def test_nivel_2_com_evidencia_passa(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    assert c.avaliar(banco, "python", 2, "pipeline em produção")["nivel"] == 2


def test_nivel_3_exige_duas_evidencias(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    with pytest.raises(RegraViolada, match="exige 2 evidências"):
        c.avaliar(banco, "python", 3, "mantive o projeto")


def test_nivel_3_exige_uma_com_metrica(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.ligar_evidencia(banco, "python", "sql-ddl")
    with pytest.raises(RegraViolada, match="número medido"):
        c.avaliar(banco, "python", 3, "mantive o projeto")

    c.ligar_evidencia(banco, "python", "operacao")
    assert c.avaliar(banco, "python", 3, "mantive o projeto")["nivel"] == 3


def test_nivel_4_exige_metrica_com_periodo(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.ligar_evidencia(banco, "python", "testes")  # tem métrica, mas data única
    with pytest.raises(RegraViolada, match="período"):
        c.avaliar(banco, "python", 4, "rodou em operação")

    c.ligar_evidencia(banco, "python", "operacao")  # de 22/06 a 16/08/2026
    assert c.avaliar(banco, "python", 4, "rodou em operação")["nivel"] == 4


def test_justificativa_obrigatoria(banco):
    with pytest.raises(RegraViolada, match="justificativa"):
        c.avaliar(banco, "python", 0, "   ")


def test_nivel_fora_da_escala(banco):
    with pytest.raises(RegraViolada, match="nível"):
        c.avaliar(banco, "python", 7, "exagero")


def test_historico_mantem_avaliacoes_antigas(banco):
    c.avaliar(banco, "python", 1, "primeira")
    c.ligar_evidencia(banco, "python", "pipeline")
    c.avaliar(banco, "python", 2, "segunda")
    assert c.buscar(banco, "python")["nivel"] == 2
    assert banco.execute("SELECT COUNT(*) FROM competency_state").fetchone()[0] == 2


def test_situacao_e_lacunas(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.avaliar(banco, "python", 2, "uso no Mirante")
    linhas = {l["slug"]: l for l in c.listar(banco)}
    assert linhas["python"]["situacao"] == "ok"
    assert linhas["python"]["pronta_para_cv"] is True
    assert linhas["sql"]["situacao"] == "nunca avaliada"

    lacunas = [l["slug"] for l in c.listar(banco, so_lacunas=True)]
    assert "python" not in lacunas and "sql" in lacunas


def test_evidencia_perdida_deixa_situacao_visivel(banco):
    """Nível 2 gravado, depois o fato some do vault: a competência fica sem sustentação."""
    c.ligar_evidencia(banco, "python", "pipeline")
    c.avaliar(banco, "python", 2, "uso no Mirante")
    from hermes.db import store

    store.reindex_facts(banco, [])
    assert store.orphan_evidence(banco)
    provas = c.evidencias(banco, "python")
    assert provas[0]["texto"] is None  # o join com facts não encontra mais


def test_cobertura_conta_por_peso(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.avaliar(banco, "python", 2, "uso no Mirante")
    resumo = c.cobertura(banco)
    assert resumo["total"] == 3 and resumo["prontas"] == 1
    assert resumo["por_peso"][3] == {"total": 1, "prontas": 1}
    assert [l["slug"] for l in resumo["lacunas"]] == ["sql", "ingles"]


def test_remover_evidencia(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.remover_evidencia(banco, "python", "pipeline")
    assert c.evidencias(banco, "python") == []


def test_remover_evidencia_inexistente(banco):
    with pytest.raises(RegraViolada, match="não tem evidência"):
        c.remover_evidencia(banco, "python", "pipeline")


def test_remover_avisa_quando_o_nivel_vigente_perde_a_base(banco):
    """Desligar é sempre possível; o nível não muda sozinho, mas o aviso diz que ficou sem base."""
    c.ligar_evidencia(banco, "python", "pipeline")
    c.avaliar(banco, "python", 2, "escrevi o pipeline")
    r = c.remover_evidencia(banco, "python", "pipeline")
    assert r["nivel_sem_base"] == "Nível 2 fica sem evidência suficiente"
    assert c.buscar(banco, "python")["nivel"] == 2
    assert c.evidencias(banco, "python") == []


def test_remover_sem_perder_a_base_nao_avisa(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.ligar_evidencia(banco, "python", "operacao")
    c.avaliar(banco, "python", 2, "escrevi o pipeline")
    assert c.remover_evidencia(banco, "python", "pipeline")["nivel_sem_base"] is None


def test_remover_funciona_com_evidencia_orfa(banco):
    from hermes.db import store

    c.ligar_evidencia(banco, "python", "pipeline")
    store.reindex_facts(banco, [])  # o fato sumiu do vault
    assert c.remover_evidencia(banco, "python", "pipeline")["block_id"] == "pipeline"


# --- remover ------------------------------------------------------------------------


def test_remover_competencia_sem_historico_desliga_vaga_e_estudo(banco):
    banco.execute(
        "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
        " VALUES ('X', 'Dev', 'colado', 't', 'h', '2026-10-01')")
    sql_id = c.buscar(banco, "sql")["id"]
    banco.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES (1, 'SQL', 'obrigatorio', ?)",
                  (sql_id,))
    banco.commit()
    r = c.remover(banco, "sql")
    assert r == {"slug": "sql", "nome": "SQL", "requisitos_desligados": 1, "estudos_desligados": 0,
                 "evidencias_desligadas": 0, "niveis_apagados": 0}
    assert [x["slug"] for x in c.listar(banco)] == ["python", "ingles"]
    assert banco.execute("SELECT competency_id FROM job_requirements").fetchone()[0] is None


def test_remover_recusa_competencia_com_evidencia_ou_nivel(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    with pytest.raises(RegraViolada, match="1 evidência"):
        c.remover(banco, "python")
    c.avaliar(banco, "ingles", 1, "li documentação em inglês")
    with pytest.raises(RegraViolada, match="avaliação"):
        c.remover(banco, "ingles")


def test_remover_aceita_nivel_zero_declarado(banco):
    c.avaliar(banco, "ingles", 0, "nunca usei")
    assert c.remover(banco, "ingles")["slug"] == "ingles"


def test_tirar_do_seed_apaga_so_o_item_e_mantem_comentarios(seed_yaml):
    seed_yaml.write_text("# minha taxonomia\n" + seed_yaml.read_text(encoding="utf-8"), encoding="utf-8")
    assert c.tirar_do_seed(seed_yaml, "sql") is True
    texto = seed_yaml.read_text(encoding="utf-8")
    assert texto.startswith("# minha taxonomia\n")
    assert "slug: sql" not in texto and "nome: SQL" not in texto
    assert "slug: python" in texto and "slug: ingles" in texto
    assert c.tirar_do_seed(seed_yaml, "sql") is False
    assert c.tirar_do_seed(seed_yaml.parent / "nao-existe.yaml", "sql") is False


# --- recusa de nível na língua da tela ---------------------------------------------


def _prova(metrica=False, texto="fato"):
    return {"tem_metrica": metrica, "texto": texto}


def test_recusa_nivel_0_e_1_passam_sem_evidencia():
    assert c.recusa_nivel("python", 0, []) is None
    assert c.recusa_nivel("python", 1, []) is None


def test_recusa_nivel_2_sem_evidencia():
    assert c.recusa_nivel("python", 2, [], nome="Python") == {
        "titulo": "Nível 2 exige uma evidência do vault",
        "texto": "Ligue um fato que mostre você usando Python, ou fique no nível 1.",
    }


def test_recusa_nivel_3_com_uma_evidencia():
    assert c.recusa_nivel("python", 3, [_prova(True)]) == {
        "titulo": "Nível 3 exige 2 evidências",
        "texto": "Você tem 1. Ligue mais um fato, ou fique no nível 2.",
    }


def test_recusa_nivel_3_sem_metrica():
    assert c.recusa_nivel("python", 3, [_prova(), _prova()]) == {
        "titulo": "Nível 3 exige uma evidência com número medido",
        "texto": "Você tem 2 evidências, mas nenhuma traz N, data ou período."
                 " Ligue um fato com métrica, ou fique no nível 2.",
    }


def test_recusa_nivel_4_sem_periodo():
    assert c.recusa_nivel("python", 4, [_prova(True, "108 testes"), _prova()]) == {
        "titulo": "Nível 4 exige métrica e período",
        "texto": "Ligue um fato com número e período (ex.: “de 22/06 a 16/08/2026: 60 execuções”),"
                 " ou fique no nível 3.",
    }


def test_recusa_nivel_passa_quando_a_evidencia_sustenta():
    assert c.recusa_nivel("python", 4, [_prova(True, "de 22/06 a 16/08/2026: 60 execuções"), _prova()]) is None


def test_exige_evidencia_e_recusa_nivel_sao_a_mesma_regra():
    """Toda recusa da tela corresponde a uma recusa da gravação, e vice-versa."""
    casos = [[], [_prova()], [_prova(True)], [_prova(), _prova()], [_prova(True, "108 testes"), _prova()],
             [_prova(True, "de 22/06 a 16/08/2026: 60 execuções"), _prova()]]
    for provas in casos:
        for nivel in range(5):
            recusa = c.recusa_nivel("python", nivel, provas)
            try:
                c._exige_evidencia("python", nivel, provas)
                gravou = True
            except RegraViolada:
                gravou = False
            assert gravou == (recusa is None), (nivel, provas)


# --- nova competência ---------------------------------------------------------------


def test_nova_grava_no_yaml_preservando_comentarios(banco, seed_yaml):
    seed_yaml.write_text("# minha taxonomia\n" + seed_yaml.read_text(encoding="utf-8"), encoding="utf-8")
    linha = c.nova(seed_yaml, banco, "Inglês técnico", "idioma", 2)
    assert linha["slug"] == "ingles-tecnico" and linha["nome"] == "Inglês técnico" and linha["peso"] == 2
    texto = seed_yaml.read_text(encoding="utf-8")
    assert texto.startswith("# minha taxonomia\n")
    import yaml
    itens = yaml.safe_load(texto)["competencias"]
    assert [i["slug"] for i in itens] == ["python", "sql", "ingles", "ingles-tecnico"]
    assert itens[-1] == {"slug": "ingles-tecnico", "nome": "Inglês técnico", "categoria": "idioma", "peso": 2}
    assert c.buscar(banco, "ingles-tecnico")["nome"] == "Inglês técnico"


def test_nova_duplicada_pelo_nome_nao_escreve(banco, seed_yaml):
    c.nova(seed_yaml, banco, "Inglês técnico", "idioma", 2)
    antes = seed_yaml.read_text(encoding="utf-8")
    with pytest.raises(c.CompetenciaDuplicada):
        c.nova(seed_yaml, banco, "ingles Técnico", "idioma", 1)
    with pytest.raises(c.CompetenciaDuplicada):
        c.nova(seed_yaml, banco, "  PYTHON ", "linguagem", 1)
    assert seed_yaml.read_text(encoding="utf-8") == antes


def test_nova_cria_o_yaml_que_nao_existe(conn, tmp_path):
    caminho = tmp_path / "novo" / "competencias.yaml"
    c.nova(caminho, conn, "SQL", "dados", 3)
    import yaml
    assert yaml.safe_load(caminho.read_text(encoding="utf-8")) == {
        "competencias": [{"slug": "sql", "nome": "SQL", "categoria": "dados", "peso": 3}]}


@pytest.mark.parametrize("nome, categoria, peso", [("Go", "inventada", 2), ("Go", "linguagem", 4),
                                                    ("Go", "linguagem", 0), ("   ", "linguagem", 2)])
def test_nova_recusa_entrada_invalida(banco, seed_yaml, nome, categoria, peso):
    antes = seed_yaml.read_text(encoding="utf-8")
    with pytest.raises(RegraViolada):
        c.nova(seed_yaml, banco, nome, categoria, peso)
    assert seed_yaml.read_text(encoding="utf-8") == antes


def test_remover_com_historico_so_quando_pedido(banco):
    c.ligar_evidencia(banco, "python", "pipeline")
    c.avaliar(banco, "python", 2, "uso")
    with pytest.raises(RegraViolada):
        c.remover(banco, "python")
    r = c.remover(banco, "python", com_historico=True)
    assert r["evidencias_desligadas"] == 1 and r["niveis_apagados"] == 1
    assert banco.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0


def test_nova_simbolos_nao_colidem(banco, seed_yaml):
    """C, C++ e C# são competências diferentes: símbolos não somem do nome nem viram o mesmo slug."""
    slugs = [c.nova(seed_yaml, banco, nome, "linguagem", 2)["slug"] for nome in ("C#", "C++", "C", "F#")]
    assert len(set(slugs)) == 4 and "recorte" not in slugs
    assert slugs[:2] == ["csharp", "cplusplus"]
    with pytest.raises(c.CompetenciaDuplicada):
        c.nova(seed_yaml, banco, "c++", "linguagem", 1)


@pytest.mark.parametrize("conteudo", ["competencias:\n  - so-um-texto\n",
                                      "competencias:\n  - nome: X\n    categoria: dados\n"])
def test_nova_com_yaml_malformado_e_recusa_sem_escrever(banco, tmp_path, conteudo):
    caminho = tmp_path / "competencias-quebrado.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(RegraViolada, match="item #1"):
        c.nova(caminho, banco, "Go", "linguagem", 2)
    assert caminho.read_text(encoding="utf-8") == conteudo


@pytest.mark.parametrize("texto", ["competencias:\n  - slug: [x\n", "- só uma lista\n",
                                   "competencias:\n  - texto solto\n", "competencias:\n  - nome: Sem slug\n    categoria: dados\n",
                                   "competencias:\n  - slug: sem-nome\n"])
def test_seed_com_yaml_quebrado_e_recusa_que_cita_o_arquivo(banco, tmp_path, texto):
    caminho = tmp_path / "competencias.yaml"
    caminho.write_text(texto, encoding="utf-8")
    with pytest.raises(c.RegraViolada, match="competencias.yaml"):
        c.seed(banco, caminho)


def test_desligar_devolve_a_evidencia_inteira_para_o_desfazer(banco):
    c.ligar_evidencia(banco, "python", NOTA + "#pipeline", forca=3, observacao="rodou 57 vezes")
    r = c.remover_evidencia(banco, "python", NOTA + "#pipeline")
    assert (r["forca"], r["observacao"]) == (3, "rodou 57 vezes") and "tem_metrica" in r


def test_religar_evidencia_orfa_pelo_desfazer(banco):
    c.ligar_evidencia(banco, "python", NOTA + "#pipeline", forca=2, observacao="obs")
    banco.execute("DELETE FROM facts WHERE nota = ? AND block_id = 'pipeline'", (NOTA,))
    banco.commit()
    # trocar a força de uma órfã: atualiza a ligação que existe
    assert c.ligar_evidencia(banco, "python", NOTA + "#pipeline", forca=3)["forca"] == 3
    r = c.remover_evidencia(banco, "python", NOTA + "#pipeline")
    with pytest.raises(RegraViolada, match="não está no índice"):
        c.ligar_evidencia(banco, "python", NOTA + "#pipeline", forca=r["forca"])
    c.ligar_evidencia(banco, "python", NOTA + "#pipeline", forca=r["forca"], tem_metrica=r["tem_metrica"],
                      observacao=r["observacao"], restaurar=True)
    [e] = [e for e in c.evidencias(banco, "python") if e["block_id"] == "pipeline"]
    assert (e["forca"], e["observacao"]) == (3, "obs")
