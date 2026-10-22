from ai_content.domains.marketing.creative_knowledge.scope import (
    canonical_brand_id,
    product_archetype,
    product_niche,
)


def test_scope_ids_come_from_the_data() -> None:
    assert canonical_brand_id("OaklineHome") == "brand:oaklinehome"
    assert canonical_brand_id("brand:LumiSkin") == "brand:lumiskin"
    assert product_niche(product_type="Standing Desk") == "niche:standing_desk"
    assert product_archetype(product_type="Serum") == "serum"
    assert canonical_brand_id(" ") is None and product_niche(product_type=None) is None
