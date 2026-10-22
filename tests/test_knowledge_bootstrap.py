from pathlib import Path

from ai_content.domains.marketing.creative_knowledge.bootstrap import load_knowledge_bootstrap

_MANIFEST = Path(__file__).parents[1] / "config/creative_knowledge/creative_v3_2026_10_22.json"
_BRANDS = {"brand:aurasleep", "brand:oaklinehome", "brand:lumiskin"}


def test_manifest_loads_with_unique_ids_and_sources() -> None:
    manifest = load_knowledge_bootstrap(_MANIFEST)
    assert len(manifest.items) >= 50
    assert all(item.source_refs for item in manifest.items)


def test_each_demo_brand_has_voice_look_depiction_and_claims_rules() -> None:
    manifest = load_knowledge_bootstrap(_MANIFEST)
    for brand in _BRANDS:
        scoped = [item for item in manifest.items if item.scope.brand_id == brand]
        assert len(scoped) >= 4, brand
