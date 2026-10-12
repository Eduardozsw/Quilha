from hermes.vault.reader import parse_note, read_notes, split_frontmatter


def test_le_so_carreira_e_ignora_templates(vault):
    notas = read_notes(vault)
    assert sorted(n.nota for n in notas) == [
        "Carreira/Experiencias/Acme.md",
        "Carreira/Projetos/Mirante.md",
    ]


def test_frontmatter_e_fatos(vault):
    nota = parse_note(vault / "Carreira" / "Projetos" / "Mirante.md", vault)
    assert nota.tipo == "project"
    assert nota.entidade == "mirante"
    assert nota.tem_secao_fatos
    assert [f.block_id for f in nota.facts] == ["pipeline", "operacao", "sql-ddl", "testes"]


def test_tags_e_texto_sem_block_id(vault):
    nota = parse_note(vault / "Carreira" / "Projetos" / "Mirante.md", vault)
    fato = nota.facts[0]
    assert fato.tags == ["python", "automacao"]
    assert fato.texto == "Pipeline batch diário em Python que coleta feeds RSS"
    assert "^pipeline" not in fato.texto


def test_continuacao_indentada_vira_um_fato_so(vault):
    nota = parse_note(vault / "Carreira" / "Projetos" / "Mirante.md", vault)
    fato = nota.facts[2]
    assert fato.texto == "Modelagem SQLite com DDL escrito à mão, com constraints CHECK"


def test_secao_apos_fatos_nao_entra(vault):
    nota = parse_note(vault / "Carreira" / "Projetos" / "Mirante.md", vault)
    assert all(f.block_id != "nao-indexado" for f in nota.facts)


def test_linha_do_fato_aponta_para_o_arquivo(vault):
    nota = parse_note(vault / "Carreira" / "Projetos" / "Mirante.md", vault)
    linhas = (vault / "Carreira" / "Projetos" / "Mirante.md").read_text().splitlines()
    assert "^pipeline" in linhas[nota.facts[0].linha - 1]


def test_nota_sem_fatos(vault):
    nota = parse_note(vault / "Carreira" / "Experiencias" / "Acme.md", vault)
    assert nota.tem_secao_fatos
    assert nota.facts == []


def test_frontmatter_ausente_ou_quebrado():
    dados, _, erro = split_frontmatter("# Sem frontmatter\n")
    assert dados == {} and erro == "nota sem frontmatter"

    dados, _, erro = split_frontmatter("---\ntype: project\n")
    assert "fechamento" in erro

    dados, _, erro = split_frontmatter("---\ntype: [inválido\n---\n")
    assert "inválido" in erro


def test_read_notes_avisa_o_progresso(vault):
    from hermes.vault.reader import read_notes

    passos = []
    notas = read_notes(vault, progresso=lambda feitas, total: passos.append((feitas, total)))
    assert passos == [(i, len(notas)) for i in range(1, len(notas) + 1)]


def test_indexacao_cancelada_nao_toca_no_indice(banco, vault):
    import pytest

    from hermes.run_status import RunStatus
    from hermes.vault import indice
    from hermes.vault.reader import IndexacaoCancelada

    antes = banco.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    lidas = []
    with pytest.raises(IndexacaoCancelada):
        indice.reindexar(banco, vault, [], RunStatus(), progresso=lambda f, t: lidas.append(f),
                         cancelado=lambda: len(lidas) >= 1)
    assert banco.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == antes > 0


def test_vault_sem_carreira_nao_zera_o_indice(banco, tmp_path):
    import pytest

    from hermes.run_status import RunStatus
    from hermes.vault import indice

    antes = banco.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert antes > 0
    outra = tmp_path / "outra-pasta"
    outra.mkdir()
    with pytest.raises(indice.VaultSemCarreira, match="Carreira/"):
        indice.reindexar(banco, outra, [], RunStatus())
    assert banco.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == antes


def test_primeira_indexacao_de_vault_sem_carreira_passa_com_zero(conn, tmp_path):
    """Quem começa do zero escolhe o vault real, ainda sem Carreira/: entra com 0 notas, não fica preso."""
    from hermes.run_status import RunStatus
    from hermes.vault import indice

    vault = tmp_path / "vault-novo"
    vault.mkdir()
    assert indice.reindexar(conn, vault, [], RunStatus())["fatos"] == 0


def test_mensagem_diz_para_criar_a_pasta(banco, tmp_path):
    import pytest

    from hermes.run_status import RunStatus
    from hermes.vault import indice

    outra = tmp_path / "sem-carreira"
    outra.mkdir()
    with pytest.raises(indice.VaultSemCarreira, match="crie a pasta Carreira/"):
        indice.reindexar(banco, outra, [], RunStatus())
