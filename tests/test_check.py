from pathlib import Path

from hermes.vault.check import (
    check_notes,
    check_orphan_evidence,
    exit_code,
    load_denylist,
)
from hermes.vault.reader import parse_note, read_notes


def _problemas(vault):
    return check_notes(read_notes(vault))


def test_vault_valido_so_avisa_nota_sem_fatos(vault):
    problemas = _problemas(vault)
    assert [p.nivel for p in problemas if p.nivel == "erro"] == []
    assert any("vazia" in p.mensagem for p in problemas)


def test_fato_sem_block_id_e_erro(vault, tmp_path):
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    nota.write_text(nota.read_text().replace(" ^pipeline", ""), encoding="utf-8")
    problemas = _problemas(vault)
    assert any(p.nivel == "erro" and "block id" in p.mensagem for p in problemas)


def test_block_id_repetido_na_mesma_nota(vault):
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    nota.write_text(nota.read_text().replace("^operacao", "^pipeline"), encoding="utf-8")
    problemas = _problemas(vault)
    assert any("repetido" in p.mensagem for p in problemas)


def test_numero_sem_fonte_vira_aviso(vault):
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    nota.write_text(
        nota.read_text().replace(
            "- Pipeline batch diário em Python que coleta feeds RSS",
            "- 108 testes automatizados com pytest",
        ),
        encoding="utf-8",
    )
    problemas = _problemas(vault)
    assert any(p.nivel == "aviso" and "número" in p.mensagem for p in problemas)


def test_numero_com_N_e_data_nao_avisa(vault):
    problemas = _problemas(vault)
    avisos_numero = [p for p in problemas if "número" in p.mensagem]
    assert avisos_numero == []


def test_frontmatter_invalido_e_erro(vault):
    nota = vault / "Carreira" / "Experiencias" / "Acme.md"
    nota.write_text(nota.read_text().replace("type: experience", "type: outro"), encoding="utf-8")
    problemas = _problemas(vault)
    assert any("`type`" in p.mensagem for p in problemas)


def test_denylist_bloqueia(vault, tmp_path):
    lista = tmp_path / "denylist.yaml"
    lista.write_text("termos:\n  - SistemaInterno\n", encoding="utf-8")
    nota = vault / "Carreira" / "Projetos" / "Mirante.md"
    nota.write_text(nota.read_text() + "\nUsa o sistemainterno da empresa.\n", encoding="utf-8")
    problemas = check_notes(read_notes(vault), load_denylist(lista))
    assert any(p.nivel == "erro" and "denylist" in p.mensagem for p in problemas)


def test_denylist_ausente_nao_quebra(tmp_path):
    assert load_denylist(tmp_path / "nao-existe.yaml") == []


def test_evidencia_orfa_e_aviso():
    problemas = check_orphan_evidence(
        [{"slug": "python", "nota": "Carreira/Projetos/X.md", "block_id": "sumiu"}]
    )
    assert problemas[0].nivel == "aviso" and "órfã" in problemas[0].mensagem


def test_exit_code():
    from hermes.vault.check import Problem

    assert exit_code([]) == 0
    assert exit_code([Problem("aviso", "n", "m")]) == 0
    assert exit_code([Problem("aviso", "n", "m")], strict=True) == 1
    assert exit_code([Problem("erro", "n", "m")]) == 1


def test_escala_e_constante_de_protocolo_nao_viram_aviso():
    from hermes.vault.check import numero_sem_fonte

    assert not numero_sem_fonte("pontua relevância de 0 a 10 e envia o relatório")
    assert not numero_sem_fonte("divisão de mensagens no limite de 4.096 caracteres")
    assert not numero_sem_fonte("deduplicação falhando em 16 de 57 dias")


def test_numero_solto_ainda_vira_aviso():
    from hermes.vault.check import numero_sem_fonte

    assert numero_sem_fonte("108 testes automatizados com pytest")
    assert numero_sem_fonte("reduziu 40% do tempo de triagem")
