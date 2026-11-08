"""Unit tests for AI analysis Pydantic schemas."""

from qa_engine.llm.schemas import AmbiguityItem, ClarificationQuestion, RequirementAnalysis


def test_requirement_analysis_schema():
    analysis = RequirementAnalysis(
        summary="User Authentication Flow",
        in_scope=["Login with username and password", "Remember me session"],
        out_of_scope=["OAuth2 social logins"],
        ambiguities=[
            AmbiguityItem(
                reference_text="Account locked after several attempts",
                issue_description="The exact number of failed attempts is not specified.",
            )
        ],
        missing_information=["Session timeout duration in minutes"],
        regression_risks=["Password reset flow", "Session expiration in cart"],
        clarification_questions=[
            ClarificationQuestion(
                question_id="Q-AUTH-001",
                question_text=(
                    "How many consecutive failed login attempts should trigger account lockout?"
                ),
                context="Needed to write boundary value test cases for account locking.",
                options=["3 attempts", "5 attempts", "10 attempts"],
                answer_type="choice",
            )
        ],
    )

    json_str = analysis.model_dump_json()
    assert "Q-AUTH-001" in json_str
    assert "Account locked after several attempts" in json_str

    # Roundtrip validation
    loaded = RequirementAnalysis.model_validate_json(json_str)
    assert len(loaded.clarification_questions) == 1
    assert loaded.clarification_questions[0].options == ["3 attempts", "5 attempts", "10 attempts"]
