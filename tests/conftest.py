import pytest

NOTA_PROJETO = """---
type: project
id: mirante
nome: Mirante
stack: [python, sqlite]
---

# Mirante

## Fatos

- Pipeline batch diário em Python que coleta feeds RSS #python #automacao ^pipeline
- Rodou em produção de 22/06 a 16/08/2026, com N=57 logs e mediana de 39 artigos #metricas ^operacao
- Modelagem SQLite com DDL escrito à mão,
  com constraints CHECK #sql ^sql-ddl
- Suíte com 108 testes automatizados, medidos em 19/09/2026 #pytest ^testes

## Limitações

- Não roda desde agosto ^nao-indexado
"""

NOTA_EXPERIENCIA = """---
type: experience
id: acme
empresa: Acme
---

# Acme

## Fatos

"""


@pytest.fixture(autouse=True)
def _isola_do_ambiente_real(tmp_path_factory, monkeypatch):
    """O `.env` aponta para o ~/Obsidian real; teste nenhum pode escrever lá."""
    isolado = tmp_path_factory.mktemp("ambiente")
    # base própria: o `.env` real (com chave de LLM) nunca é lido durante os testes
    monkeypatch.setenv("HERMES_HOME", str(isolado / "home"))
    for chave in ("LLM_API_KEY", "LLM_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                  "OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "EMAIL_CLASSIFICADOR"):
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.setenv("VAULT_PATH", str(isolado / "vault"))
    monkeypatch.setenv("HERMES_BACKUP_DIR", str(isolado / "backups"))
    monkeypatch.setenv("HERMES_SAIDA", str(isolado / "out"))
    monkeypatch.setenv("HERMES_CURRICULOS", str(isolado / "curriculos.yaml"))
    monkeypatch.setenv("HERMES_COMPETENCIAS", str(isolado / "competencias.yaml"))


@pytest.fixture
def vault(tmp_path):
    """Vault mínimo: uma nota de projeto, uma de experiência e um template."""
    carreira = tmp_path / "Carreira"
    (carreira / "Projetos").mkdir(parents=True)
    (carreira / "Experiencias").mkdir(parents=True)
    (tmp_path / "Templates").mkdir()
    (carreira / "Projetos" / "Mirante.md").write_text(NOTA_PROJETO, encoding="utf-8")
    (carreira / "Experiencias" / "Acme.md").write_text(NOTA_EXPERIENCIA, encoding="utf-8")
    (tmp_path / "Templates" / "Projeto.md").write_text(
        "---\ntype: project\nid: modelo\n---\n\n## Fatos\n\n- fato modelo ^fato-1\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def conn(tmp_path):
    from hermes.db import store

    conexao = store.connect(tmp_path / "hermes.db")
    yield conexao
    conexao.close()


SEED_TESTE = """competencias:
  - slug: python
    nome: Python
    categoria: linguagem
    peso: 3
  - slug: sql
    nome: SQL
    categoria: dados
    peso: 2
  - slug: ingles
    nome: Inglês
    categoria: idioma
    peso: 1
"""


@pytest.fixture
def seed_yaml(tmp_path):
    caminho = tmp_path / "competencias.yaml"
    caminho.write_text(SEED_TESTE, encoding="utf-8")
    return caminho


@pytest.fixture
def banco(conn, vault, seed_yaml):
    """Banco com os fatos do vault indexados e a taxonomia semeada."""
    from hermes.db import store
    from hermes.domain import competencias
    from hermes.vault.reader import read_notes

    fatos = [
        {
            "nota": nota.nota,
            "block_id": fato.block_id,
            "tipo": nota.tipo,
            "entidade": nota.entidade,
            "texto": fato.texto,
            "tags": fato.tags,
        }
        for nota in read_notes(vault)
        for fato in nota.facts
        if fato.block_id
    ]
    store.reindex_facts(conn, fatos)
    competencias.seed(conn, seed_yaml)
    return conn


@pytest.fixture(autouse=True)
def _sem_llm_de_verdade(monkeypatch):
    """Chamada real ao modelo custa dinheiro: falha na hora. Teste que precisa do LLM simula com `mocker`."""
    import litellm

    def proibido(*args, **kwargs):
        raise RuntimeError("o teste tentou chamar um LLM de verdade; simule `litellm.completion`")

    monkeypatch.setattr(litellm, "completion", proibido)


@pytest.fixture(autouse=True)
def _stream_das_respostas_simuladas(monkeypatch):
    """`llm.chat_stream` pede `stream=True`; os mocks antigos devolvem a resposta inteira.

    Só nos testes: o `litellm` que a camada LLM enxerga passa por aqui, e uma resposta simulada sem
    streaming vira a lista de chunks que o provedor mandaria. Chunks montados pelo teste passam direto.
    """
    import litellm

    from hermes import llm
    from tests.streaming import e_resposta_sem_stream, em_chunks

    class _Litellm:
        def __getattr__(self, nome):
            return getattr(litellm, nome)

        def completion(self, *args, **kwargs):
            r = litellm.completion(*args, **kwargs)
            if kwargs.get("stream") and e_resposta_sem_stream(r):
                return iter(em_chunks(r))
            return r

    monkeypatch.setattr(llm, "_litellm", lambda: _Litellm())


@pytest.fixture
def em_sao_paulo():
    """Fuso fixo (UTC-3) para os testes de hora local não dependerem da máquina. Usa um monkeypatch só seu:
    desfazer o compartilhado desligaria antes da hora o isolamento da home (HERMES_HOME e afins)."""
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset não existe no Windows: o fuso do processo não muda pela variável TZ")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TZ", "America/Sao_Paulo")
        time.tzset()
        yield
    time.tzset()
