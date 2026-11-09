"""Action DSL compilation, structured-output repair, and AI designer validation."""

import json

import pytest
from pydantic import ValidationError

from qa_engine.generation.actions import ElementLocator, TestAction, render_action
from qa_engine.generation.designer import (
    AITestDesigner,
    TestDesignResult,
    build_collection,
    build_coverage,
    parse_acceptance_criteria,
    required_secrets,
)
from qa_engine.generation.scriptgen import ScriptGenerator
from qa_engine.generation.testcases import TestCase, TestCaseCollection
from qa_engine.generation.validator import ScriptValidator
from qa_engine.llm.provider import LLMProvider, LLMResponse
from qa_engine.llm.structured import (
    StructuredOutputError,
    TruncatedReplyError,
    chat_structured,
    loads_lenient,
    parse_reply,
)


class ScriptedLLM(LLMProvider):
    """Returns queued replies and records every conversation it receives."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def initialize(self):
        return None

    async def chat(self, messages, tools=None, temperature=0.2):
        self.calls.append(messages)
        return LLMResponse(content=self.replies.pop(0))

    async def stream_chat(self, messages, tools=None, temperature=0.2):
        yield ""


def _btn(name):
    return {"by": "role", "role": "button", "value": name}


def test_every_action_compiles_to_valid_policy_compliant_code(tmp_path):
    field = ElementLocator(by="label", value="Email")
    actions = [
        TestAction(action="goto", value="/login"),
        TestAction(action="fill", target=field, value="user+{{unique}}@mail.test"),
        TestAction(
            action="fill",
            target=ElementLocator(by="label", value="Password"),
            value="{{secret.login_password}}",
        ),
        TestAction(action="select", target=ElementLocator(by="label", value="Country"), value="PK"),
        TestAction(action="check", target=ElementLocator(by="role", role="checkbox", value="Keep")),
        TestAction(action="press", value="Enter"),
        TestAction(action="click", target=ElementLocator(**_btn('Sign "in"'))),
        TestAction(action="expect_url", value="/dashboard"),
        TestAction(action="expect_title", value="Dashboard"),
        TestAction(action="expect_text", value="Welcome"),
        TestAction(action="expect_value", target=field, value="x"),
        TestAction(action="expect_count", target=ElementLocator(by="role", role="row"), value="3"),
        TestAction(action="expect_hidden", target=ElementLocator(by="text", value="Error")),
        TestAction(action="expect_enabled", target=ElementLocator(by="test_id", value="submit")),
    ]
    tc = TestCase(
        tc_id="TC-AUTH-001",
        title="Login",
        requirement_ref="REQ-AUTH",
        steps=["Log in"],
        expected_result="Dashboard shown",
        test_types=["smoke", "Regression", "bogus"],
        actions=actions,
    )
    assert tc.test_types == ["smoke", "regression"]

    paths = ScriptGenerator.write_scripts(tmp_path / "scripts", [tc], "Auth")
    code = paths["test"].read_text(encoding="utf-8")
    ok, errors = ScriptValidator.validate_code(code, approved_tc_ids={"TC-AUTH-001"})
    assert ok, errors
    compile(code, "test_auth.py", "exec")
    assert 'harness_text("{{secret.login_password}}")' in code
    assert "hunter" not in code
    assert 'name="Sign \\"in\\""' in code
    assert ".to_have_count(3)" in code
    assert required_secrets(TestCaseCollection(testcases=[tc])) == ["LOGIN_PASSWORD"]


def test_action_validation_rejects_bad_plans():
    with pytest.raises(ValidationError):
        TestAction(action="click")
    with pytest.raises(ValidationError):
        TestAction(action="fill", target=ElementLocator(by="label", value="A"))
    with pytest.raises(ValidationError):
        ElementLocator(by="role", role="made-up-role", value="X")
    with pytest.raises(ValidationError):
        TestAction(action="expect_count", target=ElementLocator(by="text", value="a"), value="x")
    assert render_action(TestAction(action="goto", value="")) == 'page.goto(harness_url(""))'


def test_hash_covers_action_plan():
    base = {
        "tc_id": "TC-A-001",
        "title": "t",
        "requirement_ref": "r",
        "steps": ["s"],
        "expected_result": "e",
    }
    a = TestCaseCollection(
        testcases=[TestCase(**base, actions=[TestAction(action="goto", value="")])]
    )
    b = TestCaseCollection(
        testcases=[TestCase(**base, actions=[TestAction(action="goto", value="/admin")])]
    )
    assert a.compute_sha256_hash() != b.compute_sha256_hash()


def test_parse_acceptance_criteria_strips_bullets():
    criteria = parse_acceptance_criteria(
        "1. User can log in\n- Wrong password shows error\n\nAC-3: x"
    )
    assert criteria == [
        {"id": "AC-1", "text": "User can log in"},
        {"id": "AC-2", "text": "Wrong password shows error"},
        {"id": "AC-3", "text": "x"},
    ]


@pytest.mark.asyncio
async def test_structured_output_repairs_invalid_json():
    llm = ScriptedLLM(["not json", '```json\n{"urls": ["https://a.test/x"], "reason": "r"}\n```'])
    from qa_engine.generation.designer import PageSelection

    result = await chat_structured(llm, [{"role": "user", "content": "pick"}], PageSelection)
    assert result.urls == ["https://a.test/x"]
    assert "not valid" in llm.calls[1][-1]["content"]

    failing = ScriptedLLM(["{}", "nope", "still nope"])
    with pytest.raises(StructuredOutputError):
        await chat_structured(failing, [{"role": "user", "content": "x"}], TestDesignResult)


def _design_json(goto_value, ac="AC-1"):
    return json.dumps(
        {
            "testcases": [
                {
                    "title": "Valid login",
                    "ac_ref": ac,
                    "priority": "P1",
                    "test_types": ["smoke"],
                    "steps": ["Open login", "Sign in"],
                    "expected_result": "Dashboard",
                    "actions": [
                        {"action": "goto", "value": goto_value},
                        {
                            "action": "fill",
                            "target": {"by": "label", "value": "Password"},
                            "value": "{{secret.PASSWORD}}",
                        },
                        {"action": "click", "target": _btn("Sign in")},
                        {"action": "expect_url", "value": "/home"},
                    ],
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_designer_rejects_out_of_scope_navigation_and_numbers_cases():
    criteria = parse_acceptance_criteria("User can sign in")
    llm = ScriptedLLM([_design_json("https://evil.test/phish"), _design_json("/login")])
    designer = AITestDesigner(llm, "User Login", "https://app.test/", ["app.test"])
    result = await designer.design("Login feature", criteria, [], [])

    assert "leaves the allowed scope" in llm.calls[1][-1]["content"]
    collection = build_collection(result, "User Login", "REQ-USER-LOGIN")
    tc = collection.testcases[0]
    assert tc.tc_id == "TC-USER-LOGIN-001"
    assert "regression" in tc.test_types
    assert build_coverage(collection, criteria).coverage_percentage == 100.0

    revised = build_collection(
        TestDesignResult.model_validate_json(_design_json("/login")),
        "User Login",
        "REQ-USER-LOGIN",
        version=2,
        existing_ids={"TC-USER-LOGIN-001"},
    )
    assert revised.testcases[0].tc_id == "TC-USER-LOGIN-002"


@pytest.mark.asyncio
async def test_designer_requires_every_criterion_covered():
    criteria = parse_acceptance_criteria("A\nB")
    llm = ScriptedLLM([_design_json(""), _design_json(""), _design_json("")])
    designer = AITestDesigner(llm, "M", "https://app.test/", ["app.test"])
    with pytest.raises(StructuredOutputError, match="No test case covers: AC-2"):
        await designer.design("req", criteria, [], [])


def test_lenient_parse_repairs_unescaped_inner_quotes():
    raw = '{"title": "Push "Add" button", "steps": ["Click "Save" in "Row 2""], "n": 1}'
    assert loads_lenient(raw) == {
        "title": 'Push "Add" button',
        "steps": ['Click "Save" in "Row 2"'],
        "n": 1,
    }
    with pytest.raises(json.JSONDecodeError):
        loads_lenient('{"a": 1 "b": 2}')


@pytest.mark.asyncio
async def test_structured_output_parses_reply_with_inner_quotes_without_repair_call():
    from qa_engine.generation.designer import PageSelection

    llm = ScriptedLLM(['{"urls": [], "reason": "Shows the "Add" button"}'])
    result = await chat_structured(llm, [{"role": "user", "content": "pick"}], PageSelection)
    assert result.reason == 'Shows the "Add" button'
    assert len(llm.calls) == 1


def test_cut_off_reply_is_reported_as_truncated():
    with pytest.raises(TruncatedReplyError):
        parse_reply('{"testcases": [{"title": "A"}, {"title": "B", "steps": ["x"')
    with pytest.raises(TruncatedReplyError):
        parse_reply('{"testcases": [{"title": "A"}, {"title": "B"')


@pytest.mark.asyncio
async def test_truncated_reply_asks_for_a_shorter_answer():
    from qa_engine.generation.designer import PageSelection

    llm = ScriptedLLM(['{"urls": ["https://a.test/x", "https://a.t', '{"urls": [], "reason": ""}'])
    await chat_structured(llm, [{"role": "user", "content": "pick"}], PageSelection)
    assert "cut off" in llm.calls[1][-1]["content"]


def _design_json_for(acs):
    return json.dumps(
        {"testcases": [json.loads(_design_json("/login", ac))["testcases"][0] for ac in acs]}
    )


@pytest.mark.asyncio
async def test_designer_splits_many_criteria_into_batches():
    criteria = parse_acceptance_criteria("\n".join(f"Criterion {i}" for i in range(1, 13)))
    llm = ScriptedLLM(
        [
            _design_json_for([f"AC-{i}" for i in range(1, 6)]),
            _design_json_for([f"AC-{i}" for i in range(6, 11)]),
            _design_json_for(["AC-11", "AC-12"]),
        ]
    )
    updates = []

    async def progress(detail):
        updates.append(detail)

    designer = AITestDesigner(llm, "M", "https://app.test/", ["app.test"])
    result = await designer.design("req", criteria, [], [], progress=progress)

    assert len(llm.calls) == 3
    assert "BATCH 2 OF 3: design cases ONLY for AC-6, AC-7, AC-8, AC-9, AC-10" in (
        llm.calls[1][-1]["content"]
    )
    assert updates == ["Batch 1 of 3: AC-1 to AC-5", "Batch 2 of 3: AC-6 to AC-10",
                       "Batch 3 of 3: AC-11 to AC-12"]
    collection = build_collection(result, "M", "REQ-M")
    assert len({tc.tc_id for tc in collection.testcases}) == 12
    assert build_coverage(collection, criteria).coverage_percentage == 100.0


@pytest.mark.asyncio
async def test_batch_rejects_cases_for_criteria_outside_the_batch():
    criteria = parse_acceptance_criteria("\n".join(f"C{i}" for i in range(1, 7)))
    llm = ScriptedLLM(
        [
            _design_json_for(["AC-1", "AC-2", "AC-3", "AC-4", "AC-6"]),
            _design_json_for([f"AC-{i}" for i in range(1, 6)]),
            _design_json_for(["AC-6"]),
        ]
    )
    designer = AITestDesigner(llm, "M", "https://app.test/", ["app.test"])
    result = await designer.design("req", criteria, [], [])
    assert "ac_ref 'AC-6' is not one of" in llm.calls[1][-1]["content"]
    assert sorted(tc.ac_ref for tc in result.testcases) == sorted(
        f"AC-{i}" for i in range(1, 7)
    )


@pytest.mark.asyncio
async def test_revise_sends_each_batch_only_its_own_cases():
    criteria = parse_acceptance_criteria("\n".join(f"C{i}" for i in range(1, 7)))
    first = build_collection(
        TestDesignResult.model_validate_json(_design_json_for([f"AC-{i}" for i in range(1, 7)])),
        "M",
        "REQ-M",
    )
    llm = ScriptedLLM(
        [_design_json_for([f"AC-{i}" for i in range(1, 6)]), _design_json_for(["AC-6"])]
    )
    designer = AITestDesigner(llm, "M", "https://app.test/", ["app.test"])
    await designer.revise(first, "Shorter titles", "req", criteria, [])

    second_prompt = llm.calls[1][-1]["content"]
    assert '"tc_id": "TC-M-006"' in second_prompt
    assert '"tc_id": "TC-M-001"' not in second_prompt
