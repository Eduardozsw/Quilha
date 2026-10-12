"""Saúde do app para a linha de status de Configurações: o problema mais grave primeiro."""

import pytest

from hermes.config import load_config
from hermes.db import store
from hermes.domain import configuracao, saude
from hermes.run_status import RunStatus


@pytest.fixture
def ambiente(monkeypatch, tmp_path):
    base = tmp_path / "base"
    monkeypatch.setenv("HERMES_HOME", str(base))
    for chave in configuracao.EDITAVEIS:
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "sk-teste")
    return monkeypatch


@pytest.fixture
def conn(ambiente, tmp_path):
    c = store.connect(tmp_path / "hermes.db")
    yield c
    c.close()


def _cfg(tmp_path):
    return load_config(vault_path=tmp_path / "sem-vault", db_path=tmp_path / "hermes.db")


def _tipos(conn, tmp_path):
    return [p["tipo"] for p in saude.problemas(conn, _cfg(tmp_path))]


def test_tudo_certo_nao_tem_problema(conn, tmp_path):
    assert saude.problemas(conn, _cfg(tmp_path)) == []


def test_sem_chave_falta_o_llm(conn, ambiente, tmp_path):
    ambiente.delenv("LLM_API_KEY")
    p = saude.problemas(conn, _cfg(tmp_path))
    assert p[0] == {"tipo": "llm_falta", "texto": "Falta configurar o LLM", "secao": "llm", "grave": True}


def test_modelo_local_nao_precisa_de_chave(conn, ambiente, tmp_path):
    ambiente.delenv("LLM_API_KEY")
    ambiente.setenv("LLM_MODEL", "ollama/llama3.1")
    assert "llm_falta" not in _tipos(conn, tmp_path)


def test_imap_com_usuario_e_sem_senha_esta_desconectado(conn, ambiente, tmp_path):
    ambiente.setenv("EMAIL_ORIGEM", "imap")
    ambiente.setenv("IMAP_USUARIO", "ana@exemplo.dev")
    assert _tipos(conn, tmp_path) == ["email_desconectado"]


def test_gmail_por_oauth_nao_acusa_email(conn, ambiente, tmp_path):
    """Review Focus 5: quem usa o OAuth próprio não está desconectado."""
    cfg = _cfg(tmp_path)
    (cfg.gmail_dir).mkdir(parents=True)
    (cfg.gmail_dir / "credentials.json").write_text("{}")
    ambiente.setenv("EMAIL_ORIGEM", "gmail")
    assert saude.problemas(conn, cfg) == []


def test_email_nunca_configurado_nao_e_problema(conn, tmp_path):
    assert not [t for t in _tipos(conn, tmp_path) if t.startswith("email")]


def test_ultima_busca_de_email_que_falhou(conn, tmp_path):
    store.record_run(conn, "email sync", "2026-10-10T08:00:00+00:00", RunStatus(), "success")
    store.record_run(conn, "email sync", "2026-10-10T09:00:00+00:00", RunStatus(), "failed", error="login")
    assert _tipos(conn, tmp_path) == ["email_falhou"]
    store.record_run(conn, "email sync", "2026-10-10T10:00:00+00:00", RunStatus(), "success")
    assert _tipos(conn, tmp_path) == []


def _fontes(tmp_path, *pares):
    """`fontes.yaml` com as fontes dadas: a saúde só conta erro de fonte que ainda está nele."""
    caminho = _cfg(tmp_path).fontes_path
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("fontes:\n" + "".join(f"  - {{tipo: {t}, board: {b}, empresa: {b.title()}}}\n" for t, b in pares),
                       encoding="utf-8")


def test_fontes_com_erro_contadas_no_plural(conn, tmp_path):
    _fontes(tmp_path, ("gupy", "orla"), ("gupy", "mare"))
    for board in ("orla", "mare"):
        conn.execute("INSERT INTO fila_coleta (fonte, board, estado, tentativas, proximo_em, ultimo_erro, atualizado_em)"
                     " VALUES ('gupy', ?, 'falhou', 3, '2026-10-10T13:00:00+00:00', '404', '2026-10-10T10:00:00+00:00')",
                     (board,))
    conn.commit()
    p = saude.problemas(conn, _cfg(tmp_path))
    assert p == [{"tipo": "fontes_erro", "texto": "2 fontes de vagas com erro", "secao": "coleta", "grave": False}]


def test_ordem_de_gravidade(conn, ambiente, tmp_path, mocker):
    ambiente.delenv("LLM_API_KEY")
    mocker.patch.object(saude, "avisos_do_vault", return_value=["a"])
    (tmp_path / "sem-vault").mkdir()
    _fontes(tmp_path, ("lever", "vela"))
    conn.execute("INSERT INTO fila_coleta (fonte, board, estado, tentativas, proximo_em, atualizado_em)"
                 " VALUES ('lever', 'vela', 'falhou', 1, '2026-10-10T13:00:00+00:00', '2026-10-10T10:00:00+00:00')")
    conn.commit()
    configuracao.marcar_recusa(conn, "2026-10-10T10:00:00+00:00")
    p = saude.problemas(conn, _cfg(tmp_path))
    assert [x["tipo"] for x in p] == ["llm_falta", "llm_recusada", "fontes_erro", "vault_avisos"]
    assert p[-1]["texto"] == "1 aviso no vault" and p[-1]["secao"] == "diagnostico"


def test_rota_traz_problemas_e_quando_indexou(conn, tmp_path):
    from fastapi.testclient import TestClient

    from hermes.api.app import criar_app
    api = TestClient(criar_app(_cfg(tmp_path), "t"), headers={"X-Hermes-Token": "t"})
    r = api.get("/api/config/saude").json()
    assert r == {"problemas": [], "indexado_em": None}


def test_fonte_que_saiu_do_fontes_yaml_nao_conta(conn, tmp_path):
    _fontes(tmp_path, ("gupy", "orla"))
    for board in ("orla", "removida"):
        conn.execute("INSERT INTO fila_coleta (fonte, board, estado, tentativas, proximo_em, ultimo_erro, atualizado_em)"
                     " VALUES ('gupy', ?, 'falhou', 3, '2026-10-10T13:00:00+00:00', '404', '2026-10-10T10:00:00+00:00')",
                     (board,))
    conn.commit()
    [p] = saude.problemas(conn, _cfg(tmp_path))
    assert p["texto"] == "1 fonte de vagas com erro"


def test_avisos_do_vault_so_releem_as_notas_quando_algo_muda(conn, tmp_path, monkeypatch):
    import os

    from hermes.domain import configuracao as conf
    vault = tmp_path / "vault"
    conf.criar_vault_exemplo(vault)
    cfg = load_config(vault_path=vault, db_path=tmp_path / "hermes.db")
    leituras = []
    original = saude.read_notes
    monkeypatch.setattr(saude, "read_notes", lambda v: leituras.append(1) or original(v))
    saude.avisos_do_vault(conn, cfg)
    saude.avisos_do_vault(conn, cfg)
    assert len(leituras) == 1
    nota = next((vault / "Carreira").rglob("*.md"))
    os.utime(nota, (nota.stat().st_atime, nota.stat().st_mtime + 5))
    saude.avisos_do_vault(conn, cfg)
    assert len(leituras) == 2


def test_avisos_do_vault_aguentam_pedidos_simultaneos_e_nota_que_some(conn, tmp_path, monkeypatch):
    """Duas leituras da saúde ao mesmo tempo, com o vault mudando no meio, e uma nota apagada durante a
    varredura: nada de KeyError nem FileNotFoundError (a tela pede a saúde a cada campo salvo)."""
    import threading

    from hermes.domain import configuracao as conf
    vault = tmp_path / "vault"
    conf.criar_vault_exemplo(vault)
    cfg = load_config(vault_path=vault, db_path=tmp_path / "hermes.db")
    nota = next((vault / "Carreira").rglob("*.md"))
    erros = []

    def ler(n):
        c = store.connect(tmp_path / "hermes.db")
        try:
            for i in range(30):
                if n == 0:
                    (vault / "Carreira" / f"extra-{i}.md").write_text("# x\n", encoding="utf-8")
                saude.avisos_do_vault(c, cfg)
        except Exception as exc:  # noqa: BLE001
            erros.append(repr(exc))
        finally:
            c.close()
    threads = [threading.Thread(target=ler, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert erros == []

    original = type(nota).stat
    def some(self, *a, **k):
        if self.name == nota.name:
            raise FileNotFoundError(self)
        return original(self, *a, **k)
    monkeypatch.setattr(type(nota), "stat", some)
    saude._assinatura(cfg)  # a nota apagada no meio da varredura não derruba
