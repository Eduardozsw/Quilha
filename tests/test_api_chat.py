"""Chat pela API: turno em SSE, confirmação de gravação por clique. Modelo sempre mockado."""

import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hermes.api import chat
from hermes.api.app import criar_app
from hermes.config import load_config
from hermes.db import store
from hermes.domain import competencias
from hermes.run_status import RunStatus
from hermes.vault import indice

TOKEN = "t"


def tool_call(nome, argumentos="{}", id="call_1"):
    return SimpleNamespace(
        id=id, type="function", function=SimpleNamespace(name=nome, arguments=argumentos)
    )


def resposta(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


@pytest.fixture
def modelo(mocker):
    import litellm

    mock = mocker.patch.object(litellm, "completion")
    mocker.patch.object(litellm, "completion_cost", return_value=0.001)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    return mock


@pytest.fixture
def cfg(vault, seed_yaml, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_MCP", str(tmp_path / "sem-mcp.yaml"))
    config = load_config(vault_path=vault, db_path=tmp_path / "hermes.db")
    conn = store.connect(config.db_path)
    try:
        indice.reindexar(conn, vault, [], RunStatus())
        competencias.seed(conn, seed_yaml)
    finally:
        conn.close()
    return config


@pytest.fixture
def api(cfg):
    return TestClient(criar_app(cfg, TOKEN), headers={"X-Hermes-Token": TOKEN})


def _eventos(r):
    """Lê o corpo SSE: pares (evento, dados)."""
    eventos, tipo = [], None
    for linha in r.iter_lines():
        if linha.startswith("event: "):
            tipo = linha[7:]
        elif linha.startswith("data: "):
            eventos.append((tipo, json.loads(linha[6:])))
    return eventos


def _nova_sessao(api):
    return api.post("/api/chat/sessoes").json()["id"]


def test_turno_simples_em_sse(api, modelo):
    modelo.side_effect = [resposta(content="oi, Ana")]
    sid = _nova_sessao(api)

    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        eventos = _eventos(r)

    tipos = [t for t, _ in eventos]
    assert tipos[-1] == "fim"
    assert eventos[-1][1]["resposta"] == "oi, Ana"
    assert eventos[-1][1]["custo"]["custo_usd"] == pytest.approx(0.001)

    mensagens = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert [m["role"] for m in mensagens] == ["user", "assistant"]
    sessoes = api.get("/api/chat/sessoes").json()
    assert sessoes[0]["id"] == sid and sessoes[0]["titulo"] == "oi"


def test_evento_de_tool_aparece_no_stream(api, modelo):
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("list_competencies")]),
        resposta(content="você tem 3"),
    ]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "quantas?"}) as r:
        eventos = _eventos(r)
    assert ("tool", "list_competencies") in [(t, d.get("nome")) for t, d in eventos]


def test_sessao_inexistente_e_422_antes_do_stream(api):
    r = api.post("/api/chat/sessoes/999/turnos", json={"texto": "oi"})
    assert r.status_code == 422


def test_custo_da_sessao_acumula_entre_turnos(api, modelo):
    modelo.side_effect = [resposta(content="um"), resposta(content="dois")]
    sid = _nova_sessao(api)
    for texto in ("a", "b"):
        with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": texto}) as r:
            _eventos(r)
    assert api.get("/api/chat/sessoes").json()[0]["cost_usd"] == pytest.approx(0.002)


# --- confirmação ---------------------------------------------------------------


def test_confirmacao_aprovada_libera_a_gravacao(cfg, modelo):
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("log_study", '{"minutos": 20, "o_que_fez": "RRF"}')]),
        resposta(content="registrado"),
    ]
    cfg_confirma = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset()})
    confirmacoes = chat.Confirmacoes()
    eventos = []

    def emitir(tipo, dados):
        eventos.append((tipo, dados))
        if tipo == "confirmar":
            threading.Thread(target=confirmacoes.responder, args=(dados["id"], True)).start()

    conn = store.connect(cfg.db_path)
    sid = chat.abrir_sessao(conn, cfg.llm_model)
    conn.close()
    chat.rodar_turno(cfg_confirma, sid, "estudei 20 min", confirmacoes, emitir)

    confirmar = next(d for t, d in eventos if t == "confirmar")
    assert confirmar["tool"] == "log_study" and confirmar["argumentos"]["minutos"] == 20
    assert eventos[-1][0] == "fim"
    conn = store.connect(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0] == 1
    finally:
        conn.close()


def test_confirmacao_recusada_nao_grava(cfg, modelo):
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("log_study", '{"minutos": 20, "o_que_fez": "RRF"}')]),
        resposta(content="ok, não gravei"),
    ]
    cfg_confirma = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset()})
    confirmacoes = chat.Confirmacoes()

    def emitir(tipo, dados):
        if tipo == "confirmar":
            threading.Thread(target=confirmacoes.responder, args=(dados["id"], False)).start()

    conn = store.connect(cfg.db_path)
    sid = chat.abrir_sessao(conn, cfg.llm_model)
    conn.close()
    chat.rodar_turno(cfg_confirma, sid, "estudei", confirmacoes, emitir)

    conn = store.connect(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0] == 0
    finally:
        conn.close()


def test_confirmacao_sem_resposta_expira_como_recusa():
    confirmacoes = chat.Confirmacoes(timeout=0.05)
    tool = SimpleNamespace(nome="log_study")
    assert confirmacoes.pedir(lambda *_: None, tool, {}) is False
    assert confirmacoes.responder("inexistente", True) is False


def test_endpoint_de_confirmacao_desconhecida_e_404(api):
    assert api.post("/api/chat/confirmacoes/nada", json={"aprovar": True}).status_code == 404


def test_erro_http_usa_o_mesmo_formato_das_recusas(api):
    r = api.post("/api/chat/sessoes/999/turnos", json={"texto": "oi"})
    assert r.json() == {"erro": "sessão 999 não existe"}


def test_chave_recusada_no_chat_acende_o_status(api, modelo):
    """Revisão final: o turno engole a exceção para emitir `erro`; a recusa da chave precisa acender o status."""
    erro = type("AuthenticationError", (Exception,), {"__module__": "litellm.exceptions"})
    modelo.side_effect = erro("invalid api key")
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"}) as r:
        eventos = _eventos(r)
    assert eventos[-1][0] == "erro"
    problemas = api.get("/api/config/saude").json()["problemas"]
    assert "llm_recusada" in [p["tipo"] for p in problemas]


# --- título e meta (V3) ----------------------------------------------------------


@pytest.mark.parametrize("texto, esperado", [
    ("Me fala sobre a vaga da Orla Tech", "Me fala sobre a vaga da Orla Tech"),
    ("Compara as 8 vagas abertas com o meu vault e me diz qual vale mais",
     "Compara as 8 vagas abertas com o meu…"),
    ("a" * 60, "a" * 40 + "…"),
    ("   oi   ", "oi"),
    ("linha um\nlinha dois", "linha um linha dois"),
])
def test_titulo_automatico_corta_no_fim_de_palavra(texto, esperado):
    assert chat.titulo_automatico(texto) == esperado


def test_titulo_editado_aparece_e_vazio_volta_ao_automatico(api, modelo):
    modelo.side_effect = [resposta(content="ok")]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "Me fala sobre a Orla"}) as r:
        _eventos(r)

    r = api.put(f"/api/chat/sessoes/{sid}/titulo", json={"titulo": "  Vaga da Orla  "})
    assert r.status_code == 200 and r.json()["titulo"] == "Vaga da Orla"
    assert api.get("/api/chat/sessoes").json()[0]["titulo"] == "Vaga da Orla"

    for vazio in ("   ", None):
        r = api.put(f"/api/chat/sessoes/{sid}/titulo", json={"titulo": vazio})
        assert r.json()["titulo"] == "Me fala sobre a Orla"
    assert api.put("/api/chat/sessoes/999/titulo", json={"titulo": "x"}).status_code == 422


def test_sessao_sem_pergunta_tem_titulo_nulo(api):
    _nova_sessao(api)
    assert api.get("/api/chat/sessoes").json()[0]["titulo"] is None


def test_mensagens_devolvem_meta_e_o_provedor_nao_ve(cfg):
    from hermes.agent import session as agent_session

    conn = store.connect(cfg.db_path)
    try:
        sessao = agent_session.abrir(conn)
        sessao.gravar({"role": "user", "content": "oi"})
        sessao.gravar({"role": "assistant", "content": "olá"}, meta={"custo_usd": 0.002, "parado": False})
        assert chat.mensagens(conn, sessao.id) == [
            {"role": "user", "content": "oi", "meta": None},
            {"role": "assistant", "content": "olá", "meta": {"custo_usd": 0.002, "parado": False}},
        ]
        assert all("meta" not in m for m in sessao.mensagens())
    finally:
        conn.close()


# --- Parar (V3) ---------------------------------------------------------------------


def test_parar_com_confirmacao_pendente_recusa_na_hora_e_a_conversa_continua(api, modelo, cfg):
    """Review Focus 1: o pedido pendente vira recusa sem esperar 5 min; nada é gravado; a próxima pergunta roda."""
    api.app.state.cfg = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset()})
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("log_study", '{"minutos": 20, "o_que_fez": "RRF"}')]),
        resposta(content="oi de novo"),
    ]
    sid = _nova_sessao(api)
    parou = {}

    def apertar_parar():
        # o TestClient só entrega o SSE no fim do turno: o Parar sai quando o pedido fica pendente
        import time

        limite = time.monotonic() + 10
        while not api.app.state.confirmacoes._pendentes and time.monotonic() < limite:
            time.sleep(0.01)
        parou.update(api.post(f"/api/chat/sessoes/{sid}/parar").json())

    botao = threading.Thread(target=apertar_parar)
    botao.start()
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "estudei"}) as r:
        eventos = _eventos(r)
    botao.join(5)

    assert parou == {"ok": True}
    assert "confirmar" in [t for t, _ in eventos]
    assert eventos[-1][0] == "fim" and eventos[-1][1]["parou_por"] == "parado"
    assert modelo.call_count == 1
    historico = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert historico[-1]["role"] == "tool" and '"cancelado"' in historico[-1]["content"]

    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "e agora?"}) as r:
        assert _eventos(r)[-1][1]["resposta"] == "oi de novo"
    conn = store.connect(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0] == 0
    finally:
        conn.close()


def test_parar_sem_turno_rodando_devolve_false(api):
    sid = _nova_sessao(api)
    assert api.post(f"/api/chat/sessoes/{sid}/parar").json() == {"ok": False}


def test_cancelar_da_sessao_so_libera_os_pedidos_dela():
    confirmacoes = chat.Confirmacoes(timeout=5)
    tool = SimpleNamespace(nome="log_study")
    resultados = {}

    def pedir(sid):
        resultados[sid] = confirmacoes.pedir(lambda *_: None, tool, {}, sessao_id=sid)

    threads = [threading.Thread(target=pedir, args=(sid,)) for sid in (1, 2)]
    for t in threads:
        t.start()
    import time

    limite = time.monotonic() + 2
    while len(confirmacoes._pendentes) < 2 and time.monotonic() < limite:
        time.sleep(0.01)
    assert confirmacoes.cancelar_da_sessao(1) == 1
    threads[0].join(1)
    assert resultados == {1: False} and threads[1].is_alive()
    confirmacoes.cancelar_da_sessao(2)
    threads[1].join(1)


# --- eventos ricos (V3) ---------------------------------------------------------------


def test_eventos_ricos_e_meta_da_resposta(api, modelo):
    modelo.side_effect = [
        resposta(content="Vou olhar. ", tool_calls=[tool_call("list_competencies")]),
        resposta(content="você tem 3"),
    ]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "quantas competências?"}) as r:
        eventos = _eventos(r)

    tool = next(d for t, d in eventos if t == "tool")
    assert tool["rotulo"]["feito"] == "Consultou as competências"
    assert ("tool_resultado", {"nome": "list_competencies", "ok": True}) in eventos
    assert [d["texto"] for t, d in eventos if t == "trecho"] == ["Vou olhar. ", "você tem 3"]
    tipo, fim = eventos[-1]
    assert tipo == "fim" and fim["cartoes"] == [] and fim["titulo"] == "quantas competências?"
    assert fim["custo"]["custo_usd"] == pytest.approx(0.002)

    historico = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert historico[-1]["meta"] == {
        "custo_usd": pytest.approx(0.002), "cartoes": [], "confirmacoes": [],
        "ferramentas": [{"nome": "list_competencies", "ok": True}], "parado": False}
    assert all(m["meta"] is None for m in historico[:-1])


def test_confirmacao_expirada_resolve_como_expirou_e_fica_no_meta(cfg, modelo):
    """Review Focus 4."""
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("assess_competency", '{"slug": "sql", "nivel": 3, "justificativa": "x"}')]),
        resposta(content="ok, não gravei"),
    ]
    cfg_confirma = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset()})
    eventos = []
    conn = store.connect(cfg.db_path)
    sid = chat.abrir_sessao(conn, cfg.llm_model)
    conn.close()
    chat.rodar_turno(cfg_confirma, sid, "sou nível 3 em SQL", chat.Confirmacoes(timeout=0.05),
                     lambda t, d: eventos.append((t, d)))

    confirmar = next(d for t, d in eventos if t == "confirmar")
    assert confirmar["titulo"] == "Gravar este nível?" and confirmar["resumo"] == "SQL nível 3"
    assert confirmar["tool"] == "assess_competency"  # o campo da V2 continua
    assert ("confirmacao_resolvida", {"id": confirmar["id"], "resultado": "expirou",
                                      "linha": "Expirou · SQL nível 3 não gravado"}) in eventos
    conn = store.connect(cfg.db_path)
    try:
        meta = chat.mensagens(conn, sid)[-1]["meta"]
    finally:
        conn.close()
    assert meta["confirmacoes"] == [{"objeto": "Nível", "resumo": "SQL nível 3", "resultado": "expirou",
                                     "linha": "Expirou · SQL nível 3 não gravado", "ferramenta": "assess_competency"}]
    assert confirmar["linhas"]["expirou"] == "Expirou · SQL nível 3 não gravado"  # a tela mostra no 404


def test_confirmacao_aprovada_resolve_como_gravado(cfg, modelo):
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("log_study", '{"minutos": 20, "o_que_fez": "RRF"}')]),
        resposta(content="registrado"),
    ]
    cfg_confirma = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset()})
    confirmacoes = chat.Confirmacoes()
    eventos = []

    def emitir(tipo, dados):
        eventos.append((tipo, dados))
        if tipo == "confirmar":
            threading.Thread(target=confirmacoes.responder, args=(dados["id"], True)).start()

    conn = store.connect(cfg.db_path)
    sid = chat.abrir_sessao(conn, cfg.llm_model)
    conn.close()
    chat.rodar_turno(cfg_confirma, sid, "estudei 20 min", confirmacoes, emitir)
    resolvida = next(d for t, d in eventos if t == "confirmacao_resolvida")
    assert resolvida["resultado"] == "gravado" and resolvida["linha"] == "Estudo gravado · 20 min de estudo"


@pytest.mark.parametrize("erro, tipo", [
    (type("AuthenticationError", (Exception,), {"__module__": "litellm.exceptions"}), "chave"),
    (type("APIConnectionError", (Exception,), {"__module__": "litellm.exceptions"}), "llm"),
    (type("ValueError", (ValueError,), {}), "outro"),
])
def test_erro_tipado_no_fio(api, modelo, erro, tipo):
    modelo.side_effect = erro("caiu")
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"}) as r:
        evento, dados = _eventos(r)[-1]
    assert evento == "erro" and dados["tipo"] == tipo and dados["mensagem"]
    # a pergunta fica no histórico (o balão continua no fio)
    assert api.get(f"/api/chat/sessoes/{sid}/mensagens").json()[0]["content"] == "oi"


def test_teto_de_custo_vira_erro_teto(api, modelo, cfg):
    api.app.state.cfg = cfg.__class__(**{**cfg.__dict__, "max_cost_usd": 0.0015})
    modelo.side_effect = [resposta(tool_calls=[tool_call("list_competencies", id=f"c{i}")]) for i in range(5)]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"}) as r:
        evento, dados = _eventos(r)[-1]
    assert evento == "erro" and dados["tipo"] == "teto"


def test_fim_traz_os_cartoes_do_turno(api, modelo, cfg):
    conn = store.connect(cfg.db_path)
    with conn:
        jid = conn.execute(
            "INSERT INTO jobs (empresa, titulo, fonte, texto_bruto, hash_texto, coletado_em)"
            " VALUES ('Orla Tech', 'Dev React', 'colado', 'x', 'h', '2026-10-01')").lastrowid
        conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                     " (?, 'Python', 'obrigatorio', (SELECT id FROM competencies WHERE slug = 'python'))", (jid,))
    conn.close()
    api.app.state.cfg = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset({"match_job"})})
    modelo.side_effect = [
        resposta(tool_calls=[tool_call("match_job", f'{{"job_id": {jid}}}')]),
        resposta(content='{"lacunas": {}, "riscos": []}'),  # o texto do match_job
        resposta(content="combina"),
    ]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "e a Orla?"}) as r:
        evento, fim = _eventos(r)[-1]
    assert evento == "fim", fim
    assert [(c["tipo"], c["job_id"]) for c in fim["cartoes"]] == [("vaga", jid)]
    meta = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()[-1]["meta"]
    assert meta["cartoes"] == fim["cartoes"]


def test_conversa_da_v2_sem_meta_continua_abrindo(api, cfg):
    """Review Focus 5."""
    conn = store.connect(cfg.db_path)
    with conn:
        sid = conn.execute("INSERT INTO agent_sessions (started_at) VALUES ('2026-09-01')").lastrowid
        conn.execute("INSERT INTO agent_messages (session_id, idx, role, content, criado_em)"
                     " VALUES (?, 0, 'user', 'oi', '2026-09-01')", (sid,))
        conn.execute("INSERT INTO agent_messages (session_id, idx, role, content, tool_calls, criado_em)"
                     " VALUES (?, 1, 'assistant', NULL, ?, '2026-09-01')",
                     (sid, '[{"id": "c1", "type": "function", "function": {"name": "list_jobs", "arguments": "{}"}}]'))
        conn.execute("INSERT INTO agent_messages (session_id, idx, role, content, tool_call_id, criado_em)"
                     " VALUES (?, 2, 'tool', '{\"ok\": true}', 'c1', '2026-09-01')", (sid,))
        conn.execute("INSERT INTO agent_messages (session_id, idx, role, content, criado_em)"
                     " VALUES (?, 3, 'assistant', 'tem 2', '2026-09-01')", (sid,))
    conn.close()
    historico = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert [m["role"] for m in historico] == ["user", "assistant", "tool", "assistant"]
    assert all(m["meta"] is None for m in historico)


# --- o que a tela da Conversa precisa (Task 4) -------------------------------------------


def test_historico_traz_o_rotulo_das_ferramentas(api, modelo):
    modelo.side_effect = [resposta(tool_calls=[tool_call("list_jobs")]), resposta(content="nenhuma")]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "vagas?"}) as r:
        _eventos(r)
    pediu = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()[1]
    assert pediu["ferramentas"] == [{"nome": "list_jobs", "rotulo": {
        "rodando": "Consultando as vagas…", "feito": "Consultou as vagas", "falhou": "Não consegui consultar as vagas",
        "verbo": "Consultou", "objeto": "as vagas"}}]


def test_teto_traz_o_gasto_e_o_teto(api, modelo, cfg):
    api.app.state.cfg = cfg.__class__(**{**cfg.__dict__, "max_cost_usd": 0.0015})
    modelo.side_effect = [resposta(tool_calls=[tool_call("list_competencies", id=f"c{i}")]) for i in range(5)]
    sid = _nova_sessao(api)
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"}) as r:
        _, dados = _eventos(r)[-1]
    assert dados["teto_usd"] == pytest.approx(0.0015) and dados["gasto_usd"] == pytest.approx(0.002)


def test_tentar_de_novo_nao_duplica_a_pergunta(api, modelo):
    erro = type("APIConnectionError", (Exception,), {"__module__": "litellm.exceptions"})
    modelo.side_effect = [erro("caiu"), resposta(content="agora foi")]
    sid = _nova_sessao(api)
    for _ in range(2):
        with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"}) as r:
            _eventos(r)
    historico = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert [(m["role"], m["content"]) for m in historico] == [("user", "oi"), ("assistant", "agora foi")]


# --- revisão final ------------------------------------------------------------------------


def test_segundo_turno_na_mesma_sessao_enquanto_o_primeiro_roda_e_409(api, modelo, cfg):
    """Revisão final (I1): dois turnos na mesma sessão quebrariam o histórico (tool sem resposta antes do user)."""
    api.app.state.cfg = cfg.__class__(**{**cfg.__dict__, "sem_confirmacao": frozenset()})
    modelo.side_effect = [resposta(tool_calls=[tool_call("log_study", '{"minutos": 20, "o_que_fez": "RRF"}')])]
    sid = _nova_sessao(api)
    resultado = {}

    def segundo():
        import time

        limite = time.monotonic() + 10
        while not api.app.state.confirmacoes._pendentes and time.monotonic() < limite:
            time.sleep(0.01)
        resultado["status"] = api.post(f"/api/chat/sessoes/{sid}/turnos", json={"texto": "outra"}).status_code
        api.post(f"/api/chat/sessoes/{sid}/parar")

    t = threading.Thread(target=segundo)
    t.start()
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "estudei"}) as r:
        _eventos(r)
    t.join(5)
    assert resultado["status"] == 409


def test_pedido_que_nasce_depois_do_parar_ja_sai_recusado():
    """Revisão final (I4): o Parar que chegou antes do pedido existir não pode deixar o pedido esperar 5 min."""
    import time

    confirmacoes = chat.Confirmacoes(timeout=5)
    parar = threading.Event()
    parar.set()
    inicio = time.monotonic()
    _, resultado = confirmacoes.pedir_resultado(lambda *_: None, SimpleNamespace(nome="log_study"), {}, 1, parar=parar)
    assert resultado == "recusado" and time.monotonic() - inicio < 1


def test_responder_depois_do_cancelamento_nao_vira_aprovado():
    """Revisão final (I4): o primeiro que resolve o pedido vale; um "Gravar" atrasado não desfaz o Parar."""
    confirmacoes = chat.Confirmacoes(timeout=5)
    resultado, ids = {}, []

    def pedir():
        resultado["r"] = confirmacoes.pedir_resultado(lambda t, d: ids.append(d["id"]), SimpleNamespace(nome="log_study"), {}, 7)[1]

    t = threading.Thread(target=pedir)
    t.start()
    import time

    limite = time.monotonic() + 2
    while not ids and time.monotonic() < limite:
        time.sleep(0.01)
    # o Parar e o "Gravar" quase juntos: o cancelamento chega primeiro
    assert confirmacoes.cancelar_da_sessao(7) == 1
    assert confirmacoes.responder(ids[0], True) is False
    t.join(2)
    assert resultado["r"] == "recusado"


def test_apagar_conversa(api):
    sid = api.post("/api/chat/sessoes").json()["id"]
    assert api.delete(f"/api/chat/sessoes/{sid}").json() == {"ok": True}
    assert all(s["id"] != sid for s in api.get("/api/chat/sessoes").json())
    assert api.get(f"/api/chat/sessoes/{sid}/mensagens").status_code == 422
    assert api.delete(f"/api/chat/sessoes/{sid}").status_code == 422


def test_tentar_de_novo_depois_do_stream_cair_guarda_o_meta_do_turno(api, modelo):
    """A repetição apaga o parcial antes de responder: a resposta nova precisa ganhar o custo no histórico."""
    from tests.streaming import chunk

    def cai():
        yield chunk("Comparando as vagas, ")
        raise ConnectionError("conexão caiu")

    sid = _nova_sessao(api)
    modelo.side_effect = [cai(), resposta(content="Resposta inteira.")]
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "compara"}) as r:
        assert _eventos(r)[-1][0] == "erro"
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "compara"}) as r:
        assert _eventos(r)[-1][0] == "fim"
    mensagens = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert [(m["role"], m["content"]) for m in mensagens] == [("user", "compara"), ("assistant", "Resposta inteira.")]
    assert mensagens[-1]["meta"] and mensagens[-1]["meta"]["custo_usd"] == pytest.approx(0.001)


def test_turno_em_sessao_apagada_no_meio_do_caminho_e_422(api, cfg, mocker):
    """Apagar entre a checagem da rota e o registro do turno: o turno não começa numa sessão que sumiu."""
    from hermes.api import chat as chat_mod

    sid = _nova_sessao(api)
    original = chat_mod.Paradas.iniciar

    def apaga_antes(self, sessao_id):
        c = store.connect(cfg.db_path)
        with c:
            c.execute("DELETE FROM agent_sessions WHERE id = ?", (sessao_id,))
        c.close()
        return original(self, sessao_id)

    mocker.patch.object(chat_mod.Paradas, "iniciar", apaga_antes)
    r = api.post(f"/api/chat/sessoes/{sid}/turnos", json={"texto": "oi"})
    assert r.status_code == 422
    assert api.app.state.paradas.rodando(sid) is False


def test_retentar_depois_de_ferramenta_continua_o_turno_sem_repetir_a_pergunta(api, modelo):
    """O stream caiu depois de uma ferramenta: repetir não regrava a pergunta e troca o parcial pela resposta."""
    from tests.streaming import chunk

    def cai():
        yield chunk("Encontrei, ")
        raise ConnectionError("conexão caiu")

    sid = _nova_sessao(api)
    modelo.side_effect = [resposta(tool_calls=[tool_call("list_competencies")]), cai(), resposta(content="Pronto.")]
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "minhas competências"}) as r:
        assert _eventos(r)[-1][0] == "erro"
    with api.stream("POST", f"/api/chat/sessoes/{sid}/turnos", json={"texto": "minhas competências"}) as r:
        assert _eventos(r)[-1][0] == "fim"
    m = api.get(f"/api/chat/sessoes/{sid}/mensagens").json()
    assert [x["role"] for x in m] == ["user", "assistant", "tool", "assistant"]
    assert m[-1]["content"] == "Pronto." and m[-1]["meta"]["custo_usd"] is not None
