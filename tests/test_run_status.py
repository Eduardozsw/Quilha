from hermes.run_status import RunStatus, final_status


def test_custo_soma_quando_conhecido():
    status = RunStatus()
    status.record_usage(10, 5, 0.001)
    status.record_usage(20, 5, 0.002)
    assert status.llm_calls == 2
    assert status.cost_usd == 0.003


def test_custo_nulo_contamina_o_total():
    status = RunStatus()
    status.record_usage(10, 5, 0.001)
    status.record_usage(10, 5, None)
    assert status.cost_usd is None


def test_status_final():
    limpo = RunStatus()
    assert final_status(limpo, crashed=False, delivered=True) == "success"
    assert final_status(limpo, crashed=True, delivered=True) == "failed"
    assert final_status(limpo, crashed=False, delivered=False) == "failed"

    com_aviso = RunStatus()
    com_aviso.add("feed fora do ar")
    assert final_status(com_aviso, crashed=False, delivered=True) == "partial"

    com_erro_de_tool = RunStatus()
    com_erro_de_tool.tool_errors = 1
    assert final_status(com_erro_de_tool, crashed=False, delivered=True) == "partial"
