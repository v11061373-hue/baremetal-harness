from baremetal_harness.meta.evolve import gate


def test_gate_promotes_when_converted_and_no_regression() -> None:
    decision = gate({"a": True, "b": False}, {"a": True, "b": True})
    assert decision.promote is True
    assert "b" in decision.reason


def test_gate_rejects_on_regression() -> None:
    decision = gate({"a": True, "b": False}, {"a": False, "b": True})
    assert decision.promote is False
    assert "a" in decision.reason


def test_gate_rejects_when_no_conversion() -> None:
    decision = gate({"a": True, "b": False}, {"a": True, "b": False})
    assert decision.promote is False
    assert "no failing task converted" in decision.reason
