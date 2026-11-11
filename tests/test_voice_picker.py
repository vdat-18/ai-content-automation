import asyncio
from types import SimpleNamespace

from ai_content.domains.marketing.products.speech import VOICES
from ai_content.domains.marketing.products.voice_picker import VoicePicker, load_catalog, settle


def test_every_catalog_voice_is_a_voice_the_speech_model_offers() -> None:
    catalog = load_catalog()
    assert {entry["id"] for entry in catalog} <= set(VOICES)
    assert {entry["gender"] for entry in catalog} == {"male", "female"}
    assert all(entry["description"] for entry in catalog)


def test_a_matching_voice_is_kept_with_its_reason() -> None:
    choice = settle("male", "tiendat.mp3", "Young and lively.", load_catalog())
    assert (choice.voice, choice.reason) == ("tiendat.mp3", "Young and lively.")


def test_a_voice_of_the_wrong_gender_is_replaced() -> None:
    choice = settle("female", "tiendat.mp3", "x", load_catalog())
    assert {e["id"]: e["gender"] for e in load_catalog()}[choice.voice] == "female"


def test_an_unknown_voice_falls_back_to_the_first_of_that_gender() -> None:
    assert settle("male", "nobody.mp3", "x", load_catalog()).voice == "tiendat.mp3"
    assert settle("female", "", "x", load_catalog()).voice == "kimoanh.mp3"


def test_without_a_known_gender_any_listed_voice_may_be_used() -> None:
    assert settle("unknown", "maichi.mp3", "Playful.", load_catalog()).voice == "maichi.mp3"


def test_the_picker_passes_the_story_and_catalog_to_the_model() -> None:
    seen = {}

    class Fake:
        async def PickVoice(self, brief_json, voices_json, person_photos):
            seen.update(brief=brief_json, voices=voices_json, photos=len(person_photos))
            return SimpleNamespace(gender="female", voice="kimoanh.mp3", reason="Soft and natural.")

    brief = {"title": "Dress", "with_person": True, "shots": [{"voiceover": "Xin chào"}]}
    choice = asyncio.run(VoicePicker(Fake()).pick(brief, [b"\xff\xd8\xff"]))
    assert choice is not None and choice.voice == "kimoanh.mp3"
    assert "Xin chào" in seen["brief"] and "kimoanh.mp3" in seen["voices"] and seen["photos"] == 1
