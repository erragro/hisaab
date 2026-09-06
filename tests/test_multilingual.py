from pydantic import ValidationError

from app.prompts import CHAT_SYSTEM, DRAFT_SYSTEM, in_language
from app.schemas import ChatIn, DraftIn


def test_only_supported_language_codes_are_accepted():
    assert ChatIn(message="আমার অ্যাকাউন্ট বন্ধ হয়েছে", language="bn").language == "bn"
    assert DraftIn(kind="legal_notice", sender_name="A", recipient_name="B", language="hi").language == "hi"
    try:
        ChatIn(message="test", language="kn")
    except ValidationError:
        pass
    else:
        raise AssertionError("unsupported language was accepted")


def test_model_language_instruction_preserves_safety_prompt():
    bengali = in_language(CHAT_SYSTEM, "bn")
    hindi = in_language(DRAFT_SYSTEM, "hi")
    assert "NOT legal advice" in bengali
    assert "plain Bengali" in bengali
    assert "Devanagari" in hindi
