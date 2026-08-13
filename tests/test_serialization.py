import pytest

from multiprovider_llm.errors import ValidationError
from multiprovider_llm.serialization import extract_json_text, normalize_messages
from multiprovider_llm.types import Message


def test_normalize_prompt_only():
    msgs = normalize_messages(prompt="hello", messages=None)
    assert msgs == [Message(role="user", content="hello")]


def test_normalize_mapping_messages():
    msgs = normalize_messages(
        prompt=None,
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )
    assert msgs[0].role == "system" and msgs[1].content == "u"


def test_normalize_rejects_both_or_neither():
    with pytest.raises(ValidationError):
        normalize_messages(prompt="x", messages=[Message("user", "y")])
    with pytest.raises(ValidationError):
        normalize_messages(prompt=None, messages=None)


def test_extract_json_from_fence_and_think():
    raw = "<think>nope</think>```json\n{\"a\": 1}\n```"
    assert extract_json_text(raw) == '{"a": 1}' or '"a"' in extract_json_text(raw)


def test_extract_json_fails_on_plain_text():
    with pytest.raises(ValidationError):
        extract_json_text("not json")
