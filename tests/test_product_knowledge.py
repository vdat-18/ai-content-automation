from dataclasses import replace
from datetime import UTC, datetime

from tests.pgstore import knowledge_repository, product_repository

from ai_content.domains.marketing.creative_knowledge.models import (
    CreativeKnowledge,
    KnowledgeAuthority,
    KnowledgeStage,
    KnowledgeStatus,
    KnowledgeType,
)
from ai_content.domains.marketing.creative_knowledge.service import (
    CreativeKnowledgeService,
    CuratedKnowledge,
)
from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.knowledge import (
    PRODUCT_AD_SCOPE,
    approved_rules,
    propose_feedback,
)
from ai_content.domains.marketing.products.service import ProductCatalogService

PRODUCT_ID = "1730000000000000001"
PNG = b"\x89PNG\r\n\x1a\nfake"


def _knowledge(tmp_path) -> CreativeKnowledgeService:
    return CreativeKnowledgeService(knowledge_repository())


async def _approved(
    service: CreativeKnowledgeService,
    knowledge_id: str,
    title: str,
    stages: tuple[KnowledgeStage, ...],
    knowledge_type: KnowledgeType = KnowledgeType.PRACTICE,
    asset: str = "keyframe",
) -> None:
    await service.repository.save(
        CreativeKnowledge(
            knowledge_id=knowledge_id,
            knowledge_type=knowledge_type,
            title=title,
            content=f"DO: {title}",
            scope=replace(PRODUCT_AD_SCOPE, asset_type=asset),
            status=KnowledgeStatus.APPROVED,
            authority=KnowledgeAuthority.LEAD,
            source_refs=("team",),
            evidence_refs=(),
            applies_to=stages,
            approved_by="lead",
            approved_at=datetime.now(UTC),
        )
    )


async def _feedback(knowledge: CreativeKnowledgeService, text: str) -> CreativeKnowledge:
    return await propose_feedback(
        knowledge,
        product_id=PRODUCT_ID,
        text=text,
        contributor="user",
        authority=KnowledgeAuthority.INDIVIDUAL,
    )


async def test_only_approved_rules_of_the_stage_and_asset_are_used(tmp_path) -> None:
    knowledge = _knowledge(tmp_path)
    await _approved(knowledge, "a", "Clear skin", (KnowledgeStage.ORCHESTRATION,))
    await _approved(knowledge, "b", "Hook fast", (KnowledgeStage.PREPARATION,), asset="brief")
    await _feedback(knowledge, "Not approved yet")
    image = await approved_rules(knowledge, KnowledgeStage.ORCHESTRATION, "keyframe")
    assert (image.text, image.ids) == ("- Clear skin: DO: Clear skin", ["a"])
    brief = await approved_rules(knowledge, KnowledgeStage.PREPARATION, "brief")
    assert (brief.text, brief.ids) == ("- Hook fast: DO: Hook fast", ["b"])
    assert not (await approved_rules(knowledge, KnowledgeStage.PREPARATION, "keyframe")).ids
    assert (await approved_rules(None, KnowledgeStage.ORCHESTRATION, "keyframe")).text == ""


async def test_the_same_feedback_is_proposed_once_and_waits_for_a_human(tmp_path) -> None:
    knowledge = _knowledge(tmp_path)
    await _feedback(knowledge, "Acne visible on the cheek")
    item = await _feedback(knowledge, "Acne visible on the cheek")
    assert item.status == KnowledgeStatus.PROPOSED
    assert len(await knowledge.repository.list()) == 1
    assert not (await approved_rules(knowledge, KnowledgeStage.ORCHESTRATION, "keyframe")).ids


class _Curator:
    async def rewrite(self, item, others):
        self.seen = [other.knowledge_id for other in others]
        return CuratedKnowledge("Clear skin", "WHEN: a face. DO: clear skin.", ("old", "hard"))


async def test_curation_rewrites_the_rule_and_retires_the_ones_it_replaces(tmp_path) -> None:
    knowledge = _knowledge(tmp_path)
    stages = (KnowledgeStage.ORCHESTRATION,)
    await _approved(knowledge, "old", "No pimples", stages)
    await _approved(knowledge, "hard", "Product identity", stages, KnowledgeType.HARD_RULE)
    item = await _feedback(knowledge, "acne again")
    await knowledge.decide(item.knowledge_id, status=KnowledgeStatus.APPROVED, reviewer="lead")
    curator = _Curator()
    rewritten = await knowledge.curate(item.knowledge_id, curator)
    assert curator.seen == ["old"]  # hard rules are never offered for replacement
    assert (rewritten.title, rewritten.status) == ("Clear skin", KnowledgeStatus.APPROVED)
    by_id = {i.knowledge_id: i.status for i in await knowledge.repository.list()}
    assert by_id["old"] == KnowledgeStatus.EXPIRED and by_id["hard"] == KnowledgeStatus.APPROVED


async def test_a_failed_curation_keeps_the_approved_rule_as_it_was(tmp_path) -> None:
    class _Failing:
        async def rewrite(self, item, others):
            return None

    knowledge = _knowledge(tmp_path)
    item = await _feedback(knowledge, "acne again")
    await knowledge.decide(item.knowledge_id, status=KnowledgeStatus.APPROVED, reviewer="lead")
    assert (await knowledge.curate(item.knowledge_id, _Failing())).title == "acne again"


async def test_rules_reach_the_image_model_and_checker_and_qa_problems_become_proposals(
    tmp_path, monkeypatch
) -> None:
    async def fetch_images(urls, http=None):
        return [b"photo"]

    monkeypatch.setattr(service_module, "fetch_images", fetch_images)
    knowledge = _knowledge(tmp_path)
    await _approved(knowledge, "a", "Clear skin", (KnowledgeStage.ORCHESTRATION,))
    await _approved(knowledge, "b", "Body ratio", (KnowledgeStage.REVIEW,))
    shots: list[dict] = []
    descriptions: list[str] = []

    class _Keyframer:
        async def master(self, shot, photos, scene, fix="", persona=None):
            shots.append(shot)
            return PNG

    class _Checker:
        async def check(
            self, description, photos, keyframe, master=None, persona=None, previous=None
        ):
            descriptions.append(description)
            return "arm too long" if len(descriptions) == 1 else ""

    repository = product_repository()
    service = ProductCatalogService(
        repository,
        keyframer=_Keyframer(),  # type: ignore[arg-type]
        checker=_Checker(),  # type: ignore[arg-type]
        knowledge=knowledge,
    )
    await repository.upsert_detail(
        {"product_id": PRODUCT_ID, "title": "Giỏ", "images": ["https://img.example/1.jpg"]}
    )
    brief = {"title": "b", "shots": [{"role": "hook", "keyframe_prompt": "master shot"}]}
    await repository.save_brief(PRODUCT_ID, "", brief, "approved")
    await service.generate_keyframes(PRODUCT_ID, tmp_path)
    assert shots[0]["rules"] == "- Clear skin: DO: Clear skin"
    assert "Approved rules:\n- Body ratio: DO: Body ratio" in descriptions[0]
    items = await knowledge.repository.list()
    proposed = [i for i in items if i.status == KnowledgeStatus.PROPOSED]
    assert [(i.content, i.contributor) for i in proposed] == [("arm too long", "gemini-qa")]


async def test_brief_writer_gets_the_approved_preparation_rules(tmp_path) -> None:
    from test_product_briefs import PRODUCT_ID as BRIEF_PRODUCT
    from test_product_briefs import _make_reference_live, _service

    seen: list[str] = []

    class _Writer:
        async def write(self, product, user_idea, shot_count=1, person_photos=None, rules=""):
            seen.append(rules)
            return {
                "title": "Brief",
                "shots": [{"role": "hook", "keyframe_prompt": "x"}] * shot_count,
            }

    service = await _service(tmp_path, _Writer())
    knowledge = _knowledge(tmp_path)
    await _approved(knowledge, "b", "Hook fast", (KnowledgeStage.PREPARATION,), asset="brief")
    service._knowledge = knowledge
    await service._repository.select_product(BRIEF_PRODUCT, "áo thun")
    await _make_reference_live(service)
    record = await service.create_brief(BRIEF_PRODUCT, video_seconds=15, person_photos=[b"face"])
    assert seen == ["- Hook fast: DO: Hook fast"]
    assert record["brief"]["rule_ids"] == ["b"]  # the brief keeps which rules shaped it


async def test_an_approved_rule_can_be_turned_off_and_is_then_not_used(tmp_path) -> None:
    import pytest

    knowledge = _knowledge(tmp_path)
    await _approved(knowledge, "a", "Clear skin", (KnowledgeStage.ORCHESTRATION,))
    retired = await knowledge.retire("a")
    assert retired.status == KnowledgeStatus.EXPIRED
    assert not (await approved_rules(knowledge, KnowledgeStage.ORCHESTRATION, "keyframe")).ids
    with pytest.raises(ValueError, match="Only approved"):
        await knowledge.retire("a")


async def test_an_automatic_proposal_never_reopens_a_decided_rule(tmp_path) -> None:
    knowledge = _knowledge(tmp_path)
    first = await propose_feedback(
        knowledge, product_id=PRODUCT_ID, text="Hook fast", contributor="video-check",
        authority=KnowledgeAuthority.EXTERNAL, asset_type="brief", once=True,
    )  # fmt: skip
    await knowledge.repository.save(replace(first, status=KnowledgeStatus.REJECTED))
    again = await propose_feedback(
        knowledge, product_id="other", text="Hook fast", contributor="video-check",
        authority=KnowledgeAuthority.EXTERNAL, asset_type="brief", once=True,
    )  # fmt: skip
    assert again.status == KnowledgeStatus.REJECTED
    assert len(await knowledge.repository.list()) == 1


async def test_feedback_never_puts_an_approved_rule_back_to_proposed(tmp_path) -> None:
    knowledge = _knowledge(tmp_path)
    first = await _feedback(knowledge, "Acne visible on the cheek")
    await knowledge.decide(first.knowledge_id, status=KnowledgeStatus.APPROVED, reviewer="lead")
    again = await _feedback(knowledge, "Acne visible on the cheek")  # without once=True
    assert again.status == KnowledgeStatus.APPROVED and again.approved_by == "lead"
    assert (await approved_rules(knowledge, KnowledgeStage.ORCHESTRATION, "keyframe")).ids == [
        first.knowledge_id
    ]


async def test_a_check_problem_seen_in_two_videos_becomes_a_proposed_script_rule(tmp_path) -> None:
    knowledge = _knowledge(tmp_path)
    repository = product_repository()
    service = ProductCatalogService(repository, knowledge=knowledge)
    for product in ("p1", "p2"):
        await repository.save_brief(product, "", {"title": product, "shots": []}, "approved")
    issue = {"code": "no_hook", "severity": "minor", "message": "m"}
    await service._write_json(
        tmp_path, "videos/p1/video.json", {"check": {"score": 90, "issues": [issue]}}
    )
    await service._learn_from_check("p2", tmp_path, {"score": 90, "issues": [issue]})
    [item] = await knowledge.repository.list()
    assert item.status == KnowledgeStatus.PROPOSED and item.contributor == "video-check"
    assert item.scope.asset_type == "brief" and "hook" in item.content

    await service._learn_from_check("p2", tmp_path, {"score": 90, "issues": []})
    quiet = {"code": "silence", "severity": "minor", "message": "m"}
    await service._learn_from_check("p2", tmp_path, {"score": 90, "issues": [quiet]})
    assert len(await knowledge.repository.list()) == 1  # silence has not been seen before


async def test_rules_can_be_skipped_and_are_capped(tmp_path, monkeypatch) -> None:
    from ai_content.domains.marketing.products import knowledge as knowledge_module

    knowledge = _knowledge(tmp_path)
    for name in ("a", "b", "c"):
        await _approved(knowledge, name, f"Rule {name}", (KnowledgeStage.ORCHESTRATION,))
    stage = KnowledgeStage.ORCHESTRATION
    skipped = await approved_rules(knowledge, stage, "keyframe", frozenset({"b"}))
    assert skipped.ids == ["a", "c"]
    monkeypatch.setattr(knowledge_module, "MAX_RULES", 2)
    assert len((await approved_rules(knowledge, stage, "keyframe")).ids) == 2
