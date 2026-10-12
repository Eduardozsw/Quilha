"""A camada LLM, com o LiteLLM mockado. Nenhum teste aqui toca a rede ou gasta crédito."""

from types import SimpleNamespace

import pytest

from hermes import llm
from hermes.run_status import RunStatus


def resposta(content="ok", tool_calls=None, prompt=10, completion=5):
    mensagem = SimpleNamespace(content=content, tool_calls=tool_calls, role="assistant")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=mensagem)],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


@pytest.fixture
def fake_litellm(mocker):
    import litellm

    mocker.patch.object(litellm, "completion", return_value=resposta())
    mocker.patch.object(litellm, "completion_cost", return_value=0.0012)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["response_format"])
    return litellm


def test_chat_devolve_a_mensagem_crua(fake_litellm):
    msg = llm.chat([{"role": "user", "content": "oi"}])
    assert msg.content == "ok"


def test_tools_viram_tool_choice_auto(fake_litellm):
    esquema = [{"type": "function", "function": {"name": "list_competencies"}}]
    llm.chat([{"role": "user", "content": "oi"}], tools=esquema)
    kwargs = fake_litellm.completion.call_args.kwargs
    assert kwargs["tools"] == esquema
    assert kwargs["tool_choice"] == "auto"


def test_sem_tools_nao_manda_tool_choice(fake_litellm):
    llm.chat([{"role": "user", "content": "oi"}])
    assert "tool_choice" not in fake_litellm.completion.call_args.kwargs


def test_uso_e_custo_somam_no_run_status(fake_litellm):
    status = RunStatus()
    llm.chat([{"role": "user", "content": "oi"}], status=status)
    llm.chat([{"role": "user", "content": "de novo"}], status=status)
    assert status.llm_calls == 2
    assert status.prompt_tokens == 20
    assert status.completion_tokens == 10
    assert status.cost_usd == pytest.approx(0.0024)


def test_modelo_sem_preco_deixa_o_custo_desconhecido_e_nao_quebra(fake_litellm, mocker):
    mocker.patch.object(fake_litellm, "completion_cost", side_effect=Exception("sem preço"))
    status = RunStatus()
    llm.chat([{"role": "user", "content": "oi"}], status=status)
    assert status.prompt_tokens == 10  # os tokens continuam contados
    assert status.cost_unknown is True
    assert status.cost_usd is None  # nunca 0: desconhecido não é de graça


def test_json_mode_so_vai_para_provedor_que_aceita(fake_litellm, mocker):
    llm.chat([{"role": "user", "content": "oi"}], json_mode=True)
    assert fake_litellm.completion.call_args.kwargs["response_format"] == {"type": "json_object"}

    mocker.patch.object(fake_litellm, "get_supported_openai_params", return_value=["temperature"])
    llm.chat([{"role": "user", "content": "oi"}], json_mode=True)
    assert "response_format" not in fake_litellm.completion.call_args.kwargs


def test_provedor_desconhecido_nao_derruba_a_chamada(fake_litellm, mocker):
    mocker.patch.object(
        fake_litellm, "get_supported_openai_params", side_effect=Exception("modelo estranho")
    )
    llm.chat([{"role": "user", "content": "oi"}], json_mode=True)
    assert "response_format" not in fake_litellm.completion.call_args.kwargs


def test_complete_recusa_conteudo_vazio(fake_litellm, mocker):
    mocker.patch.object(fake_litellm, "completion", return_value=resposta(content=None))
    with pytest.raises(ValueError, match="vazio"):
        llm.complete("system", "user")


def test_env_controla_modelo_retries_e_timeout(fake_litellm, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("LLM_NUM_RETRIES", "7")
    monkeypatch.setenv("LLM_TIMEOUT", "12.5")
    llm.chat([{"role": "user", "content": "oi"}])
    kwargs = fake_litellm.completion.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["num_retries"] == 7
    assert kwargs["timeout"] == 12.5


def test_teto_de_custo_aborta_antes_da_proxima_chamada():
    status = RunStatus()
    status.record_usage(100, 50, 0.49)
    llm.check_cost_limit(status, 0.50)  # ainda cabe
    status.record_usage(100, 50, 0.02)
    with pytest.raises(llm.CostLimitError, match="teto de custo"):
        llm.check_cost_limit(status, 0.50)


def test_custo_desconhecido_nao_aborta_a_sessao():
    """Travar aqui seria impedir modelo local, que nunca tem preço na tabela."""
    status = RunStatus()
    status.record_usage(100, 50, None)
    llm.check_cost_limit(status, 0.50)


def test_dependencias_de_runtime_do_litellm_estao_instaladas():
    """O litellm 1.102 importa `tenacity` em runtime para aplicar `num_retries`, mas não a
    declara como dependência. Como os outros testes mockam `litellm.completion`, esse caminho
    nunca roda aqui — sem esta verificação, a falta só aparece na primeira conversa de verdade.
    """
    import tenacity  # noqa: F401

    import litellm

    assert callable(litellm.completion)


# --- streaming (V3) -----------------------------------------------------------------

import threading

from tests.streaming import chunk, delta_tool, uso


@pytest.fixture
def stream(mocker):
    """`litellm.completion` devolvendo chunks montados à mão; `stream_chunk_builder` é o real."""
    import litellm

    mock = mocker.patch.object(litellm, "completion")
    mocker.patch.object(litellm, "completion_cost", return_value=0.003)
    mocker.patch.object(litellm, "get_supported_openai_params", return_value=["stream_options"])
    return mock


def test_chat_stream_entrega_os_trechos_e_monta_a_mensagem(stream):
    stream.return_value = iter([chunk("Olá, "), chunk("tudo "), chunk("bem?", finish="stop"),
                                chunk(usage=uso(12, 3))])
    trechos, status = [], RunStatus()
    msg = llm.chat_stream([{"role": "user", "content": "oi"}], status=status, on_trecho=trechos.append)

    assert trechos == ["Olá, ", "tudo ", "bem?"]
    assert msg.content == "Olá, tudo bem?" and not msg.tool_calls
    assert (status.prompt_tokens, status.completion_tokens) == (12, 3)
    assert status.cost_usd == pytest.approx(0.003)
    kwargs = stream.call_args.kwargs
    assert kwargs["stream"] is True and kwargs["stream_options"] == {"include_usage": True}


def test_chat_stream_junta_a_tool_call_picada(stream):
    """Review Focus 2: nome no primeiro chunk, argumentos em dois, texto antes da ferramenta."""
    stream.return_value = iter([
        chunk("Vou olhar. "),
        chunk(tool_calls=[delta_tool(0, "call_9", "list_jobs", "")]),
        chunk(tool_calls=[delta_tool(0, argumentos='{"status": ')]),
        chunk(tool_calls=[delta_tool(0, argumentos='"abertas"}')], finish="tool_calls"),
        chunk(usage=uso()),
    ])
    trechos = []
    msg = llm.chat_stream([{"role": "user", "content": "vagas?"}], tools=[{"type": "function"}],
                          on_trecho=trechos.append)
    assert trechos == ["Vou olhar. "]
    assert msg.content == "Vou olhar. "
    (chamada,) = msg.tool_calls
    assert (chamada.id, chamada.function.name, chamada.function.arguments) == (
        "call_9", "list_jobs", '{"status": "abertas"}')


def test_chat_stream_sem_usage_deixa_o_custo_desconhecido(stream):
    """Review Focus 3: sem `usage` o LiteLLM estima tokens; o custo fica desconhecido, nunca 0."""
    stream.return_value = iter([chunk("oi", finish="stop")])
    status = RunStatus()
    msg = llm.chat_stream([{"role": "user", "content": "oi"}], status=status)
    assert msg.content == "oi"
    assert status.llm_calls == 1 and status.cost_usd is None


def test_chat_stream_sem_suporte_a_stream_options_nao_manda(stream, mocker):
    import litellm

    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    stream.return_value = iter([chunk("oi", finish="stop")])
    llm.chat_stream([{"role": "user", "content": "oi"}])
    assert "stream_options" not in stream.call_args.kwargs


def test_chat_stream_parado_no_meio_levanta_com_o_parcial(stream):
    parar = threading.Event()
    lidos = []

    def chunks():
        yield chunk("Olhando as vagas, ")
        lidos.append(1)
        parar.set()
        yield chunk("a da Orla ")
        lidos.append(2)
        yield chunk("é a melhor.", finish="stop")

    stream.return_value = chunks()
    trechos = []
    with pytest.raises(llm.Parado) as exc:
        llm.chat_stream([{"role": "user", "content": "oi"}], on_trecho=trechos.append, parar=parar)
    assert exc.value.parcial == "Olhando as vagas, "
    assert trechos == ["Olhando as vagas, "]
    assert lidos == [1]  # parou de ler


def test_parado_no_meio_registra_os_tokens_com_custo_estimado(stream, mocker):
    """O provedor cobra a chamada interrompida: os tokens e o custo estimado entram na conta, nunca 0."""
    import litellm

    mocker.patch.object(litellm, "cost_per_token", return_value=(0.0001, 0.0002))
    parar = threading.Event()

    def chunks():
        yield chunk("Olhando as vagas, ")
        parar.set()
        yield chunk("a da Orla ")

    stream.return_value = chunks()
    status = RunStatus()
    with pytest.raises(llm.Parado):
        llm.chat_stream([{"role": "user", "content": "compara as vagas abertas"}], status=status, parar=parar)
    assert status.llm_calls == 1 and status.prompt_tokens > 0
    assert status.cost_usd == pytest.approx(0.0003)  # estimado pela tabela, nunca some do total


def test_parado_nao_apaga_o_custo_ja_conhecido_do_turno(stream, mocker):
    """Uma ferramenta com custo conhecido e depois o "Parar": o total do turno continua com o que já foi gasto."""
    import litellm

    mocker.patch.object(litellm, "cost_per_token", return_value=(0.0001, 0.0002))
    parar = threading.Event()

    def chunks():
        yield chunk("Olhando")
        parar.set()
        yield chunk(" mais")

    stream.return_value = chunks()
    status = RunStatus()
    status.record_usage(100, 20, 0.004)  # a chamada anterior do turno, com preço conhecido
    with pytest.raises(llm.Parado):
        llm.chat_stream([{"role": "user", "content": "oi"}], status=status, parar=parar)
    assert status.cost_usd == pytest.approx(0.004 + 0.0003)


def test_parado_sem_preco_conhecido_fica_desconhecido(stream, mocker):
    """Modelo fora da tabela de preços (local, por exemplo): o custo fica desconhecido, nunca inventado."""
    import litellm

    mocker.patch.object(litellm, "cost_per_token", side_effect=ValueError("modelo sem preço"))
    parar = threading.Event()
    parar.set()
    stream.return_value = iter([chunk("x")])
    status = RunStatus()
    with pytest.raises(llm.Parado):
        llm.chat_stream([{"role": "user", "content": "oi"}], status=status, parar=parar)
    assert status.llm_calls == 1 and status.cost_usd is None


def test_parado_antes_do_primeiro_trecho_tambem_conta(stream, mocker):
    import litellm

    mocker.patch.object(litellm, "cost_per_token", return_value=(0.0001, 0.0))
    parar = threading.Event()
    parar.set()
    stream.return_value = iter([chunk("nunca lido")])
    status = RunStatus()
    with pytest.raises(llm.Parado):
        llm.chat_stream([{"role": "user", "content": "oi, tudo bem?"}], status=status, parar=parar)
    assert status.llm_calls == 1 and status.prompt_tokens > 0 and status.cost_usd == pytest.approx(0.0001)


def test_chat_stream_erro_do_provedor_no_meio_vira_falha_llm(stream):
    erro = type("APIConnectionError", (Exception,), {"__module__": "litellm.exceptions"})

    def chunks():
        yield chunk("começo")
        raise erro("caiu")

    stream.return_value = chunks()
    with pytest.raises(llm.FalhaLLM):
        llm.chat_stream([{"role": "user", "content": "oi"}])


class _WrapperDoLitellm:
    """Como o `CustomStreamWrapper` sem `stream_options` (Anthropic, Gemini): entrega os chunks sem `usage`
    e guarda os originais, com o `usage` do provedor, em `.chunks`."""

    def __init__(self, originais):
        self.chunks = []
        self._originais = originais

    def __iter__(self):
        for c in self._originais:
            self.chunks.append(c)
            if getattr(c, "usage", None) is not None:
                continue  # o chunk só de usage não chega a quem chama
            yield c


def test_chat_stream_usa_o_usage_que_o_wrapper_guardou(stream, mocker):
    """Revisão final (C1): sem `stream_options` o custo não pode virar desconhecido se o provedor mandou tokens."""
    import litellm

    mocker.patch.object(litellm, "get_supported_openai_params", return_value=[])
    stream.return_value = _WrapperDoLitellm([chunk("Olá"), chunk(" mundo", finish="stop"), chunk(usage=uso(1000, 50))])
    status, trechos = RunStatus(), []
    msg = llm.chat_stream([{"role": "user", "content": "oi"}], status=status, on_trecho=trechos.append)
    assert msg.content == "Olá mundo" and trechos == ["Olá", " mundo"]
    assert (status.prompt_tokens, status.completion_tokens) == (1000, 50)
    assert status.cost_usd == pytest.approx(0.003)


def test_recusa_do_provedor_nao_mostra_a_chave(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-proj-abcdef1234567890")

    class AuthenticationError(Exception):
        pass

    e = AuthenticationError("Incorrect API key provided: sk-proj-abcdef1234567890. You can find your key at ...")
    msg = str(llm._falha_do_provedor(e))
    assert "abcdef1234567890" not in msg and "***" in msg
    assert msg.startswith("o provedor do LLM recusou a chave")


def test_chave_sem_prefixo_conhecido_tambem_some(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "q8Zt3kLmN0pQrStUvWx")

    class AuthenticationError(Exception):
        pass

    assert "q8Zt3kLmN0pQrStUvWx" not in str(llm._falha_do_provedor(AuthenticationError("bad key q8Zt3kLmN0pQrStUvWx")))


def test_eco_parcial_com_asteriscos_tambem_some():
    assert "AbCd" not in llm.mascarar_chaves("Incorrect API key provided: sk-proj-****AbCd")


def test_texto_sem_chave_fica_igual():
    assert llm.mascarar_chaves("Rate limit reached for gpt-4o-mini") == "Rate limit reached for gpt-4o-mini"


@pytest.mark.parametrize("texto", ["pkg_resources", "skeleton", "skipping", "sk-learn", "use sk-learn e pandas",
                                   "xai-grok-beta", "rk_tarefa"])
def test_mascara_nao_pega_palavras_comuns(texto):
    assert llm.mascarar_chaves(texto) == texto


@pytest.mark.parametrize("chave", ["sk-proj-abcdefghij1234567890", "sk-ant-api03-AbCdEf123456", "gsk_8f7a6b5c4d3e2f1a",
                                   "AIzaSyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv", "xai-AbCd1234EfGh5678"])
def test_mascara_pega_chave(chave):
    assert chave not in llm.mascarar_chaves(f"chave {chave} recusada")
