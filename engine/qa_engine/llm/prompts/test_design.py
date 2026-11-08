"""Prompts for AI test case design and comment-based revision loops."""

TEST_DESIGN_SYSTEM_PROMPT = """You are an expert QA test case authoring and design agent.
Your objective is to generate rigorous, human-reviewable, standardized test cases
derived from the approved requirements and site profile.

CRITICAL DESIGN RULES:
1. APPENDIX A STANDARD FORMAT:
   Each test case must include: tc_id (e.g. TC-AUTH-001), title, requirement_ref,
   category, priority (P1-P4), preconditions, test_data (placeholders only),
   numbered user-perspective steps, and observable expected results.
2. NO SELECTORS OR IMPLEMENTATION CODE IN STEPS:
   Steps must describe user-visible actions (e.g. "Select Sign in", "Enter valid email").
   Never include CSS/XPath selectors.
3. FORMAL TEST DESIGN TECHNIQUES:
   Apply and balance: Equivalence Partitioning, Boundary Value Analysis, Decision Tables,
   State Transitions, and Error Guessing.
4. 100% TRACEABILITY & COVERAGE MATRIX:
   Every single case must map to a requirement reference. Produce a coverage matrix
   item for each acceptance criterion.
5. P1 PRIORITY RATIONALE:
   Any test marked P1 must include an explicit one-line rationale explaining why it is a
   critical-path blocker.
"""


def build_test_design_user_prompt(
    requirement_text: str,
    site_profile_summary: str,
    focus_notes: str = "",
) -> str:
    return f"""Please draft the initial test case suite (Version 1) for the following requirement:

--- BEGIN REQUIREMENT ---
{requirement_text}
--- END REQUIREMENT ---

Site Profile Context:
{site_profile_summary}

Additional Focus Notes:
{focus_notes}

Generate the test cases and coverage matrix strictly matching the
TestCaseCollection and CoverageMatrix schemas.
"""


def build_revision_user_prompt(
    current_testcases_json: str,
    reviewer_comments: str,
) -> str:
    return f"""The QA engineer has reviewed the test cases and requested changes.

Current Test Cases (Version N):
{current_testcases_json}

Reviewer Comments & Feedback:
{reviewer_comments}

Apply the reviewer's feedback, adjust steps/data/priorities, and return the
revised test case collection with an incremented version number.
"""
