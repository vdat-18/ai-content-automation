from types import SimpleNamespace

from ai_content.domains.marketing.creative.application.preparation import check_references


def test_selected_research_reference_counts_as_citable_evidence() -> None:
    context = SimpleNamespace(
        package=SimpleNamespace(evidence=(SimpleNamespace(source_id="product"),)),
        approved_claims=(),
        references=(SimpleNamespace(reference_id="research:record_a:media_b"),),
    )
    assert check_references(context, ("product", "research:record_a:media_b"), (), ()) == ()
    assert check_references(context, ("unknown",), (), ()) == ("invalid_evidence_refs",)
