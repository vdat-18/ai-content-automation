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
        "product-ad-v8",
        "78ddb7ed60131495e8ed0ccee22e6975e709ad26427a8dc174084efef8e63784",
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


async def test_a_reworded_curated_rule_stays_approved(tmp_path) -> None:
    import json

    from ai_content.domains.marketing.creative_knowledge.bootstrap import (
        import_knowledge_proposals,
    )
    from ai_content.domains.marketing.creative_knowledge.models import KnowledgeStatus
    from ai_content.domains.marketing.creative_knowledge.repositories import (
        SqliteCreativeKnowledgeRepository,
    )
    from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService

    service = CreativeKnowledgeService(SqliteCreativeKnowledgeRepository(tmp_path / "k.db"))
    first = tmp_path / "v1.json"
    manifest = json.loads(_PRODUCT_AD.read_text(encoding="utf-8"))
    manifest["items"] = manifest["items"][:1]
    first.write_text(json.dumps(manifest), encoding="utf-8")
    await import_knowledge_proposals(service, load_knowledge_bootstrap(first), contributor="system")

    manifest["bootstrap_id"] = "next"
    manifest["items"][0]["content"] += " Reworded."
    second = tmp_path / "v2.json"
    second.write_text(json.dumps(manifest), encoding="utf-8")
    await import_knowledge_proposals(service, load_knowledge_bootstrap(second), contributor="system")
    [rule] = await service.repository.list()
    assert rule.content.endswith("Reworded.") and rule.status == KnowledgeStatus.APPROVED
