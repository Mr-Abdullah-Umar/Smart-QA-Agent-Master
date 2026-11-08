"""Pydantic schemas for structured AI reasoning and analysis.

Enforces Section 8.3:
Structured analysis output requiring explicit clarification questions
to prevent the AI from guessing or silently inventing missing requirements.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class AmbiguityItem(BaseModel):
    reference_text: str = Field(description="Exact quote or phrase from the requirement")
    issue_description: str = Field(description="Why this statement is ambiguous or contradictory")


class ClarificationQuestion(BaseModel):
    question_id: str = Field(description="Unique identifier, e.g. Q-001")
    question_text: str = Field(description="Direct question posed to the QA engineer")
    context: str = Field(description="Why this information is needed for test design")
    options: Optional[List[str]] = Field(
        default=None, description="Suggested answers if applicable"
    )
    answer_type: str = Field(default="text", description="Type: 'choice' or 'text'")


class RequirementAnalysis(BaseModel):
    summary: str = Field(description="High-level understanding of the feature under test")
    in_scope: List[str] = Field(
        default_factory=list, description="Explicit functional behaviors in scope"
    )
    out_of_scope: List[str] = Field(
        default_factory=list, description="Behaviors explicitly excluded"
    )
    ambiguities: List[AmbiguityItem] = Field(
        default_factory=list,
        description="Contradictions or ambiguities identified in the requirement",
    )
    missing_information: List[str] = Field(
        default_factory=list, description="Unspecified boundary limits, error states, or user roles"
    )
    regression_risks: List[str] = Field(
        default_factory=list, description="Associated system areas vulnerable to regression"
    )
    clarification_questions: List[ClarificationQuestion] = Field(
        default_factory=list,
        description=(
            "Mandatory questions for the engineer. Unknowns must NEVER be invented as requirements."
        ),
    )
