"""Painel da tela Início: números, o que andou desde ontem e atividade recente."""

from datetime import datetime, timedelta, timezone

import pytest

from hermes.db import store
from hermes.domain import candidaturas as cand
from hermes.domain import painel

AGORA = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)


def _iso(horas_atras: float) -> str:
    return (AGORA - timedelta(hours=horas_atras)).isoformat(timespec="seconds")


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "hermes.db")
    yield c
    c.close()


def _vaga(conn, titulo, empresa, coletado_em, status="novo"):
    cur = conn.execute(
        "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em, status)"
        " VALUES (?, ?, 'colado', 'texto', ?, ?, ?)", (empresa, titulo, f"{empresa}-{titulo}", coletado_em, status))
    conn.commit()
    return cur.lastrowid


def _match(conn, job_id, score, criado_em):
    conn.execute("INSERT INTO job_matches (job_id, score, formula, criado_em) VALUES (?, ?, 'v1', ?)",
                 (job_id, score, criado_em))
    conn.commit()


def _email(conn, assunto, final, recebido_em, candidatura_id=None, gmail_id=None):
    eid = cand.inserir_email(conn, {"gmail_id": gmail_id or assunto, "recebido_em": recebido_em,
                                     "de": "rh@empresa.com", "assunto": assunto, "final": final})
    if candidatura_id:
        conn.execute("UPDATE emails SET candidatura_id = ? WHERE id = ?", (candidatura_id, eid))
        conn.commit()
    return eid


def test_painel_vazio_nao_quebra(conn):
    r = painel.resumo(conn, AGORA)
    assert r["numeros"] == {
        "vagas_abertas": 0, "vagas_novas_hoje": 0, "candidaturas_ativas": 0,
        "candidaturas_em_processo": 0, "emails_a_triar": 0, "estudo_minutos": 0,
        "estudo_minutos_alvo": None, "vagas_com_requisitos": 0,
    }
    assert r["desde_ontem"]["emails_triados"] == 0
    assert r["candidaturas"] == [] and r["atividade"] == []
    assert r["indice"] == {"notas": 0, "indexado_em": None}


def test_vagas_abertas_e_novas_hoje(conn):
    _vaga(conn, "Dev", "A", _iso(1))
    _vaga(conn, "Dev", "B", _iso(24 * 3), status="analisado")
    _vaga(conn, "Dev", "C", _iso(1), status="descartado")
    n = painel.resumo(conn, AGORA)["numeros"]
    assert n["vagas_abertas"] == 2
    assert n["vagas_novas_hoje"] == 1


def test_candidaturas_ativas_e_em_andamento(conn):
    job = _vaga(conn, "Front-end Pleno", "Vértice Pay", _iso(200), status="aplicado")
    _match(conn, job, 82, _iso(190))
    em_processo = cand.registrar_do_cv(conn, job, "front", None)
    _email(conn, "Convite para entrevista técnica", "avanco", _iso(2), em_processo)
    cand.recalcular(conn, em_processo)
    enviada = cand.registrar_manual(conn, "Lumina Saúde", "back", "Engenheiro de Software", "2026-09-28")
    cancelada = cand.registrar_manual(conn, "Outra", "back")
    cand.cancelar(conn, cancelada)

    r = painel.resumo(conn, AGORA)
    assert r["numeros"]["candidaturas_ativas"] == 2
    assert r["numeros"]["candidaturas_em_processo"] == 1
    ids = [c["id"] for c in r["candidaturas"]]
    assert ids == [em_processo, enviada]  # em processo primeiro
    primeira = r["candidaturas"][0]
    assert primeira["score"] == 82
    assert primeira["ultimo_email"] == {"assunto": "Convite para entrevista técnica", "categoria": "avanco"}
    assert r["candidaturas"][1]["score"] is None and r["candidaturas"][1]["ultimo_email"] is None
    assert r["desde_ontem"]["avancos"] == 1


def test_desde_ontem_conta_so_as_ultimas_24h(conn):
    _email(conn, "recente", "outro", _iso(3))
    conn.execute("UPDATE emails SET processado_em = ?", (_iso(3),))
    _email(conn, "antigo", "outro", _iso(48))
    conn.execute("UPDATE emails SET processado_em = ? WHERE assunto = 'antigo'", (_iso(48),))
    conn.commit()
    _comp(conn, "react", 3)
    _comp(conn, "cobol", 0)
    _vaga_req(conn, "Dev", "A", _iso(5), ["react"])
    _vaga_req(conn, "Dev", "B", _iso(5), ["cobol"])
    _vaga_req(conn, "Dev", "C", _iso(50), ["react"])
    d = painel.resumo(conn, AGORA)["desde_ontem"]
    assert d["emails_triados"] == 1
    assert d["vagas_boas"] == 1


def test_vagas_boas_desde_e_mudancas_usam_a_mesma_base(conn):
    """A vaga coletada há 30 h e analisada agora não é "nova desde ontem"; a coletada há 3 h, com score bom
    pela fórmula e sem análise gravada, é — no resumo e na lista de mudanças."""
    _comp(conn, "react", 3)
    antiga = _vaga_req(conn, "Antiga", "A", _iso(30), ["react"])
    _match(conn, antiga, 95, _iso(1))
    _vaga_req(conn, "Recente", "B", _iso(3), ["react"])
    _vaga_req(conn, "Recente 2", "C", _iso(2), ["react"])
    r = painel.resumo(conn, AGORA, desde=_iso(24))
    assert r["desde_ontem"]["vagas_boas"] == 2 and r["desde_visita"]["vagas_boas"] == 2
    assert [m["quantas"] for m in r["mudancas"] if m["tipo"] == "vagas_boas"] == [2]


def test_etapas_ordenam_pelo_instante_com_fusos_misturados(conn):
    # como texto, "2026-10-04T23:00-03:00" vem antes de "2026-10-05T01:00+00:00"; no relógio, é 1 h depois
    tarde = cand.registrar_manual(conn, "Tarde", "geral", enviada_em="2026-09-01")
    cedo = cand.registrar_manual(conn, "Cedo", "geral", enviada_em="2026-09-01")
    cand.ligar_manual(conn, _email(conn, "Recebemos", "inscricao_confirmada", "2026-10-04T23:00:00-03:00"), tarde)
    cand.ligar_manual(conn, _email(conn, "Obrigado", "inscricao_confirmada", "2026-10-05T01:00:00+00:00"), cedo)
    r = painel.resumo(conn, AGORA)
    assert [i["id"] for i in r["etapas"]["enviada"]["itens"]] == [tarde, cedo]


def test_emails_pendentes_ordenam_pelo_instante(conn):
    tarde = _email(conn, "Tarde", "revisar", "2026-10-04T23:00:00-03:00")
    cedo = _email(conn, "Cedo", "revisar", "2026-10-05T01:00:00+00:00")
    assert [e["id"] for e in cand.emails_pendentes(conn)] == [cedo, tarde]


def test_emails_pendentes_consultado_uma_vez(conn, monkeypatch):
    chamadas = []
    original = cand.emails_pendentes
    monkeypatch.setattr(cand, "emails_pendentes", lambda c: chamadas.append(1) or original(c))
    painel.resumo(conn, AGORA)
    assert len(chamadas) == 1


def test_emails_a_triar_sao_os_pendentes(conn):
    _email(conn, "sem dono", "avanco", _iso(1))
    _email(conn, "duvidoso", "revisar", _iso(1))
    _email(conn, "newsletter", "outro", _iso(1))
    assert painel.resumo(conn, AGORA)["numeros"]["emails_a_triar"] == 2


def test_atividade_mistura_fontes_em_ordem_e_ignora_outro(conn):
    _email(conn, "Convite", "avanco", _iso(1))
    _email(conn, "Newsletter", "outro", _iso(0.5))
    job = _vaga(conn, "Back-end", "Lumina", _iso(30))
    conn.execute(
        "INSERT INTO cv_versions (job_id, idioma, caminho, fatos, criado_em, perfil, palavras)"
        " VALUES (?, 'pt', 'out/cv.md', '[\"a.md#x\", \"b.md#y\"]', ?, 'back', 612)", (job, _iso(20)))
    conn.commit()
    _match(conn, job, 77, _iso(25))

    atividade = painel.resumo(conn, AGORA)["atividade"]
    assert [a["tipo"] for a in atividade] == ["email", "curriculo", "match"]
    cv = atividade[1]
    assert cv["titulo"] == "Currículo gerado para Lumina"
    assert cv["fatos"] == 2 and cv["palavras"] == 612


def test_atividade_respeita_o_limite(conn):
    for i in range(10):
        _email(conn, f"e{i}", "avanco", _iso(i + 1))
    assert len(painel.resumo(conn, AGORA, limite=4)["atividade"]) == 4


def test_resumo_usa_a_ultima_visita(conn):
    painel.marcar_visita(conn, _iso(48))
    _comp(conn, "react", 3)
    _vaga_req(conn, "Dev React", "Orla Tech", _iso(30), ["react"])
    r = painel.resumo(conn, agora=AGORA, desde=painel.ultima_visita(conn))
    assert r["desde_visita"]["desde"] == _iso(48)
    assert r["desde_visita"]["vagas_boas"] == 1
    assert r["desde_ontem"]["vagas_boas"] == 0


def test_sem_visita_gravada_cai_para_24h(conn):
    assert painel.ultima_visita(conn) is None
    r = painel.resumo(conn, agora=AGORA)
    assert r["desde_visita"]["desde"] == _iso(24)


def test_marcar_visita_sobrescreve(conn):
    painel.marcar_visita(conn, _iso(48))
    painel.marcar_visita(conn, _iso(2))
    assert painel.ultima_visita(conn) == _iso(2)


def test_entrevista_conta_como_ativa_e_vem_primeiro(conn):
    a = cand.registrar_manual(conn, "Orla Tech", "geral", enviada_em="2026-10-01")
    b = cand.registrar_manual(conn, "Vale Norte", "geral", enviada_em="2026-10-02")
    cand.marcar_entrevista(conn, a, "2026-10-10T14:00:00-03:00")
    r = painel.resumo(conn, AGORA)
    assert r["numeros"]["candidaturas_ativas"] == 2
    assert r["numeros"]["candidaturas_em_processo"] == 1
    assert [c["id"] for c in r["candidaturas"]] == [a, b]
    assert r["candidaturas"][0]["entrevista_em"] == "2026-10-10T14:00:00-03:00"


# --- V3: cartões de "Pede ação", mudanças desde a visita e etapas ---------------------


def _comp(conn, slug, nivel, quando="2026-09-01T00:00:00+00:00"):
    with conn:
        cid = conn.execute("INSERT OR IGNORE INTO competencies (slug, nome, categoria, criado_em) VALUES (?, ?, 'linguagem', ?)",
                           (slug, slug.title(), quando)).lastrowid or conn.execute(
            "SELECT id FROM competencies WHERE slug = ?", (slug,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO evidence (competency_id, nota, block_id, forca, criado_em) VALUES (?, 'n.md', ?, 3, ?)",
                     (cid, slug, quando))
        conn.execute("INSERT INTO competency_state (competency_id, nivel, justificativa, origem, criado_em) VALUES (?, ?, 'x', 'declarado', ?)",
                     (cid, nivel, quando))
    return cid


def _vaga_req(conn, titulo, empresa, coletado_em, slugs, status="novo"):
    job = _vaga(conn, titulo, empresa, coletado_em, status)
    with conn:
        for s in slugs:
            conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                         " (?, ?, 'obrigatorio', (SELECT id FROM competencies WHERE slug = ?))", (job, s, s))
    return job


def test_pede_acao_na_ordem_do_pm(conn):
    _comp(conn, "react", 3)
    cid = cand.registrar_manual(conn, "Orla Tech", "geral", titulo="Desenvolvedor React", enviada_em="2026-09-20")
    amanha = (AGORA + timedelta(hours=20)).isoformat(timespec="seconds")
    cand.marcar_entrevista(conn, cid, amanha)
    _vaga_req(conn, "Front-end", "Vértice Pay", _iso(3), ["react"])
    _email(conn, "Teste técnico", "pendencia", _iso(5), gmail_id="e1")
    _email(conn, "Próxima etapa", "avanco", _iso(6), gmail_id="e2")
    for e in conn.execute("SELECT id FROM emails").fetchall():
        conn.execute("UPDATE emails SET empresa_extraida = NULL WHERE id = ?", (e[0],))
    conn.commit()
    r = painel.resumo(conn, AGORA)
    assert [c["tipo"] for c in r["pede_acao"]] == ["entrevista", "vaga", "emails"]
    assert r["pede_acao"][0]["candidatura_id"] == cid and r["pede_acao"][0]["entrevista_em"] == amanha
    assert r["pede_acao"][1]["score"] >= painel.vaga.SCORE_BOM
    assert r["pede_acao"][2]["quantos"] == 2


def test_entrevista_que_ja_passou_nao_vira_cartao(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral", enviada_em="2026-09-20")
    cand.marcar_entrevista(conn, cid, (AGORA - timedelta(days=1)).isoformat(timespec="seconds"))
    r = painel.resumo(conn, AGORA)
    assert not [c for c in r["pede_acao"] if c["tipo"] == "entrevista"]
    assert [i["id"] for i in r["etapas"]["entrevista"]["itens"]] == [cid]


def test_muitas_vagas_novas_viram_um_cartao_e_um_item(conn):
    _comp(conn, "react", 3)
    for i in range(7):
        _vaga_req(conn, f"Vaga {i}", f"Empresa {i}", _iso(2 + i), ["react"])
    _vaga_req(conn, "Já aberta", "Outra", _iso(1), ["react"], status="analisado")
    _comp(conn, "cobol", 1)
    _vaga_req(conn, "Fraca", "Fraca SA", _iso(1), ["cobol"])
    r = painel.resumo(conn, AGORA, desde=_iso(48))
    vagas = [c for c in r["pede_acao"] if c["tipo"] == "vaga"]
    assert len(vagas) == 1 and vagas[0]["outras"] == 6
    boas = [m for m in r["mudancas"] if m["tipo"] == "vagas_boas"]
    assert len(boas) == 1 and boas[0]["quantas"] == 8  # as 7 novas e a já aberta passaram do corte


def test_vagas_boas_so_conta_vagas_abertas(conn):
    """Descartada, já candidatada ou com candidatura ligada não é vaga boa para olhar."""
    _comp(conn, "react", 3)
    _vaga_req(conn, "Aberta", "A", _iso(2), ["react"])
    _vaga_req(conn, "Descartada", "B", _iso(2), ["react"], status="descartado")
    _vaga_req(conn, "Aplicada", "C", _iso(2), ["react"], status="aplicado")
    com_cand = _vaga_req(conn, "Com candidatura", "D", _iso(2), ["react"])
    cand.registrar_do_cv(conn, com_cand, None, None)
    for job in conn.execute("SELECT id FROM jobs").fetchall():
        _match(conn, job[0], 90, _iso(1))
    r = painel.resumo(conn, AGORA, desde=_iso(48))
    boas = [m for m in r["mudancas"] if m["tipo"] == "vagas_boas"]
    assert boas and boas[0]["quantas"] == 1
    assert r["desde_visita"]["vagas_boas"] == 1


def test_mudancas_desde_a_visita(conn):
    import json

    cid = cand.registrar_manual(conn, "Lumina Saúde", "geral", enviada_em="2026-09-20")
    e = _email(conn, "Próxima etapa", "avanco", _iso(10), gmail_id="av")
    cand.ligar_manual(conn, e, cid)
    for idioma in ("pt", "en"):
        conn.execute("INSERT INTO cv_versions (idioma, caminho, fatos, criado_em, conteudo) VALUES (?, 'x.md', ?, ?, '#')",
                     (idioma, json.dumps(["a#1", "b#2"]), _iso(8)))
    conn.commit()
    _comp(conn, "playwright", 1, quando=_iso(100))
    _comp(conn, "playwright", 2, quando=_iso(4))
    _comp(conn, "sql", 2, quando=_iso(100))
    _comp(conn, "sql", 2, quando=_iso(3))  # reavaliação no mesmo nível não é mudança
    r = painel.resumo(conn, AGORA, desde=_iso(24))
    tipos = [(m["tipo"], m.get("empresa") or m.get("competencia")) for m in r["mudancas"]]
    assert ("avanco", "Lumina Saúde") in tipos
    assert ("nivel", "Playwright") in tipos and ("nivel", "Sql") not in tipos
    assert [m["tipo"] for m in r["mudancas"]].count("curriculo") == 1
    assert [m["quando"] for m in r["mudancas"]] == sorted([m["quando"] for m in r["mudancas"]], reverse=True)


def test_mudancas_no_maximo_cinco(conn):
    for i in range(8):
        cid = cand.registrar_manual(conn, f"Empresa {i}", "geral", enviada_em="2026-09-20")
        cand.ligar_manual(conn, _email(conn, f"Etapa {i}", "avanco", _iso(1 + i), gmail_id=f"g{i}"), cid)
    assert len(painel.resumo(conn, AGORA, desde=_iso(24))["mudancas"]) == 5


def test_etapas_sem_reprovadas_e_da_mais_recente(conn):
    a = cand.registrar_manual(conn, "Antiga", "geral", enviada_em="2026-09-01")
    b = cand.registrar_manual(conn, "Nova", "geral", enviada_em="2026-09-25")
    c = cand.registrar_manual(conn, "Cancelada", "geral", enviada_em="2026-09-26")
    cand.cancelar(conn, c)
    r = painel.resumo(conn, AGORA)
    assert [i["id"] for i in r["etapas"]["enviada"]["itens"]] == [b, a]
    assert r["etapas"]["enviada"]["total"] == 2


def test_vagas_com_requisitos(conn):
    _comp(conn, "react", 3)
    _vaga_req(conn, "Com", "A", _iso(1), ["react"])
    _vaga(conn, "Sem", "B", _iso(1))
    assert painel.resumo(conn, AGORA)["numeros"]["vagas_com_requisitos"] == 1


def test_visita_nunca_volta_no_tempo(conn):
    """Review: a visita é o horário do resumo que você viu; uma marca mais antiga não apaga uma mais nova."""
    painel.marcar_visita(conn, _iso(1))
    painel.marcar_visita(conn, _iso(5))
    assert painel.ultima_visita(conn) == _iso(1)


def _rascunho(conn, empresa, titulo, quando):
    job = _vaga(conn, titulo, empresa, quando, status="analisado")
    cid = cand.registrar_do_cv(conn, job, "front-end", None)
    conn.execute("UPDATE candidaturas SET enviada_em = ? WHERE id = ?", (quando, cid))
    conn.commit()
    return cid


def test_a_enviar_e_a_primeira_etapa_da_inicio(conn):
    cid = _rascunho(conn, "Maré Digital", "Front-end Pleno", _iso(2))
    cand.registrar_manual(conn, "Nimbo", "geral", enviada_em="2026-09-25")
    r = painel.resumo(conn, AGORA)
    assert list(r["etapas"]) == ["a_enviar", "entrevista", "em_processo", "enviada"]
    assert [i["id"] for i in r["etapas"]["a_enviar"]["itens"]] == [cid]
    assert r["numeros"]["candidaturas_ativas"] == 1  # a enviar não conta como ativa


def test_pede_acao_curriculo_pronto_entre_entrevista_e_vaga(conn):
    _comp(conn, "react", 3)
    orla = cand.registrar_manual(conn, "Orla Tech", "geral", titulo="Dev React", enviada_em="2026-09-20")
    cand.marcar_entrevista(conn, orla, (AGORA + timedelta(hours=20)).isoformat(timespec="seconds"))
    _rascunho(conn, "Antiga", "Back-end", _iso(30))
    mare = _rascunho(conn, "Maré Digital", "Front-end Pleno", _iso(2))
    _vaga_req(conn, "Front-end", "Vértice Pay", _iso(3), ["react"])
    r = painel.resumo(conn, AGORA)
    assert [c["tipo"] for c in r["pede_acao"]] == ["entrevista", "a_enviar", "vaga"]
    c = r["pede_acao"][1]
    assert (c["candidatura_id"], c["empresa"], c["outras"]) == (mare, "Maré Digital", 1)


def test_entrevista_sem_fuso_e_hora_local(em_sao_paulo):
    t = painel._quando_entrevista("2026-10-14T14:00:00")
    assert t.utcoffset() == timedelta(hours=-3) and t.hour == 14
    assert painel._quando_entrevista("2026-10-14T14:00:00+00:00").utcoffset() == timedelta(0)


@pytest.fixture
def confere_isolamento():
    import os

    antes = os.environ.get("HERMES_HOME")
    yield
    # roda depois do fim de `em_sao_paulo`: o isolamento da home tem que continuar valendo
    assert os.environ.get("HERMES_HOME") == antes


def test_fuso_fixo_nao_desfaz_o_isolamento_da_home(confere_isolamento, em_sao_paulo):
    assert painel._quando_entrevista("2026-10-14T14:00:00").hour == 14


def test_vagas_abertas_nao_conta_vaga_que_virou_candidatura(conn):
    _vaga(conn, "Livre", "A", _iso(2))
    com_cand = _vaga(conn, "Já mandei", "B", _iso(2))
    cand.registrar_do_cv(conn, com_cand, None, None)
    conn.execute("UPDATE jobs SET status = 'analisado' WHERE id = ?", (com_cand,))  # status não mudou à mão
    conn.commit()
    assert painel.resumo(conn, AGORA)["numeros"]["vagas_abertas"] == 1


def test_niveis_declarados_juntos_viram_um_item(conn):
    """A primeira declaração de níveis (uma rodada na tela) não enche "Desde a sua última visita"."""
    for slug in ("react", "sql", "git", "docker", "python", "css"):
        _comp(conn, slug, 2, quando=_iso(2))
    r = painel.resumo(conn, AGORA, desde=_iso(24))
    niveis = [m for m in r["mudancas"] if m["tipo"] in ("nivel", "niveis")]
    assert len(niveis) == 1 and niveis[0]["tipo"] == "niveis" and niveis[0]["quantos"] == 6


def test_nivel_sozinho_continua_com_o_nome(conn):
    _comp(conn, "react", 1, quando=_iso(100))
    _comp(conn, "react", 3, quando=_iso(2))
    [m] = [m for m in painel.resumo(conn, AGORA, desde=_iso(24))["mudancas"] if m["tipo"] in ("nivel", "niveis")]
    assert (m["tipo"], m["competencia"], m["nivel"]) == ("nivel", "React", 3)
