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


def test_the_model_is_the_only_client_and_the_primary(monkeypatch) -> None:
    registry = _build(monkeypatch, "a")
    assert registry.primary == "T_a" and list(registry.clients) == ["T_a"]
    assert registry.clients["T_a"][1]["model"] == "a"


def test_there_is_no_fallback_chain(monkeypatch) -> None:
    registry = _build(monkeypatch, "a")
    assert all(provider != "fallback" for provider, _ in registry.clients.values())


def test_no_output_limit_is_sent_unless_one_is_given(monkeypatch) -> None:
    monkeypatch.setattr(baml_registry, "ClientRegistry", _Registry)
    kwargs = {"name": "T", "base_url": "http://x/v1", "model": "a", "api_key": "k"}
    open_ended = baml_registry.build_client_registry(**kwargs, reasoning_effort=None, temperature=0)
    capped = baml_registry.build_client_registry(
        **kwargs, reasoning_effort=None, temperature=0, max_output_tokens=50
    )
    assert "max_tokens" not in open_ended.clients["T_a"][1]
    assert capped.clients["T_a"][1]["max_tokens"] == 50


def test_the_client_name_carries_the_model_so_errors_name_it(monkeypatch) -> None:
    registry = _build(monkeypatch, "cc/claude-sonnet-5-5")
    assert registry.primary == "T_cc_claude-sonnet-5-5"
