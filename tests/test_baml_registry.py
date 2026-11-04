from ai_content.domains.marketing.products.adapters import baml_registry


class _Registry:
    def __init__(self) -> None:
        self.clients: dict[str, tuple[str, dict]] = {}
        self.primary = ""

    def add_llm_client(self, name, provider, options) -> None:
        self.clients[name] = (provider, options)

    def set_primary(self, name) -> None:
        self.primary = name


def _build(monkeypatch, model: str) -> _Registry:
    monkeypatch.setattr(baml_registry, "ClientRegistry", _Registry)
    return baml_registry.build_client_registry(
        name="T",
        base_url="http://x/v1",
        model=model,
        api_key="k",
        reasoning_effort=None,
        temperature=0,
        max_output_tokens=100,
    )


def test_one_model_is_the_primary_client(monkeypatch) -> None:
    registry = _build(monkeypatch, "a")
    assert registry.primary == "T" and list(registry.clients) == ["T"]


def test_several_models_become_a_fallback_chain_in_order(monkeypatch) -> None:
    registry = _build(monkeypatch, "a, b")
    assert registry.primary == "TChain"
    assert registry.clients["TChain"] == ("fallback", {"strategy": ["T", "TFallback1"]})
    assert [registry.clients[n][1]["model"] for n in ("T", "TFallback1")] == ["a", "b"]
