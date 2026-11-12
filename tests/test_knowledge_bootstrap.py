import hashlib
from pathlib import Path

from ai_content.domains.marketing.creative_knowledge.bootstrap import load_knowledge_bootstrap

_PRODUCT_AD = Path(__file__).parents[1] / "config/creative_knowledge/product_ad.json"


def test_manifest_loads_with_unique_ids_and_sources() -> None:
    manifest = load_knowledge_bootstrap(_PRODUCT_AD)
    assert len(manifest.items) >= 15
    assert all(item.source_refs for item in manifest.items)


def test_product_ad_rules_change_only_together_with_their_bootstrap_id() -> None:
    # A changed file under an applied id is refused, so the new rules would never load: bump the id
    manifest = load_knowledge_bootstrap(_PRODUCT_AD)
    content = hashlib.sha256(_PRODUCT_AD.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert (manifest.bootstrap_id, content) == (
        "product-ad-v4",
        "b9a322802285f41f60628491f5827a39f20dc1a81aef4d19c77cc2e1d955265e",
    )
    assert all(item.auto_approve for item in manifest.items)


async def test_curated_rules_are_approved_when_they_are_loaded(tmp_path) -> None:
    from ai_content.domains.marketing.creative_knowledge.bootstrap import (
        import_knowledge_proposals,
    )
    from ai_content.domains.marketing.creative_knowledge.models import KnowledgeStatus
    from ai_content.domains.marketing.creative_knowledge.repositories import (
        SqliteCreativeKnowledgeRepository,
    )
    from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService

    service = CreativeKnowledgeService(SqliteCreativeKnowledgeRepository(tmp_path / "k.db"))
    result = await import_knowledge_proposals(
        service, load_knowledge_bootstrap(_PRODUCT_AD), contributor="system"
    )
    assert result.applied and result.imported
    stored = await service.repository.list()
    assert {item.status for item in stored} == {KnowledgeStatus.APPROVED}
    assert {item.approved_by for item in stored} == {"system"}
