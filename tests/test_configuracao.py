"""Configuração pelo app: `.env` da base, chave que nunca volta e vault de exemplo."""

import os
import stat

import pytest
from fastapi.testclient import TestClient

from hermes.api.app import criar_app
from hermes.config import load_config
from hermes.domain import configuracao
from hermes.vault.check import check_notes
from hermes.vault.reader import read_notes

TOKEN = "segredo-de-teste"


@pytest.fixture
def home(monkeypatch, tmp_path):
    """Base isolada; o que `gravar` põe no ambiente é desfeito no fim do teste."""
    base = tmp_path / "base"
    monkeypatch.setenv("HERMES_HOME", str(base))
    for chave in configuracao.EDITAVEIS:
        monkeypatch.delenv(chave, raising=False)
    return base


@pytest.fixture
def api(home, tmp_path):
    cfg = load_config(vault_path=tmp_path / "sem-vault", db_path=tmp_path / "hermes.db")
    return TestClient(criar_app(cfg, TOKEN), headers={"X-Hermes-Token": TOKEN})


def test_estado_inicial_pede_vault(api):
    estado = api.get("/api/config").json()
    assert estado["pronto"] is False and estado["configurado"] is False
    assert estado["vault"]["existe"] is False
    assert estado["llm"]["chave_definida"] is False


def test_chave_nunca_volta_e_env_fica_0600(api, home):
    estado = api.put("/api/config", json={"llm_api_key": "sk-segredo", "llm_model": "gpt-4o"}).json()

    assert "sk-segredo" not in str(estado)
    assert estado["llm"]["modelo"] == "gpt-4o" and estado["llm"]["chave_definida"] is True
    env = home / ".env"
    assert "LLM_API_KEY=sk-segredo" in env.read_text(encoding="utf-8")
    if os.name != "nt":  # no Windows o modo POSIX não existe; quem protege é a ACL da pasta do usuário
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_gravar_preserva_o_resto_do_env_e_string_vazia_apaga(api, home):
    home.mkdir()
    (home / ".env").write_text("# meu comentário\nHERMES_MAX_COST_USD=1.00\nLLM_API_KEY=velha\n",
                               encoding="utf-8")

    api.put("/api/config", json={"llm_api_key": ""})

    texto = (home / ".env").read_text(encoding="utf-8")
    assert "# meu comentário" in texto and "HERMES_MAX_COST_USD=1.00" in texto
    assert "LLM_API_KEY=\n" in texto
    assert api.get("/api/config").json()["llm"]["chave_definida"] is False


def test_vault_novo_vale_sem_reiniciar(api, tmp_path):
    destino = tmp_path / "Meu Vault"
    criados = api.post("/api/vault/exemplo", json={"caminho": str(destino)}).json()["criados"]
    estado = api.put("/api/config", json={"vault_path": str(destino)}).json()

    assert sorted(criados) == ["Carreira/Projetos/Projeto Exemplo.md", "Perfil.md"]
    assert {k: estado["vault"][k] for k in ("caminho", "existe", "notas")} == {
        "caminho": str(destino), "existe": True, "notas": 1}
    assert estado["pronto"] is True and estado["configurado"] is True


def test_vault_de_exemplo_passa_no_check_e_nao_sobrescreve(tmp_path):
    configuracao.criar_vault_exemplo(tmp_path)
    nota = tmp_path / "Carreira" / "Projetos" / "Projeto Exemplo.md"
    nota.write_text(nota.read_text(encoding="utf-8") + "\n<!-- editado -->\n", encoding="utf-8")

    assert configuracao.criar_vault_exemplo(tmp_path) == []
    assert "editado" in nota.read_text(encoding="utf-8")
    erros = [p for p in check_notes(read_notes(tmp_path)) if p.nivel == "erro"]
    assert erros == []


def test_chave_fora_da_lista_e_recusada(home):
    cfg = load_config()
    with pytest.raises(configuracao.ConfiguracaoRecusada, match="não é editável"):
        configuracao.gravar(cfg, {"HERMES_DB": "/tmp/outro.db"})
    with pytest.raises(configuracao.ConfiguracaoRecusada, match="quebra de linha"):
        configuracao.gravar(cfg, {"LLM_MODEL": "a\nLLM_API_KEY=x"})


def test_inicializar_semeia_banco_novo_uma_vez(home, tmp_path, monkeypatch):
    from hermes import caminhos
    from hermes.db import store

    monkeypatch.delenv("HERMES_COMPETENCIAS")  # o conftest aponta para fora da base
    caminhos.preparar()  # põe o competencias.yaml padrão na base
    cfg = load_config(db_path=tmp_path / "novo.db")
    conn = store.connect(cfg.db_path)
    try:
        assert configuracao.inicializar(conn, cfg) > 0
        conn.execute("UPDATE competencies SET peso = 1 WHERE slug = 'python'")
        assert configuracao.inicializar(conn, cfg) == 0  # já tem: não mexe
        assert conn.execute("SELECT peso FROM competencies WHERE slug = 'python'").fetchone()[0] == 1
    finally:
        conn.close()


def test_classificador_de_email_editavel_e_validado(api):
    estado = api.put("/api/config", json={"email_classificador": "jev"}).json()
    assert estado["triagem"]["classificador"] == "jev"
    r = api.put("/api/config", json={"email_classificador": "gpt"})
    assert r.status_code == 422 and "EMAIL_CLASSIFICADOR" in r.json()["erro"]


def test_sugestao_de_vault_nunca_e_uma_pasta_que_existe(tmp_path, monkeypatch):
    from hermes.config import load_config
    from hermes.domain import configuracao

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() no Windows
    (tmp_path / "Quilha").mkdir()
    (tmp_path / "Quilha" / "minha-nota.md").write_text("não mexa", encoding="utf-8")
    cfg = load_config(vault_path=tmp_path / "nenhum")
    assert configuracao.estado(cfg)["vault"]["sugestao"] == str(tmp_path / "Quilha 2")
    (tmp_path / "Quilha 2").mkdir()
    assert configuracao.estado(cfg)["vault"]["sugestao"] == str(tmp_path / "Quilha 3")
    assert (tmp_path / "Quilha" / "minha-nota.md").read_text(encoding="utf-8") == "não mexa"


def test_limite_de_custo_aceita_virgula_e_vale_sem_reiniciar(api, home):
    r = api.put("/api/config", json={"hermes_max_cost_usd": "1,5"})
    assert r.status_code == 200
    assert r.json()["llm"]["limite_usd"] == 1.5
    assert "HERMES_MAX_COST_USD=1.5" in (home / ".env").read_text(encoding="utf-8")
    assert api.app.state.cfg.max_cost_usd == 1.5


@pytest.mark.parametrize("valor", ["abc", "0", "-1", "101"])
def test_limite_de_custo_invalido_e_recusado_sem_gravar(api, home, valor):
    r = api.put("/api/config", json={"hermes_max_cost_usd": valor})
    assert r.status_code == 422
    env = home / ".env"
    assert "HERMES_MAX_COST_USD" not in (env.read_text(encoding="utf-8") if env.exists() else "")


@pytest.mark.parametrize("valor,ok", [("30", True), ("365", True), ("0", False), ("400", False), ("dez", False)])
def test_dias_de_email_validados(api, valor, ok):
    r = api.put("/api/config", json={"email_dias": valor})
    assert (r.status_code == 200) == ok
    if ok:
        assert r.json()["email"]["dias"] == int(valor)


def test_estado_traz_pastas_versao_e_ultima_copia(api, home):
    e = api.get("/api/config").json()
    assert e["pastas"]["base"] == str(home)
    assert e["pastas"]["ultima_copia"] is None
    assert e["app"]["sistema"] and e["app"]["versao"]
    assert e["email"]["dias"] == 30
    assert api.post("/api/operacao/backup").status_code == 200
    assert api.get("/api/config").json()["pastas"]["ultima_copia"] is not None


def _recusa_a_chave(mocker):
    import litellm
    erro = type("AuthenticationError", (Exception,), {"__module__": "litellm.exceptions"})
    mocker.patch.object(litellm, "completion", side_effect=erro("invalid api key"))


def _tipos_de_problema(api) -> list[str]:
    return [p["tipo"] for p in api.get("/api/config/saude").json()["problemas"]]


def test_testar_chave_ok_limpa_a_recusa(api, mocker):
    import litellm
    from hermes.db import store
    from tests.test_llm import resposta
    mocker.patch.object(litellm, "completion", return_value=resposta("ok"))
    mocker.patch.object(litellm, "completion_cost", return_value=0.00001)
    conn = store.connect(api.app.state.cfg.db_path)
    configuracao.marcar_recusa(conn, "2026-10-10T12:00:00+00:00")
    conn.close()
    assert "llm_recusada" in _tipos_de_problema(api)
    r = api.post("/api/config/llm/testar").json()
    assert r["ok"] is True and r["modelo"] and r["ms"] >= 0
    assert "llm_recusada" not in _tipos_de_problema(api)


def test_chave_recusada_acende_e_trocar_a_chave_apaga(api, mocker):
    api.put("/api/config", json={"llm_model": "gpt-4o-mini", "llm_api_key": "sk-velha"})
    _recusa_a_chave(mocker)
    r = api.post("/api/config/llm/testar").json()
    assert r["ok"] is False and "recusou a chave" in r["mensagem"]
    assert "llm_recusada" in _tipos_de_problema(api)
    api.put("/api/config", json={"llm_api_key": "sk-nova"})
    assert "llm_recusada" not in _tipos_de_problema(api)


def test_recusa_em_outra_rota_tambem_acende(api, mocker):
    """Review Focus 4: a recusa vem do chat ou do currículo, não só do botão de teste."""
    from hermes.llm import FalhaLLM

    @api.app.post("/api/teste/falha-cru")
    def _cru():
        raise FalhaLLM("o provedor do LLM recusou a chave; confira em Configurações → LLM (x)")

    r = api.post("/api/teste/falha-cru")
    assert r.status_code == 502 and r.json()["codigo"] == "llm"
    assert "llm_recusada" in _tipos_de_problema(api)


def test_salvar_e_testar_recusa_chave_vazia(api):
    """Review Focus 1: o botão nunca apaga a chave; para apagar, só o .env."""
    api.put("/api/config", json={"llm_api_key": "sk-x"})
    r = api.post("/api/config/llm/salvar-e-testar", json={"llm_api_key": ""})
    assert r.status_code == 422
    assert api.get("/api/config").json()["llm"]["chave_definida"] is True


def test_salvar_e_testar_grava_e_testa(api, mocker):
    _recusa_a_chave(mocker)
    r = api.post("/api/config/llm/salvar-e-testar", json={"llm_api_key": "sk-nova"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["estado"]["llm"]["chave_definida"] is True
    assert corpo["teste"]["ok"] is False


@pytest.mark.parametrize("campo,chave", [("hermes_max_cost_usd", "limite_usd"), ("email_dias", None)])
def test_limite_e_dias_vazios_sao_recusados_e_nao_apagam(api, home, campo, chave):
    """Revisão final: apagar o campo não pode tirar o limite em silêncio."""
    api.put("/api/config", json={"hermes_max_cost_usd": "1,5", "email_dias": "60"})
    r = api.put("/api/config", json={campo: ""})
    assert r.status_code == 422
    env = (home / ".env").read_text(encoding="utf-8")
    assert "HERMES_MAX_COST_USD=1.5" in env and "EMAIL_DIAS=60" in env


def test_email_dias_invalido_no_env_nao_derruba_a_config(api, monkeypatch):
    """Revisão final: um .env editado à mão com EMAIL_DIAS=abc não pode quebrar o app."""
    monkeypatch.setenv("EMAIL_DIAS", "abc")
    r = api.get("/api/config")
    assert r.status_code == 200 and r.json()["email"]["dias"] == 30


def test_recusa_nos_avisos_da_triagem_acende(api):
    """Revisão final: a triagem transforma a falha do LLM em aviso; a recusa precisa acender mesmo assim."""
    from hermes.db import store
    conn = store.connect(api.app.state.cfg.db_path)
    configuracao.lembrar_recusa_nos_avisos(conn, ["e-mail 1: o provedor do LLM recusou a chave; confira (x)"])
    conn.close()
    assert "llm_recusada" in _tipos_de_problema(api)


def test_estado_classificador_normalizado(api, monkeypatch):
    monkeypatch.setenv("EMAIL_CLASSIFICADOR", " Jev ")
    assert api.get("/api/config").json()["triagem"]["classificador"] == "jev"


def test_jev_salvar_e_testar_liga_quando_passa(api, home, monkeypatch):
    from hermes.domain import triagem_email
    chaves = []
    monkeypatch.setattr(triagem_email, "testar_jev",
                        lambda cliente=None, chave=None: chaves.append(chave) or {"ok": True, "ms": 12})
    r = api.post("/api/config/jev/salvar-e-testar", json={"typesafe_api_key": " tsk_boa "}).json()
    assert chaves == ["tsk_boa"]
    assert r["teste"]["ok"] and r["estado"]["triagem"] == {"classificador": "jev", "jev_chave_definida": True}
    assert "TYPESAFE_API_KEY=tsk_boa" in (home / ".env").read_text(encoding="utf-8")


def test_jev_salvar_e_testar_recusa_nao_liga(api, home, monkeypatch):
    from hermes.domain import triagem_email
    monkeypatch.setattr(triagem_email, "testar_jev",
                        lambda cliente=None, chave=None: {"ok": False, "mensagem": "o Jev recusou a chave"})
    r = api.post("/api/config/jev/salvar-e-testar", json={"typesafe_api_key": "tsk_ruim"}).json()
    assert r["teste"] == {"ok": False, "mensagem": "o Jev recusou a chave"}
    assert r["estado"]["triagem"] == {"classificador": "llm", "jev_chave_definida": False}
    assert "tsk_ruim" not in ((home / ".env").read_text(encoding="utf-8") if (home / ".env").exists() else "")


def test_jev_salvar_e_testar_sem_chave_e_recusado(api):
    r = api.post("/api/config/jev/salvar-e-testar", json={"typesafe_api_key": "  "})
    assert r.status_code == 422


def test_jev_testar_usa_a_chave_salva(api, monkeypatch):
    from hermes.domain import triagem_email
    monkeypatch.setattr(triagem_email, "testar_jev", lambda cliente=None, chave=None: {"ok": True, "ms": 7})
    assert api.post("/api/config/jev/testar").json() == {"ok": True, "ms": 7}


class _JevFalso:
    def __init__(self, erro=None):
        self.erro = erro
        self.estados = []

    def system_one(self, state, questions):
        self.estados.append(state)
        if self.erro:
            raise self.erro
        from types import SimpleNamespace as N
        return N(choices={"categoria": N(choice="outro", probabilities={"outro": 0.9})},
                 nouls={"e_processo": N(noul=0.1), "tem_prazo": N(noul=0.0)})


def test_testar_jev_ok_classifica_um_email_de_teste():
    from hermes.domain import triagem_email
    jev = _JevFalso()
    r = triagem_email.testar_jev(jev)
    assert r["ok"] is True and isinstance(r["ms"], int)
    assert jev.estados and "Quilha" in jev.estados[0]["from"]


def test_testar_jev_traduz_erro_de_autenticacao():
    import httpx2
    from typesafe_sdk import TypeSafeAuthenticationError
    from hermes.domain import triagem_email
    r = triagem_email.testar_jev(_JevFalso(TypeSafeAuthenticationError(401, {}, httpx2.Headers())))
    assert r == {"ok": False, "mensagem": "o Jev recusou a chave"}


def test_testar_jev_outro_erro_vira_mensagem():
    from typesafe_sdk import TypeSafeError
    from hermes.domain import triagem_email
    r = triagem_email.testar_jev(_JevFalso(TypeSafeError("sem crédito")))
    assert r == {"ok": False, "mensagem": "o Jev recusou: sem crédito"}


def test_vault_de_exemplo_pela_api_recusa_pasta_com_arquivos(api, tmp_path):
    cheia = tmp_path / "minhas-notas"
    cheia.mkdir()
    (cheia / "diario.md").write_text("pessoal", encoding="utf-8")
    r = api.post("/api/vault/exemplo", json={"caminho": str(cheia)})
    assert r.status_code == 422 and "já tem arquivos" in r.json()["erro"]
    assert sorted(p.name for p in cheia.iterdir()) == ["diario.md"]
    vazia = tmp_path / "nova"
    assert api.post("/api/vault/exemplo", json={"caminho": str(vazia)}).status_code == 200
