"""Schema-enforced structured generation with a bounded repair loop.

The model must answer with a single JSON object. Replies that fail to parse or fail
Pydantic validation are sent back with the exact error (max two repair attempts) without
discarding prior context, as specified in the Phase 0 spike report. Unescaped double quotes
inside string values are repaired locally, and replies cut off by the model's output limit
are reported as such so the retry asks for a shorter answer.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from qa_engine.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)

MAX_QUOTE_REPAIRS = 200


class StructuredOutputError(Exception):
    """Raised when the model cannot produce schema-valid JSON within the repair budget."""


class TruncatedReplyError(ValueError):
    """The reply stopped before its JSON object was closed (output limit reached)."""


def _strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def extract_json_object(text: str) -> str:
    """Return the outermost JSON object in a reply, tolerating code fences and prose."""
    cleaned = _strip_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        if start != -1:
            raise TruncatedReplyError("The reply was cut off before the JSON object was closed.")
        raise ValueError("No JSON object found in model reply.")
    return cleaned[start : end + 1]


def _escape_stray_quote(text: str, exc: json.JSONDecodeError) -> Optional[str]:
    """Escape the quote that ended a string too early, e.g. "Push "Add" button"."""
    if not exc.msg.startswith("Expecting ',' delimiter") or exc.pos >= len(text):
        return None
    if text[exc.pos] == '"' and text[exc.pos - 1] == '"':
        quote = exc.pos - 1  # inner quote right before the closing one: "... "Row 2""
    elif text[exc.pos] in '"{[]},:':
        return None
    else:
        quote = text.rfind('"', 0, exc.pos)
    if quote <= 0 or text[quote - 1] == "\\":
        return None
    return text[:quote] + '\\"' + text[quote + 1 :]


def loads_lenient(raw: str) -> Any:
    """json.loads that tolerates raw control characters and unescaped inner quotes."""
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError as first_error:
        text, exc = raw, first_error
        for _ in range(MAX_QUOTE_REPAIRS):
            fixed = _escape_stray_quote(text, exc)
            if fixed is None:
                break
            text = fixed
            try:
                return json.loads(text, strict=False)
            except json.JSONDecodeError as next_error:
                exc = next_error
        raise


def parse_reply(content: str) -> Any:
    """Parse the JSON object in a model reply, flagging replies that were cut off."""
    raw = extract_json_object(content)
    try:
        return loads_lenient(raw)
    except json.JSONDecodeError as exc:
        if not _strip_fences(content).endswith("}"):
            raise TruncatedReplyError(
                f"The reply was cut off before the JSON object was closed ({exc})."
            ) from exc
        raise ValueError(str(exc)) from exc


def schema_instructions(model_cls: Type[BaseModel]) -> str:
    schema = json.dumps(model_cls.model_json_schema(), separators=(",", ":"))
    return (
        "Respond with ONLY one JSON object (no markdown, no commentary) that validates "
        "against the JSON Schema below. Write it compactly without indentation, and escape "
        f'every double quote inside a string value as \\".\n{schema}'
    )


def _repair_request(error: Exception) -> str:
    if isinstance(error, TruncatedReplyError):
        return (
            "Your previous reply was cut off before the JSON object ended, because it was too "
            "long. Reply again with the COMPLETE JSON object, written compactly on one line, "
            "with shorter steps and titles."
        )
    return (
        "Your previous reply was not valid for the required schema:\n"
        f"{str(error)[:2000]}\nReply again with ONLY the corrected JSON object."
    )


async def chat_structured(
    llm: LLMProvider,
    messages: List[Dict[str, str]],
    model_cls: Type[T],
    max_repairs: int = 2,
    temperature: float = 0.1,
    extra_check: Optional[Callable[[T], List[str]]] = None,
) -> T:
    """Ask the model for JSON matching `model_cls`, repairing invalid replies.

    `extra_check` may return semantic problems (e.g. out-of-scope URLs); they are fed back
    to the model exactly like schema errors.
    """
    conversation = list(messages)
    last_error = ""
    for _ in range(max_repairs + 1):
        response = await llm.chat(conversation, temperature=temperature)
        content = response.content or ""
        try:
            parsed = model_cls.model_validate(parse_reply(content))
            problems = extra_check(parsed) if extra_check else []
            if not problems:
                return parsed
            raise ValueError("; ".join(problems))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:2000]
            conversation = conversation + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": _repair_request(exc)},
            ]
    raise StructuredOutputError(f"Model did not return valid JSON: {last_error}")
