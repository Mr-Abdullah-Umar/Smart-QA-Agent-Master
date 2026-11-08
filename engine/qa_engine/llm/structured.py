"""Schema-enforced structured generation with a bounded repair loop.

The model must answer with a single JSON object. Replies that fail to parse or fail
Pydantic validation are sent back with the exact error (max two repair attempts) without
discarding prior context, as specified in the Phase 0 spike report.
"""

import json
from typing import Callable, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from qa_engine.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when the model cannot produce schema-valid JSON within the repair budget."""


def extract_json_object(text: str) -> str:
    """Return the outermost JSON object in a reply, tolerating code fences and prose."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model reply.")
    return cleaned[start : end + 1]


def schema_instructions(model_cls: Type[BaseModel]) -> str:
    schema = json.dumps(model_cls.model_json_schema(), separators=(",", ":"))
    return (
        "Respond with ONLY one JSON object (no markdown, no commentary) that validates "
        f"against this JSON Schema:\n{schema}"
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
            parsed = model_cls.model_validate(json.loads(extract_json_object(content)))
            problems = extra_check(parsed) if extra_check else []
            if not problems:
                return parsed
            raise ValueError("; ".join(problems))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:2000]
            conversation = conversation + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not valid for the required schema:\n"
                        f"{last_error}\nReply again with ONLY the corrected JSON object."
                    ),
                },
            ]
    raise StructuredOutputError(f"Model did not return valid JSON: {last_error}")
