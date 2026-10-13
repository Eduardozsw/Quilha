"""Candidaturas: nota por perfil, empresa do e-mail, ligação e status."""

from datetime import date

import pytest

from hermes.domain import candidaturas as cand


@pytest.mark.parametrize("maturados, avancos, esperado", [
    (10, 3, 5),     # 30%
    (10, 2, 5),     # 20%, limite inclusivo
    (10, 1, 4),     # 10%
    (15, 1, 3),     # 6,7%
    (40, 1, 2),     # 2,5%
    (60, 1, 1),     # 1,7%
    (5, 1, None),   # poucos envios: 20% de 5 não diz nada
    (99, 0, None),  # zerado, mas ainda sem veredito
    (100, 0, 0),    # zerado com 100: péssimo
    (0, 0, None),
])
def test_nota(maturados, avancos, esperado):
    assert cand.nota(maturados, avancos) == esperado


def test_maturada_por_tempo_ou_por_resposta():
    hoje = date(2026, 9, 29)
    assert not cand.maturada("2026-09-09T10:00:00+00:00", None, hoje)  # 20 dias
    assert cand.maturada("2026-09-08T10:00:00+00:00", None, hoje)      # 21 dias
    assert cand.maturada("2026-09-26T10:00:00+00:00", "2026-09-28T09:00:00+00:00", hoje)


@pytest.mark.parametrize("texto, esperado", [
    ("AUREO S.A.", "aureo"),
    ("Áureo", "aureo"),
    ("Nexo Brasil", "nexo"),
    ("MoBi Global", "mobi"),
    ("[PATALUZ]", "pataluz"),
    ("Pico Capital Ltda.", "pico capital"),
    ("", ""),
    (None, ""),
])
def test_normalizar_empresa(texto, esperado):
    assert cand.normalizar_empresa(texto) == esperado


# no formato de remetentes e assuntos reais do jev (resultados.csv de 28/09/2026), com empresas fictícias
@pytest.mark.parametrize("de, assunto, esperado", [
    ("Robotiza <no-reply@gupy.com.br>", "[Robotiza] Confirmação de Candidatura", "robotiza"),
    ("Pataluz <noreply@job.recrut.ai>", "[PATALUZ] Fulano, sua inscrição foi confirmada com sucesso", "pataluz"),
    ('"AUREO S.A." <no-reply@gupy.com.br>',
     "Programa de Estágio Corporativo Áureo | Queremos te conhecer melhor", "aureo"),
    ("Nexo Brasil <no-reply@gupy.com.br>",
     "Candidatura para a vaga Desenvolvedor Fullstack Jr não finalizada", "nexo"),
    ("quartzo@ses-mail.inhire.app", "Recebemos sua candidatura na Quartzo ✨", "quartzo"),
    ("norteweb@ses-mail.inhire.app", "Processo Seletivo NorteWeb | Recebemos sua inscrição!", "norteweb"),
    ("noreply@mail.orbital.jobs", "Processo de candidatura na Orbital: atualização sobre o status", "orbital"),
    ("noreply@mail.orbital.jobs", "Acompanhe sua candidatura", "orbital"),
    ("LinkedIn <jobs-noreply@linkedin.com>", "Fulano, sua candidatura foi enviada à Pico Capital", "pico capital"),
    ("mobirecruiting_noreply@mobi-labs.com", "Thank you for applying at MoBi Global", "mobi"),
    ("Send-Only.sec@myworkday.com", "Thank you for applying to Kairos", "kairos"),
    ("no-reply@imarket.com.br", "iMarket | Programa de Estágio iFuturo 27 | Feedback", "imarket"),
    ('"Lume | Time de People" <no-reply@ashbyhq.com>', "Lume | Recebemos sua candidatura", "lume"),
    ("no-reply@kova.com", "[ENCERRAMENTO] KOVA Summer Internship 2027", "kova"),
    ("Atlas Solutions Dev <no-reply@sesametime.com>", "ETAPA TESTE PRÁTICO | PROCESSO SELETIVO", "atlas solutions dev"),
    ("no-reply@us.greenhouse-mail.io", "Recebemos sua candidatura para AI Engineer I! 🚀", None),
    ("Send-Only.sec@otp.workday.com", "Confirmar conta de candidato", None),
])
def test_empresa_do_email(de, assunto, esperado):
    achada = cand.empresa_do_email(de, assunto)
    assert (cand.normalizar_empresa(achada) or None) == esperado


def _vaga(conn, empresa="Quartzo", titulo="Desenvolvedor Python"):
    cur = conn.execute(
        "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
        " VALUES (?, ?, 'colado', 'x', ?, '2026-09-01')", (empresa, titulo, f"h-{empresa}-{titulo}"))
    return cur.lastrowid


def _email(conn, final, empresa, recebido="2026-09-10T12:00:00+00:00", assunto="assunto", gid=None):
    return cand.inserir_email(conn, {
        "gmail_id": gid or f"g{final}{recebido}{assunto}", "recebido_em": recebido, "de": "x@y.com",
        "assunto": assunto, "categoria_jev": final, "prob_categoria": 0.9, "prob_processo": 0.9,
        "prob_prazo": 0.1, "final": final, "empresa_extraida": empresa, "latencia_ms": 300,
    })


def _cand(conn, cid):
    return dict(conn.execute("SELECT * FROM candidaturas WHERE id = ?", (cid,)).fetchone())


def test_registrar_do_cv_cria_a_enviar_e_e_idempotente(conn):
    job = _vaga(conn)
    cid = cand.registrar_do_cv(conn, job, "engenharia-ia", None)
    assert cand.registrar_do_cv(conn, job, "engenharia-ia", None) == cid  # pdf depois do draft
    c = _cand(conn, cid)
    assert (c["empresa_norm"], c["perfil"], c["origem"], c["status"]) == ("quartzo", "engenharia-ia", "cv", "a_enviar")
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job,)).fetchone()[0] != "aplicado"  # decisão 8
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 1


def test_cv_sem_perfil_vira_geral_e_cancelada_continua_cancelada(conn):
    job = _vaga(conn)
    cid = cand.registrar_do_cv(conn, job, None, None)
    assert _cand(conn, cid)["perfil"] == "geral"
    cand.cancelar(conn, cid)
    cand.registrar_do_cv(conn, job, None, None)
    assert _cand(conn, cid)["status"] == "cancelada"


def test_email_liga_na_candidatura_do_cv_e_avanco_conta(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    e = _email(conn, "avanco", "Quartzo")
    assert cand.ligar(conn, e) == cid
    c = _cand(conn, cid)
    assert (c["status"], c["teve_avanco"], c["respondida_em"]) == ("em_processo", 1, "2026-09-10T12:00:00+00:00")


def test_reprovacao_depois_do_avanco_fica_reprovada_mas_teve_avanco(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    cand.ligar(conn, _email(conn, "avanco", "Quartzo", "2026-09-10T00:00:00+00:00"))
    cand.ligar(conn, _email(conn, "reprovado", "Quartzo", "2026-09-20T00:00:00+00:00"))
    c = _cand(conn, cid)
    assert (c["status"], c["teve_avanco"]) == ("reprovada", 1)


def test_email_sem_candidatura_cria_pingada(conn):
    cid = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Orbital"))
    c = _cand(conn, cid)
    assert (c["perfil"], c["origem"], c["empresa_norm"]) == (None, "email", "orbital")
    assert c["enviada_em"] == "2026-09-10T12:00:00+00:00"


def test_outro_revisar_e_sem_empresa_nao_ligam(conn):
    assert cand.ligar(conn, _email(conn, "outro", "Orbital")) is None
    assert cand.ligar(conn, _email(conn, "revisar", "Orbital")) is None
    assert cand.ligar(conn, _email(conn, "reprovado", None)) is None
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 0
    assert len(cand.emails_pendentes(conn)) == 2  # revisar e o sem empresa; `outro` não é pendência


def test_duas_vagas_na_empresa_desempata_pelo_titulo_ou_fica_pendente(conn):
    dados = cand.registrar_do_cv(conn, _vaga(conn, "Quartzo", "Engenheiro de Dados"), "engenharia-ia", None)
    cand.registrar_do_cv(conn, _vaga(conn, "Quartzo", "Desenvolvedor Frontend"), "engenharia-ia", None)
    assert cand.ligar(conn, _email(conn, "avanco", "Quartzo", assunto="Teste para Engenheiro de Dados")) == dados
    ambiguo = _email(conn, "avanco", "Quartzo", assunto="Próxima etapa")
    assert cand.ligar(conn, ambiguo) is None
    assert [e["id"] for e in cand.emails_pendentes(conn)] == [ambiguo]


def test_inscricao_depois_de_reprovacao_abre_candidatura_nova(conn):
    """Review Focus 1: a Orbital manda e-mail de vários processos."""
    velha = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Orbital", "2026-08-01T00:00:00+00:00"))
    cand.ligar(conn, _email(conn, "reprovado", "Orbital", "2026-08-15T00:00:00+00:00"))
    nova = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Orbital", "2026-09-10T00:00:00+00:00"))
    assert nova != velha
    assert _cand(conn, velha)["status"] == "reprovada"
    assert _cand(conn, nova)["status"] == "enviada"


def test_corrigir_para_outro_desliga_e_recalcula(conn):
    """Review Focus 4."""
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    e = _email(conn, "avanco", "Quartzo")
    cand.ligar(conn, e)
    cand.corrigir(conn, e, "outro")
    c = _cand(conn, cid)
    assert (c["status"], c["teve_avanco"], c["respondida_em"]) == ("enviada", 0, None)
    assert conn.execute("SELECT candidatura_id FROM emails WHERE id = ?", (e,)).fetchone()[0] is None


def test_corrigir_avanco_para_pendencia_zera_o_avanco(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    e = _email(conn, "avanco", "Quartzo")
    cand.ligar(conn, e)
    assert cand.corrigir(conn, e, "pendencia") == cid
    assert _cand(conn, cid)["teve_avanco"] == 0


def test_corrigir_categoria_invalida_recusa(conn):
    e = _email(conn, "revisar", "Quartzo")
    with pytest.raises(cand.CandidaturaRecusada, match="categoria"):
        cand.corrigir(conn, e, "revisar")


def test_ligar_manual_e_definir_perfil(conn):
    e = _email(conn, "reprovado", None)
    cid = cand.registrar_manual(conn, "Kairos", cand.GERAL, enviada_em="2026-09-01")
    cand.ligar_manual(conn, e, cid)
    assert _cand(conn, cid)["status"] == "reprovada"
    with pytest.raises(cand.CandidaturaRecusada, match="não existe"):
        cand.definir_perfil(conn, 999, "geral")


def test_notas_por_perfil_so_conta_maturadas_e_ignora_pingadas_e_canceladas(conn):
    hoje = date(2026, 9, 29)
    for i in range(10):
        cid = cand.registrar_manual(conn, f"Empresa {i}", "engenharia-ia", enviada_em="2026-08-01")
        if i < 3:
            cand.ligar_manual(conn, _email(conn, "avanco", None, gid=f"a{i}"), cid)
    cand.registrar_manual(conn, "Recente", "engenharia-ia", enviada_em="2026-09-25")  # não maturou
    cand.cancelar(conn, cand.registrar_manual(conn, "Nunca enviei", "engenharia-ia", enviada_em="2026-08-01"))
    cand.ligar(conn, _email(conn, "inscricao_confirmada", "Pingada SA"))

    r = cand.notas_por_perfil(conn, hoje)
    [ia] = r["perfis"]
    assert (ia["perfil"], ia["enviados"], ia["maturados"], ia["avancos"], ia["nota"]) == (
        "engenharia-ia", 11, 10, 3, 5)
    assert r["pingadas"] == 1


def test_nota_sem_dados_diz_o_que_falta(conn):
    cand.registrar_manual(conn, "A", "visao", enviada_em="2026-08-01")
    [v] = cand.notas_por_perfil(conn, date(2026, 9, 29))["perfis"]
    assert v["nota"] is None
    assert "9" in v["falta"]  # faltam 9 envios maturados


# revisão final: palavras genéricas, TLD, provedor pessoal e ATS fora da lista não viram empresa (C1)
@pytest.mark.parametrize("de, assunto, esperado", [
    ("Granito <no-reply@granito.com.br>", "Você avançou no Processo Seletivo", "granito"),
    ("recruiting@yz.com.br", "Atualização no Processo Seletivo", "yz"),
    ("jobs@listra.com", "Invitation to Interview", "listra"),
    ("no-reply@roxobank.com.br", "Your application to Software Engineer at Roxobank", "roxobank"),
    ("no-reply@hackhub.ai", "You're in! Welcome to the ZEN Lab Program", "hackhub"),
    ("careers@orbital.co.uk", "Your application", "orbital"),
    ("Veloz Human Data <human-data@veloz.com>", "Onboarding Session Link | 3D Dev - Assets | Veloz", "veloz"),
    ("Recrutador <fulano@outlook.com>", "Olá Fulano | atualização", None),
    ('"Equipe de Recrutamento" <no-reply@gupy.com.br>', "Queremos te conhecer melhor", None),
    ("no-reply@smartrecruiters.com", "Convite para entrevista na Próxima Etapa", None),
    ("x@teamtailor.com", "[Processo Seletivo] Atualização", None),
    ("Roxobank <no-reply@gupy.com.br>", "Feedback | Programa de Estágio", "roxobank"),
])
def test_empresa_do_email_nao_inventa_empresa(de, assunto, esperado):
    achada = cand.empresa_do_email(de, assunto)
    assert (cand.normalizar_empresa(achada) or None) == esperado


def test_processo_novo_depois_de_reprovacao_recebe_os_emails_seguintes(conn):
    """I1: depois de abrir a candidatura nova, o avanço dela não pode ficar pendente."""
    velha = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Orbital", "2026-08-01T00:00:00+00:00"))
    cand.ligar(conn, _email(conn, "reprovado", "Orbital", "2026-08-15T00:00:00+00:00"))
    nova = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Orbital", "2026-09-10T00:00:00+00:00"))
    assert cand.ligar(conn, _email(conn, "avanco", "Orbital", "2026-09-12T00:00:00+00:00")) == nova
    assert _cand(conn, velha)["teve_avanco"] == 0


def test_processo_novo_que_comeca_com_avanco_nao_reabre_a_reprovada(conn):
    """I2: na Orbital o primeiro e-mail do processo novo costuma ser 'Ação exigida: avaliação'."""
    velha = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Orbital", "2026-08-01T00:00:00+00:00"))
    cand.ligar(conn, _email(conn, "avanco", "Orbital", "2026-08-05T00:00:00+00:00"))
    cand.ligar(conn, _email(conn, "reprovado", "Orbital", "2026-08-15T00:00:00+00:00"))
    nova = cand.ligar(conn, _email(conn, "pendencia", "Orbital", "2026-09-12T00:00:00+00:00"))
    assert nova != velha
    assert _cand(conn, velha)["status"] == "reprovada"


def test_ligar_que_falha_nao_deixa_pingada_vazia(conn, monkeypatch):
    """I3: pingada, ligação e status entram juntos ou não entram."""
    e = _email(conn, "inscricao_confirmada", "Orbital")
    monkeypatch.setattr(cand, "recalcular", lambda *a: (_ for _ in ()).throw(RuntimeError("locked")))
    with pytest.raises(RuntimeError):
        cand.ligar(conn, e)
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 0
    assert conn.execute("SELECT candidatura_id FROM emails WHERE id = ?", (e,)).fetchone()[0] is None


def test_registrar_manual_recusa_data_invalida(conn):
    """I5: data fora de AAAA-MM-DD quebraria `app notas` depois."""
    with pytest.raises(cand.CandidaturaRecusada, match="data"):
        cand.registrar_manual(conn, "Quartzo", "geral", enviada_em="28/09/2026")


def test_empresa_depois_de_pela():
    """Sync real de 29/09: 'Sua candidatura foi vista pela Pico Capital' (LinkedIn) ficou sem empresa."""
    achada = cand.empresa_do_email("LinkedIn <jobs-noreply@linkedin.com>",
                                   "Sua candidatura foi vista pela Pico Capital")
    assert cand.normalizar_empresa(achada) == "pico capital"


# --- detalhe e título (tela de candidaturas) ---------------------------------------


def test_detalhe_traz_os_emails_em_ordem_com_o_corpo(conn):
    cid = cand.registrar_manual(conn, "Áureo", "geral")
    for gid, quando, final, corpo in (("g2", "2026-09-25T10:00:00+00:00", "avanco", "Queremos te conhecer melhor"),
                                      ("g1", "2026-09-23T10:00:00+00:00", "inscricao_confirmada", None)):
        eid = cand.inserir_email(conn, {"gmail_id": gid, "recebido_em": quando, "de": "rh@aureo.com.br",
                                        "assunto": gid, "corpo": corpo, "final": final})
        cand.ligar_manual(conn, eid, cid)
    d = cand.detalhe(conn, cid)
    assert d["candidatura"]["empresa"] == "Áureo" and d["candidatura"]["status"] == "em_processo"
    assert [(e["assunto"], e["corpo"], e["categoria"]) for e in d["emails"]] == [
        ("g1", None, "inscricao_confirmada"), ("g2", "Queremos te conhecer melhor", "avanco")]
    assert d["vaga"] is None and d["cv"] is None


def test_detalhe_de_candidatura_que_nao_existe_e_recusa(conn):
    with pytest.raises(cand.CandidaturaRecusada, match="não existe"):
        cand.detalhe(conn, 99)


def test_definir_titulo_e_limpar(conn):
    cid = cand.registrar_manual(conn, "Áureo", "geral")
    cand.definir_titulo(conn, cid, "  Programa de Estágio Corporativo  ")
    assert cand.detalhe(conn, cid)["candidatura"]["titulo"] == "Programa de Estágio Corporativo"
    cand.definir_titulo(conn, cid, "   ")
    assert cand.detalhe(conn, cid)["candidatura"]["titulo"] is None


# --- triagem na tela de e-mails ---------------------------------------------------


def _mail(conn, gid, final, empresa=None, corpo="texto"):
    return cand.inserir_email(conn, {"gmail_id": gid, "recebido_em": f"2026-09-2{len(gid)}T10:00:00+00:00",
                                     "de": "rh@x.com", "assunto": gid, "corpo": corpo, "final": final,
                                     "empresa_extraida": empresa})


def test_listar_emails_por_visao(conn):
    pendente = _mail(conn, "g1", "revisar")
    outro = _mail(conn, "g22", "outro")
    ligado = _mail(conn, "g333", "avanco", "Áureo")
    cand.ligar(conn, ligado)
    assert [e["id"] for e in cand.listar_emails(conn, "pendentes")] == [pendente]
    assert [e["id"] for e in cand.listar_emails(conn, "outros")] == [outro]
    processo = cand.listar_emails(conn, "processo")
    assert [e["id"] for e in processo] == [ligado] and processo[0]["cand_empresa"] == "Áureo"
    assert "corpo" not in processo[0] and cand.email(conn, ligado)["corpo"] == "texto"
    assert cand.contar_emails(conn) == {"pendentes": 1, "processo": 1, "outros": 1}
    with pytest.raises(cand.CandidaturaRecusada):
        cand.listar_emails(conn, "lixo")


def test_definir_empresa_cria_a_pingada_ou_liga_na_existente(conn):
    sem_empresa = _mail(conn, "g1", "inscricao_confirmada")
    cid = cand.definir_empresa(conn, sem_empresa, "  Greenhouse Co ")
    c = cand.detalhe(conn, cid)
    assert c["candidatura"]["empresa"] == "Greenhouse Co" and [e["id"] for e in c["emails"]] == [sem_empresa]

    outro_da_mesma = _mail(conn, "g22", "avanco")
    assert cand.definir_empresa(conn, outro_da_mesma, "greenhouse co") == cid
    assert cand.listar_emails(conn, "pendentes") == []


def test_definir_empresa_recusa_email_que_nao_e_de_processo(conn):
    duvidoso = _mail(conn, "g1", "revisar")
    with pytest.raises(cand.CandidaturaRecusada, match="corrija a categoria"):
        cand.definir_empresa(conn, duvidoso, "Áureo")


def test_desligar_volta_o_email_para_pendente_e_recalcula(conn):
    cid = cand.registrar_manual(conn, "Robotiza", "geral")
    eid = _mail(conn, "g1", "avanco")
    cand.ligar_manual(conn, eid, cid)
    assert cand.detalhe(conn, cid)["candidatura"]["status"] == "em_processo"
    cand.desligar(conn, eid)
    assert cand.detalhe(conn, cid)["candidatura"]["status"] == "enviada"
    assert [e["id"] for e in cand.listar_emails(conn, "pendentes")] == [eid]
    cand.desligar(conn, eid)  # de novo não quebra
    with pytest.raises(cand.CandidaturaRecusada):
        cand.desligar(conn, 999)


# --- etapa entrevista -------------------------------------------------------------


def _versao_cv(conn, idioma="pt"):
    return conn.execute("INSERT INTO cv_versions (idioma, caminho, fatos, criado_em) VALUES (?, 'x.md', '[]', '2026-10-01')",
                        (idioma,)).lastrowid


def test_gerar_so_em_ingles_nao_troca_a_versao_da_candidatura(conn):
    job = _vaga(conn)
    pt, en, pt2 = _versao_cv(conn), _versao_cv(conn, "en"), _versao_cv(conn)
    cid = cand.registrar_do_cv(conn, job, None, pt)
    cand.registrar_do_cv(conn, job, None, en, trocar_versao=False)
    assert _cand(conn, cid)["cv_version_id"] == pt
    cand.registrar_do_cv(conn, job, None, pt2)
    assert _cand(conn, cid)["cv_version_id"] == pt2


def test_candidatura_nova_so_em_ingles_nasce_com_a_versao_en(conn):
    en = _versao_cv(conn, "en")
    cid = cand.registrar_do_cv(conn, _vaga(conn), None, en, trocar_versao=False)
    assert _cand(conn, cid)["cv_version_id"] == en


def test_marcar_entrevista_e_desmarcar(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    cand.ligar(conn, _email(conn, "avanco", "Quartzo"))
    d = cand.marcar_entrevista(conn, cid, "2026-10-10T14:00:00-03:00")
    assert (d["candidatura"]["status"], d["candidatura"]["entrevista_em"]) == ("entrevista", "2026-10-10T14:00:00-03:00")
    d = cand.marcar_entrevista(conn, cid, None)
    assert (d["candidatura"]["status"], d["candidatura"]["entrevista_em"]) == ("em_processo", None)


def test_entrevista_sobrevive_a_email_novo_e_reprovacao_vence(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    cand.marcar_entrevista(conn, cid, "2026-10-10T14:00:00-03:00")
    c = _cand(conn, cid)
    assert (c["status"], c["teve_avanco"]) == ("entrevista", 1)  # entrevista marcada é avanço
    cand.ligar(conn, _email(conn, "avanco", "Quartzo", "2026-10-05T00:00:00+00:00"))
    assert _cand(conn, cid)["status"] == "entrevista"  # e-mail de avanço não rebaixa
    cand.ligar(conn, _email(conn, "reprovado", "Quartzo", "2026-10-12T00:00:00+00:00"))
    assert _cand(conn, cid)["status"] == "reprovada"


def test_marcar_entrevista_recusa_data_invalida_e_candidatura_inexistente(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    with pytest.raises(cand.CandidaturaRecusada, match="ISO"):
        cand.marcar_entrevista(conn, cid, "amanhã")
    with pytest.raises(cand.CandidaturaRecusada, match="não existe"):
        cand.marcar_entrevista(conn, 999, "2026-10-10T14:00:00-03:00")
    assert _cand(conn, cid)["status"] == "a_enviar"


def test_email_com_data_de_entrevista_ligado_a_mao_marca_a_etapa(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    e = cand.inserir_email(conn, {"gmail_id": "x1", "recebido_em": "2026-10-05T12:00:00+00:00", "de": "rh@orla.example",
                                  "assunto": "Entrevista", "final": "avanco", "entrevista_em": "2026-10-10T14:00:00-03:00"})
    cand.ligar_manual(conn, e, cid)
    c = _cand(conn, cid)
    assert (c["status"], c["entrevista_em"]) == ("entrevista", "2026-10-10T14:00:00-03:00")


def _email_entrevista(conn, gid, recebido, quando):
    return cand.inserir_email(conn, {"gmail_id": gid, "recebido_em": recebido, "de": "rh@orla.example",
                                     "assunto": "Entrevista", "final": "avanco", "entrevista_em": quando})


def test_email_mais_antigo_ligado_depois_nao_desfaz_a_remarcacao(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    novo = _email_entrevista(conn, "n", "2026-10-06T12:00:00+00:00", "2026-10-12T10:00:00-03:00")
    velho = _email_entrevista(conn, "v", "2026-10-02T12:00:00+00:00", "2026-10-09T10:00:00-03:00")
    cand.ligar_manual(conn, novo, cid)
    cand.ligar_manual(conn, velho, cid)
    assert _cand(conn, cid)["entrevista_em"] == "2026-10-12T10:00:00-03:00"


def test_data_marcada_a_mao_vence_o_email(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    cand.marcar_entrevista(conn, cid, "2026-10-12T15:00:00-03:00")
    e = _email_entrevista(conn, "lembrete", "2026-10-11T12:00:00+00:00", "2026-10-12T18:00:00+00:00")
    cand.ligar_manual(conn, e, cid)
    assert _cand(conn, cid)["entrevista_em"] == "2026-10-12T15:00:00-03:00"


def test_desligar_o_email_tira_a_data_que_veio_dele(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    a = _email_entrevista(conn, "a", "2026-10-02T12:00:00+00:00", "2026-10-09T10:00:00-03:00")
    b = _email_entrevista(conn, "b", "2026-10-06T12:00:00+00:00", "2026-10-12T10:00:00-03:00")
    cand.ligar_manual(conn, a, cid)
    cand.ligar_manual(conn, b, cid)
    cand.desligar(conn, b)
    assert _cand(conn, cid)["entrevista_em"] == "2026-10-09T10:00:00-03:00"  # volta para a do e-mail que restou
    cand.corrigir(conn, a, "outro")
    c = _cand(conn, cid)
    assert (c["entrevista_em"], c["status"]) == (None, "enviada")  # sem e-mail de avanço ligado


# --- etapa "A enviar" (migração 009) ------------------------------------------------

candidaturas = cand


@pytest.fixture
def vaga_id(conn):
    return _vaga(conn, empresa="Maré Digital", titulo="Desenvolvedora Front-end Pleno")


@pytest.fixture
def email_de():
    def inserir(conn, *, empresa_da_vaga=True, categoria="avanco", recebido_em="2026-10-01T10:00:00+00:00"):
        return _email(conn, categoria, "Maré Digital" if empresa_da_vaga else None, recebido=recebido_em)
    return inserir


def test_gerar_curriculo_cria_a_enviar_e_nao_marca_a_vaga(conn, vaga_id):
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    c = candidaturas.detalhe(conn, cid)["candidatura"]
    assert c["status"] == "a_enviar"
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (vaga_id,)).fetchone()[0] != "aplicado"


def test_marquei_como_enviada_grava_data_e_marca_a_vaga(conn, vaga_id):
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    d = candidaturas.marcar_enviada(conn, cid, "2026-10-09")
    assert d["candidatura"]["status"] == "enviada" and d["candidatura"]["enviada_em"].startswith("2026-10-09")
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (vaga_id,)).fetchone()[0] == "aplicado"
    with pytest.raises(candidaturas.CandidaturaRecusada):
        candidaturas.marcar_enviada(conn, cid)


def test_gerar_de_novo_nao_volta_para_a_enviar(conn, vaga_id):
    """Review Focus 5."""
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    candidaturas.marcar_enviada(conn, cid, "2026-10-09")
    candidaturas.registrar_do_cv(conn, vaga_id, "back-end", None)
    c = candidaturas.detalhe(conn, cid)["candidatura"]
    assert (c["status"], c["perfil"], c["enviada_em"][:10]) == ("enviada", "back-end", "2026-10-09")


def test_email_de_processo_tira_de_a_enviar(conn, vaga_id, email_de):
    """Review Focus 1: mandou e esqueceu de marcar."""
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    eid = email_de(conn, empresa_da_vaga=True, categoria="inscricao_confirmada", recebido_em="2026-10-01T10:00:00+00:00")
    assert candidaturas.ligar(conn, eid) == cid
    c = candidaturas.detalhe(conn, cid)["candidatura"]
    assert c["status"] == "enviada" and c["enviada_em"].startswith("2026-10-01")


def test_a_enviar_nao_conta_na_nota_por_perfil(conn, vaga_id):
    candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    assert candidaturas.notas_por_perfil(conn, date(2026, 10, 10))["perfis"] == []


def test_marcar_enviada_sem_data_usa_hoje(conn, vaga_id):
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    d = candidaturas.marcar_enviada(conn, cid)
    assert d["candidatura"]["enviada_em"][:10] == date.today().isoformat()


# --- parecidas, juntar e nova candidatura pelo e-mail ------------------------------

def _pingada(conn, empresa="Grupo Tavares", n_emails=1, entrevista=None):
    """Pingada com e-mails ligados (o primeiro com a data de entrevista, se houver)."""
    ids = []
    for i in range(n_emails):
        e = cand.inserir_email(conn, {
            "gmail_id": f"p-{empresa}-{i}", "recebido_em": f"2026-10-0{i + 1}T10:00:00+00:00", "de": "rh@x.example",
            "assunto": "Inscrição", "final": "avanco" if i == 0 else "inscricao_confirmada",
            "empresa_extraida": empresa, "entrevista_em": entrevista if i == 0 else None})
        ids.append(e)
    with conn:
        pid = cand._inserir(conn, empresa=empresa, titulo=None, perfil=None, origem="email",
                            enviada_em="2026-10-01T10:00:00+00:00")
        conn.executemany("UPDATE emails SET candidatura_id = ? WHERE id = ?", [(pid, e) for e in ids])
    cand._entrevista_dos_emails(conn, pid)
    cand.recalcular(conn, pid)
    return pid


def test_parecidas_so_para_pingada_e_so_ativas_da_mesma_empresa(conn):
    estagio = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio Corporativo")
    encerrada = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Trainee")
    cand.cancelar(conn, encerrada)
    cand.registrar_manual(conn, "Outra Empresa", "geral", titulo="Dev")
    pid = _pingada(conn)
    assert [p["id"] for p in cand.parecidas(conn, pid)] == [estagio]
    assert cand.parecidas(conn, estagio) == []
    d = cand.detalhe(conn, pid)
    assert [p["titulo"] for p in d["parecidas"]] == ["Estágio Corporativo"] and d["roteiro"] is None


def test_juntar_leva_os_emails_e_a_entrevista_e_apaga_a_pingada(conn):
    """Review Focus 2."""
    destino = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio Corporativo")
    cand.ligar_manual(conn, _email(conn, "avanco", "Grupo Tavares", gid="d1"), destino)
    pid = _pingada(conn, n_emails=2, entrevista="2026-10-12T14:00:00-03:00")
    d = cand.juntar(conn, pid, destino)
    assert len(d["emails"]) == 3 and d["candidatura"]["status"] == "entrevista"
    assert d["candidatura"]["entrevista_em"] == "2026-10-12T14:00:00-03:00"
    assert conn.execute("SELECT COUNT(*) FROM candidaturas WHERE id = ?", (pid,)).fetchone()[0] == 0


def test_juntar_recusa_origem_nao_pingada_a_mesma_e_destino_encerrado(conn):
    a = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio")
    b = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Trainee")
    pid = _pingada(conn)
    with pytest.raises(cand.CandidaturaRecusada):
        cand.juntar(conn, a, b)
    with pytest.raises(cand.CandidaturaRecusada):
        cand.juntar(conn, pid, pid)
    cand.cancelar(conn, b)
    with pytest.raises(cand.CandidaturaRecusada):
        cand.juntar(conn, pid, b)
    assert conn.execute("SELECT COUNT(*) FROM emails WHERE candidatura_id = ?", (pid,)).fetchone()[0] == 1


def test_nova_do_email_cria_pingada_e_liga(conn):
    sem_empresa = _email(conn, "avanco", None, gid="n1")
    with pytest.raises(cand.CandidaturaRecusada, match="empresa"):
        cand.nova_do_email(conn, sem_empresa)
    existente = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio")
    e = _email(conn, "pendencia", "Grupo Tavares", gid="n2")
    nova = cand.nova_do_email(conn, e)
    assert nova != existente
    c = _cand(conn, nova)
    assert (c["origem"], c["titulo"], c["empresa"], c["status"]) == ("email", None, "Grupo Tavares", "enviada")
    assert cand.email(conn, e)["candidatura_id"] == nova
    outro = _email(conn, "outro", "Grupo Tavares", gid="n3")
    with pytest.raises(cand.CandidaturaRecusada):
        cand.nova_do_email(conn, outro)


def test_entrevista_com_titulo_padrao_e_desmarcar_limpa(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    d = cand.marcar_entrevista(conn, cid, "2026-10-12T14:00:00-03:00", "")
    assert d["candidatura"]["entrevista_titulo"] == "Entrevista"
    d = cand.marcar_entrevista(conn, cid, "2026-10-12T14:00:00-03:00", "Conversa com o gestor")
    assert d["candidatura"]["entrevista_titulo"] == "Conversa com o gestor"
    d = cand.marcar_entrevista(conn, cid, None)
    c = d["candidatura"]
    assert (c["entrevista_em"], c["entrevista_titulo"], c["status"]) == (None, None, "enviada")


def test_detalhe_traz_quantos_fatos_o_curriculo_usou(conn, vaga_id):
    with conn:
        vid = conn.execute("INSERT INTO cv_versions (job_id, idioma, caminho, fatos, criado_em, perfil)"
                           " VALUES (?, 'pt', 'cv.md', '[\"a\", \"b\", \"c\"]', '2026-10-10T09:40:00+00:00', 'front-end')",
                           (vaga_id,)).lastrowid
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", vid)
    assert candidaturas.detalhe(conn, cid)["cv"]["n_fatos"] == 3


def test_reabrir_desfaz_o_cancelamento_e_recalcula(conn, vaga_id):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral", titulo="Dev")
    cand.ligar_manual(conn, _email(conn, "avanco", "Orla Tech", gid="r1"), cid)
    cand.cancelar(conn, cid)
    assert cand.reabrir(conn, cid)["candidatura"]["status"] == "em_processo"
    a_enviar = cand.registrar_do_cv(conn, vaga_id, "front-end", None)
    cand.cancelar(conn, a_enviar)
    assert cand.reabrir(conn, a_enviar, "a_enviar")["candidatura"]["status"] == "a_enviar"
    with pytest.raises(cand.CandidaturaRecusada):
        cand.reabrir(conn, cid)  # não está cancelada


# --- triagem: um passo atômico e o desfazer (Review Focus 4) ------------------------

def _revisar(conn, gid, empresa=None, recebido="2026-10-05T10:00:00+00:00"):
    return _email(conn, "revisar", empresa, recebido=recebido, gid=gid)


def test_triar_com_empresa_nova_cria_pingada_e_restaurar_apaga_ela(conn):
    e = _revisar(conn, "t1")
    r = cand.triar(conn, e, "avanco", empresa="Porto Digital")
    assert r["candidatura_id"] == r["criada"] is not None
    assert _cand(conn, r["criada"])["status"] == "em_processo"
    cand.restaurar_email(conn, e, rotulo_manual=None, candidatura_id=None, empresa=None, apagar=r["criada"])
    linha = conn.execute("SELECT rotulo_manual, candidatura_id, empresa_extraida FROM emails WHERE id = ?", (e,)).fetchone()
    assert tuple(linha) == (None, None, None)
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 0
    assert [x["id"] for x in cand.emails_pendentes(conn)] == [e]


def test_triar_ligando_a_mao_e_desfazer_recalcula(conn):
    cid = cand.registrar_manual(conn, "Lumina Saúde", "geral", titulo="Engenheiro")
    e = _revisar(conn, "t2", empresa="Outra Coisa")
    r = cand.triar(conn, e, "avanco", candidatura_id=cid)
    assert (r["candidatura_id"], r["criada"]) == (cid, None)
    assert _cand(conn, cid)["status"] == "em_processo"
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 1  # nenhuma pingada de "Outra Coisa"
    cand.restaurar_email(conn, e, rotulo_manual=None, candidatura_id=None, empresa="Outra Coisa", apagar=None)
    assert _cand(conn, cid)["status"] == "enviada"
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 1


def test_triar_outro_nao_liga_e_nova_cria_mesmo_com_outra_ativa(conn):
    existente = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio")
    e = _revisar(conn, "t3", empresa="Grupo Tavares")
    assert cand.triar(conn, e, "outro") == {"candidatura_id": None, "criada": None}
    e2 = _revisar(conn, "t4", empresa="Grupo Tavares")
    r = cand.triar(conn, e2, "inscricao_confirmada", nova=True)
    assert r["criada"] not in (None, existente) and r["candidatura_id"] == r["criada"]
    with pytest.raises(cand.CandidaturaRecusada):
        cand.triar(conn, e2, "revisar")


def test_restaurar_nao_apaga_candidatura_que_tem_emails(conn):
    e = _revisar(conn, "t5")
    r = cand.triar(conn, e, "avanco", empresa="Porto Digital")
    outro = _email(conn, "avanco", "Porto Digital", gid="t6")
    cand.ligar_manual(conn, outro, r["criada"])
    cand.restaurar_email(conn, e, rotulo_manual=None, candidatura_id=None, empresa=None, apagar=r["criada"])
    assert _cand(conn, r["criada"])["id"] == r["criada"]


# --- revisão final ---------------------------------------------------------------------

def test_desfazer_triagem_devolve_a_candidatura_a_enviar(conn, vaga_id):
    """Review Focus 1 × 4: o desfazer não pode deixar a candidatura contando como enviada."""
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    antes = _cand(conn, cid)
    e = _revisar(conn, "rf1")
    r = cand.triar(conn, e, "avanco", candidatura_id=cid)
    assert _cand(conn, cid)["status"] == "em_processo"
    cand.restaurar_email(conn, e, rotulo_manual=None, candidatura_id=None, empresa=None, apagar=r["criada"],
                         candidatura_antes=r["candidatura_antes"])
    depois = _cand(conn, cid)
    assert (depois["status"], depois["enviada_em"]) == ("a_enviar", antes["enviada_em"])
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (vaga_id,)).fetchone()[0] != "aplicado"


def test_juntar_preserva_entrevista_e_roteiro_da_pingada(conn):
    destino = cand.registrar_manual(conn, "Grupo Tavares", "geral", titulo="Estágio")
    pid = _pingada(conn)
    cand.marcar_entrevista(conn, pid, "2026-10-20T10:00:00-03:00", "Painel")
    cand.salvar_roteiro(conn, pid, [{"tema": "SQL"}])
    d = cand.juntar(conn, pid, destino)
    c = d["candidatura"]
    assert (c["entrevista_em"], c["entrevista_titulo"], c["status"]) == ("2026-10-20T10:00:00-03:00", "Painel", "entrevista")
    assert d["roteiro"]["itens"] == [{"tema": "SQL"}]


def test_reabrir_pelo_menu_volta_o_rascunho_para_a_enviar(conn, vaga_id):
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    cand.cancelar(conn, cid)
    assert cand.reabrir(conn, cid)["candidatura"]["status"] == "a_enviar"
    enviada = cand.registrar_manual(conn, "Orla", "geral")
    cand.cancelar(conn, enviada)
    assert cand.reabrir(conn, enviada)["candidatura"]["status"] == "enviada"


def test_nao_vou_enviar_remove_o_rascunho_e_desfazer_devolve(conn, vaga_id):
    cid = candidaturas.registrar_do_cv(conn, vaga_id, "front-end", None)
    antes = _cand(conn, cid)
    rascunho = cand.descartar_rascunho(conn, cid)
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 0
    d = cand.restaurar_rascunho(conn, rascunho)
    assert d["candidatura"]["id"] == cid
    assert {k: d["candidatura"][k] for k in ("status", "enviada_em", "perfil", "job_id")} == \
        {k: antes[k] for k in ("status", "enviada_em", "perfil", "job_id")}


def test_nao_vou_enviar_so_vale_para_rascunho_sem_emails(conn, vaga_id):
    enviada = cand.registrar_manual(conn, "Orla", "geral")
    with pytest.raises(cand.CandidaturaRecusada):
        cand.descartar_rascunho(conn, enviada)


def test_marcar_entrevista_sem_fuso_grava_com_o_fuso_local(conn, em_sao_paulo):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    d = cand.marcar_entrevista(conn, cid, "2026-10-14T14:00:00")
    assert d["candidatura"]["entrevista_em"] == "2026-10-14T14:00:00-03:00"


def test_marcar_entrevista_com_fuso_nao_muda(conn, em_sao_paulo):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    d = cand.marcar_entrevista(conn, cid, "2026-10-14T14:00:00+01:00")
    assert d["candidatura"]["entrevista_em"] == "2026-10-14T14:00:00+01:00"


def test_entrevista_marcada_a_mao_conta_como_resposta(conn):
    cid = cand.registrar_do_cv(conn, _vaga(conn), "engenharia-ia", None)
    cand.marcar_enviada(conn, cid)
    cand.marcar_entrevista(conn, cid, "2026-10-10T14:00:00-03:00")
    primeira = _cand(conn, cid)["respondida_em"]
    assert primeira is not None
    cand.marcar_entrevista(conn, cid, "2026-10-12T10:00:00-03:00")
    assert _cand(conn, cid)["respondida_em"] == primeira  # remarcar não muda quando ela respondeu
    cand.marcar_entrevista(conn, cid, None)
    assert _cand(conn, cid)["respondida_em"] is None


def test_data_de_envio_no_futuro_e_recusada(conn):
    from datetime import date, timedelta

    amanha = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(cand.CandidaturaRecusada, match="futuro"):
        cand.registrar_manual(conn, "Orla Tech", "geral", enviada_em=amanha)
    cid = cand.registrar_do_cv(conn, _vaga(conn), None, None)
    with pytest.raises(cand.CandidaturaRecusada, match="futuro"):
        cand.marcar_enviada(conn, cid, amanha)
    assert cand.marcar_enviada(conn, cid, date.today().isoformat())["candidatura"]["status"] == "enviada"


def test_ligar_vaga_a_candidatura_manual(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral", titulo="Dev React")
    job = _vaga(conn)
    d = cand.ligar_vaga(conn, cid, job)
    assert d["candidatura"]["job_id"] == job
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job,)).fetchone()[0] == "aplicado"


def test_ligar_vaga_recusa_vaga_inexistente_ou_ja_ligada(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    with pytest.raises(cand.CandidaturaRecusada, match="não existe"):
        cand.ligar_vaga(conn, cid, 999)
    job = _vaga(conn)
    outra = cand.registrar_do_cv(conn, job, None, None)
    with pytest.raises(cand.CandidaturaRecusada, match="já está"):
        cand.ligar_vaga(conn, cid, job)
    assert cand.detalhe(conn, outra)["candidatura"]["job_id"] == job


def test_religar_outra_vaga_devolve_a_anterior_para_as_abertas(conn):
    cid = cand.registrar_manual(conn, "Orla Tech", "geral")
    antiga, nova = _vaga(conn), _vaga(conn, "Outra")
    cand.ligar_vaga(conn, cid, antiga)
    cand.ligar_vaga(conn, cid, nova)
    status = dict(conn.execute("SELECT id, status FROM jobs WHERE id IN (?, ?)", (antiga, nova)).fetchall())
    assert (status[antiga], status[nova]) == ("analisado", "aplicado")


# --- mesma empresa escrita de jeitos diferentes ------------------------------------


@pytest.mark.parametrize("a, b, esperado", [
    ("apollo solutions dev", "apollosolutions", True),   # remetente do ATS × domínio do RH (Apollo, 13/10)
    ("tech lab", "techlab", True),                        # só os espaços mudam
    ("quartzo", "quartzo", True),
    ("banco inter tech", "banco inter labs", True),       # sobra "banco inter" nos dois
    ("tech lab", "tech dev", False),                      # tirar a palavra genérica deixaria só "tech"
    ("techlab", "techdev", False),
    ("apollo", "apollo solutions", False),                # uma palavra só não basta
    ("orbital dev", "orbital", False),
    ("", "", False),
])
def test_mesma_empresa(a, b, esperado):
    assert cand.mesma_empresa(a, b) is esperado
    assert cand.mesma_empresa(b, a) is esperado


def test_email_do_ats_liga_na_pingada_do_dominio(conn):
    primeira = cand.ligar(conn, _email(conn, "avanco", "apollosolutions", "2026-10-02T00:00:00+00:00"))
    segunda = cand.ligar(conn, _email(conn, "avanco", "Apollo Solutions Dev", "2026-10-13T00:00:00+00:00"))
    assert segunda == primeira
    assert conn.execute("SELECT COUNT(*) FROM candidaturas").fetchone()[0] == 1


def test_empresas_parecidas_continuam_separadas(conn):
    lab = cand.ligar(conn, _email(conn, "avanco", "Tech Lab", "2026-10-02T00:00:00+00:00"))
    dev = cand.ligar(conn, _email(conn, "avanco", "Tech Dev", "2026-10-03T00:00:00+00:00"))
    assert lab != dev


def test_parecidas_acha_a_mesma_empresa_escrita_diferente(conn):
    estagio = cand.registrar_do_cv(conn, _vaga(conn, empresa="Apollo Solutions"), "geral", None)
    pid = cand.ligar(conn, _email(conn, "inscricao_confirmada", "Apollo Solutions Dev"))
    assert pid == estagio  # já liga direto na candidatura do currículo
    outra = cand.nova_do_email(conn, _email(conn, "avanco", "Apollo Solutions Dev", gid="g-novo"))
    assert [p["id"] for p in cand.parecidas(conn, outra)] == [estagio]
