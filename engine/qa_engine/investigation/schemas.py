"""Schemas for Root Cause Analysis (RCA) and Failure Investigation.

Implements Appendix B specifications:
- 7 mutually exclusive categories.
- Strict segregation of observed facts from speculative hypotheses.
- Mandatory verified evidence ID citations ([EV-001]) for every fact.
- Gate 2 human sign-off requirement for any classification as 'Product defect'.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    PRODUCT_DEFECT = "Product defect"
    AUTOMATION_ISSUE = "Automation issue"
    TEST_DATA_ISSUE = "Test data issue"
    ENVIRONMENT_FAILURE = "Environment issue"
    UNCLEAR_REQUIREMENT = "Unclear requirement"
    FLAKY = "Flaky"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


class InvestigationFact(BaseModel):
    statement: str
    evidence_id: str  # Must correspond to a verified on-disk evidence item, e.g. EV-001


class InvestigationHypothesis(BaseModel):
    hypothesis: str
    supporting_indicators: List[str] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    failure_id: str
    tc_id: str
    category: FailureCategory
    confidence: float = Field(ge=0.0, le=1.0)
    facts: List[InvestigationFact] = Field(default_factory=list)
    hypotheses: List[InvestigationHypothesis] = Field(default_factory=list)
    evidence_citations: List[str] = Field(default_factory=list)
    reproduction_steps: List[str] = Field(default_factory=list)
    recommended_action: str
    preventive_measure: str

    # Gate 2 controls: Product defect must be explicitly signed off by human
    requires_human_signoff: bool = False
    gate_2_signed_off: bool = False
    signed_off_by: Optional[str] = None
    signoff_notes: Optional[str] = None

