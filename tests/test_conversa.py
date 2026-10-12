"""Conversa da V3: rótulos de ferramenta, confirmações legíveis e cartões. Só leitura, sem LLM."""

import pytest

from hermes.agent.registry import TOOLS
from hermes.api import conversa


def test_toda_ferramenta_local_tem_rotulo():
    for tool in TOOLS:
        r = conversa.rotulo_ferramenta(tool.nome)
        assert r["rodando"].endswith("…") and r["feito"] and r["falhou"].startswith("Não consegui"), tool.nome
        assert tool.nome not in r["feito"], tool.nome  # português, nunca o nome cru


def test_rotulos_do_quadro():
    assert conversa.rotulo_ferramenta("list_jobs") == {
        "rodando": "Consultando as vagas…", "feito": "Consultou as vagas",
        "falhou": "Não consegui consultar as vagas",
        "verbo": "Consultou", "objeto": "as vagas"}


def test_ferramenta_mcp_usa_o_nome_cru():
    r = conversa.rotulo_ferramenta("buscar_issues")
    assert r["feito"] == "Usou `buscar_issues`" and r["falhou"] == "Não consegui usar `buscar_issues`"


def test_toda_ferramenta_que_pede_confirmacao_tem_cartao(banco):
    argumentos = {
        "link_evidence": {"slug": "python", "referencia": "Mirante.md#pipeline", "forca": 3},
        "assess_competency": {"slug": "sql", "nivel": 3, "justificativa": "DDL à mão"},
        "parse_job": {"texto": "Vaga de dev " * 30},
        "match_job": {"job_id": 1},
        "log_study": {"minutos": 30, "o_que_fez": "Playwright"},
        "git_activity": {"dias": 3},
        "confirm_study_signals": {"sinais": [1, 2], "minutos": 60, "o_que_fez": "RRF", "slug": "python"},
        "plan_week": {"minutos_disponiveis": 300},
    }
    pedem = {t.nome for t in TOOLS if t.pede_confirmacao}
    assert pedem == set(argumentos)
    for nome, args in argumentos.items():
        c = conversa.confirmacao(banco, nome, args)
        assert c["titulo"].endswith("?") and c["campos"] and c["resumo"] and c["objeto"], nome
        assert set(c["linhas"]) == {"gravado", "recusado", "expirou", "falhou"}, nome


def test_confirmacao_do_estudo_mostra_o_nome_da_competencia(banco):
    c = conversa.confirmacao(banco, "log_study", {"minutos": 30, "o_que_fez": "Testes de API", "slug": "python"})
    assert c["titulo"] == "Gravar este estudo?" and c["objeto"] == "Estudo"
    assert c["campos"] == [{"rotulo": "Tempo", "valor": "30 min"},
                           {"rotulo": "O que fez", "valor": "Testes de API"},
                           {"rotulo": "Competência", "valor": "Python"}]
    assert c["resumo"] == "30 min em Python"
    assert c["linhas"]["gravado"] == "Estudo gravado · 30 min em Python"


def test_expirou_concorda_com_a_duracao(banco):
    c = conversa.confirmacao(banco, "log_study", {"minutos": 60, "o_que_fez": "x", "slug": "graphql"})
    assert c["linhas"]["expirou"] == "Expirou · 1 h de graphql não gravada"
    c = conversa.confirmacao(banco, "log_study", {"minutos": 90, "o_que_fez": "x"})
    assert c["resumo"] == "1 h 30 min de estudo"


def test_confirmacao_do_nivel(banco):
    c = conversa.confirmacao(banco, "assess_competency", {"slug": "sql", "nivel": 3, "justificativa": "DDL"})
    assert c["resumo"] == "SQL nível 3"
    assert c["linhas"]["recusado"] == "Não gravado · SQL nível 3"
    assert {"rotulo": "Nível", "valor": "3 de 4"} in c["campos"]


def test_confirmacao_da_avaliacao_mostra_titulo_e_empresa(banco):
    jid = _vaga(banco)
    c = conversa.confirmacao(banco, "match_job", {"job_id": jid})
    assert {"rotulo": "Vaga", "valor": "Desenvolvedor React — Orla Tech"} in c["campos"]


def _vaga(conn, empresa="Orla Tech", titulo="Desenvolvedor React"):
    with conn:
        jid = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, senioridade, local, texto_bruto, hash_texto, coletado_em)"
            " VALUES (?, ?, 'colado', 'pleno', 'remoto', 'x', ?, '2026-10-01')", (empresa, titulo, empresa)).lastrowid
        for texto, slug in (("Python", "python"), ("SQL avançado", "sql"), ("Kubernetes", None)):
            conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                         " (?, ?, 'obrigatorio', (SELECT id FROM competencies WHERE slug = ?))", (jid, texto, slug))
    return jid


def _ok(**data):
    return {"ok": True, "data": data}


def test_cartao_de_vaga_um_por_vaga_no_turno(banco):
    jid = _vaga(banco)
    cartoes = conversa.cartoes(banco, [("parse_job", _ok(job_id=jid)), ("match_job", _ok(job_id=jid, score=10))])
    (c,) = cartoes
    assert c["tipo"] == "vaga" and c["job_id"] == jid
    assert (c["titulo"], c["empresa"], c["senioridade"], c["local"]) == ("Desenvolvedor React", "Orla Tech", "pleno", "remoto")
    assert (c["total"], c["cobertos"]) == (3, 0)
    assert c["lacunas"] == ["Python", "SQL avançado", "Kubernetes"]
    assert isinstance(c["score"], int)


def test_lista_de_vagas_e_falha_nao_viram_cartao(banco):
    jid = _vaga(banco)
    assert conversa.cartoes(banco, [("list_jobs", _ok(itens=[])),
                                    ("match_job", {"ok": False, "error": {"code": "x", "message": "y"}}),
                                    ("study_week", _ok())]) == []
    assert conversa.cartoes(banco, [("match_job", _ok(job_id=999))]) == []  # vaga apagada no meio
    assert len(conversa.cartoes(banco, [("match_job", _ok(job_id=jid))])) == 1


def test_cartao_de_candidatura_com_ultimo_email(banco):
    with banco:
        cid = banco.execute(
            "INSERT INTO candidaturas (empresa, titulo, origem, enviada_em, status, atualizada_em)"
            " VALUES ('Orla Tech', 'Dev React', 'manual', '2026-10-01', 'entrevista', '2026-10-02')").lastrowid
        for gid, quando, assunto in (("m1", "2026-10-02", "Recebemos"), ("m2", "2026-10-05", "Entrevista técnica")):
            banco.execute("INSERT INTO emails (gmail_id, recebido_em, de, assunto, final, candidatura_id, processado_em)"
                          " VALUES (?, ?, 'rh@orla.example', ?, 'avanco', ?, ?)", (gid, quando, assunto, cid, quando))
    jid = _vaga(banco)
    detalhe = _ok(candidatura={"id": cid}, emails=[])
    cartoes = conversa.cartoes(banco, [("match_job", _ok(job_id=jid)), ("application_detail", detalhe),
                                       ("application_detail", detalhe)])
    assert [c["tipo"] for c in cartoes] == ["vaga", "candidatura"]
    c = cartoes[1]
    assert (c["id"], c["titulo"], c["empresa"], c["status"]) == (cid, "Dev React", "Orla Tech", "entrevista")
    assert c["ultimo_email"] == {"assunto": "Entrevista técnica", "recebido_em": "2026-10-05"}
