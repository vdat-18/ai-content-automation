from ai_content.domains.marketing.products.compliance import (
    brief_warnings,
    find_flagged_terms,
    package_warnings,
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
