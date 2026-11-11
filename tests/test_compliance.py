from ai_content.domains.marketing.products.compliance import (
    brief_warnings,
    find_flagged_terms,
    package_warnings,
    product_facts,
)


def test_flags_absolute_claims_platforms_and_health_claims_only_as_whole_words() -> None:
    assert find_flagged_terms("Sọt TỐT NHẤT, 100% chắc chắn") == [
        ("absolute claim", "tốt nhất"),
        ("absolute claim", "100%"),
        ("absolute claim", "chắc chắn"),
    ]
    assert find_flagged_terms("rẻ hơn trên Shopee") == [("other platform", "shopee")]
    assert find_flagged_terms("giúp điều trị mụn") == [("health claim", "điều trị")]
    assert find_flagged_terms("chất liệu polyester, gấp gọn, freeship") == []
    assert find_flagged_terms("hoàn toàn mới") and not find_flagged_terms("tikitaka")


DETAIL = {
    "title": "Sọt lưới gấp gọn",
    "price": {"current": 199000},
    "sold_count": 3200,
    "rating": 4.6,
    "description": "Giảm 30% hôm nay, cotton thoáng mát",
}


def test_numbers_missing_from_the_product_data_are_warned_about() -> None:
    brief = {
        "title": "Sọt gọn",
        "selling_angle": "",
        "shots": [
            {"on_screen_text": "Chỉ 199k", "voiceover": "Hơn 3.000 người đã mua, giảm 30%"},
            {"on_screen_text": "", "voiceover": "Hơn 10.000 người mua, giảm 70%, gấp trong 3 giây"},
        ],
    }
    assert brief_warnings(brief, product_facts(DETAIL, "")) == [
        'shot 2 voiceover: "10.000" is not in the product data (unverified number)',
        'shot 2 voiceover: "70%" is not in the product data (unverified number)',
    ]
    assert brief_warnings(brief) == []  # no product data, nothing to check against


def test_the_users_own_idea_counts_as_a_source() -> None:
    brief = {"shots": [{"voiceover": "Tặng 500 sọt cho khách"}]}
    assert brief_warnings(brief, product_facts(DETAIL, "")) != []
    assert brief_warnings(brief, product_facts(DETAIL, "tặng 500 sọt")) == []


def test_warnings_say_where_the_word_was_found() -> None:
    brief = {
        "title": "Sọt gọn",
        "selling_angle": "Rẻ nhất phòng giặt",
        "shots": [{"on_screen_text": "", "voiceover": "Mua trên Shopee"}],
    }
    assert brief_warnings(brief) == [
        'selling_angle: "rẻ nhất" (absolute claim)',
        'shot 1 voiceover: "shopee" (other platform)',
    ]
    package = {"captions": ["ổn", "Tốt nhất!"], "hashtags": ["#shopee"]}
    assert package_warnings(package) == [
        'caption 2: "tốt nhất" (absolute claim)',
        'hashtags: "shopee" (other platform)',
    ]
