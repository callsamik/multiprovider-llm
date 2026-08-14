from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .errors import ValidationError
from .types import Message


def normalize_messages(
    *,
    prompt: str | None,
    messages: Sequence[Message | Mapping[str, Any]] | None,
) -> list[Message]:
    if prompt is not None and messages is not None:
        raise ValidationError("provide exactly one of prompt or messages")
    if prompt is None and messages is None:
        raise ValidationError("provide exactly one of prompt or messages")
    if prompt is not None:
        return [Message(role="user", content=str(prompt))]
    out: list[Message] = []
    for item in messages or ():
        if isinstance(item, Message):
            out.append(item)
            continue
        role = str(item.get("role", "")).strip()
        content = item.get("content")
        if not role or content is None:
            raise ValidationError("each message mapping needs role and content")
        out.append(Message(role=role, content=str(content)))
    if not out:
        raise ValidationError("messages must be non-empty")
    return out


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_text(text: str) -> str:
    """Extract a JSON object string from model text.

    Tries a full ``json.loads``, then a fenced ``json`` object, then the
    first object via ``JSONDecoder.raw_decode`` (so prose such as
    ``Sure! {"a": 1} and also {"b": 2}`` yields ``{"a":1}``). Parse
    failures are always ``ValidationError`` — never ``JSONDecodeError``.
    """
    raw = _THINK_RE.sub("", text or "")
    raw = _THINK_OPEN_RE.sub("", raw).strip()
    if not raw:
        raise ValidationError("empty model response")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return json.dumps(data, separators=(",", ":"))
    except json.JSONDecodeError:
        pass
    fence = _FENCE_RE.search(raw)
    if fence:
        try:
            data = json.loads(fence.group(1))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return json.dumps(data, separators=(",", ":"))
    data = _first_json_object(raw)
    if isinstance(data, dict):
        return json.dumps(data, separators=(",", ":"))
    raise ValidationError("model response was not a JSON object")


def _first_json_object(raw: str) -> Any:
    start = raw.find("{")
    if start < 0:
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(raw, start)
    except json.JSONDecodeError as exc:
        raise ValidationError("model response was not a JSON object") from exc
    return data
