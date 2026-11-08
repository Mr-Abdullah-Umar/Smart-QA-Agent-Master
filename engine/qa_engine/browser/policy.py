"""Action classification and destructive action governance.

Enforces T8 controls: prevents excessive agency and unauthorized data destruction
by classifying interactive actions into read vs destructive/state-changing operations.
"""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ActionRiskLevel(str, Enum):
    SAFE_READ = "SAFE_READ"
    STATE_CHANGE = "STATE_CHANGE"
    DESTRUCTIVE = "DESTRUCTIVE"


class ActionPolicyResult(BaseModel):
    risk_level: ActionRiskLevel
    action_type: str
    target_description: str
    is_permitted: bool
    requires_approval: bool
    reason: Optional[str] = None


class ActionClassifier:
    """Classifies browser interactions based on target element semantics and attributes."""

    DESTRUCTIVE_KEYWORDS = re.compile(
        r"(?i)\b(delete|remove|destroy|purge|drop|wipe|reset|terminate|cancel account|clear all)\b"
    )
    STATE_CHANGE_KEYWORDS = re.compile(
        r"(?i)\b(submit|save|create|update|pay|checkout|purchase|order|confirm order|post|send)\b"
    )

    @classmethod
    def classify_action(
        cls,
        action_type: str,  # "click", "fill", "navigate", etc.
        element_role: str,  # "button", "link", "textbox", etc.
        element_name: str,  # Accessible name e.g. "Delete User"
        policy_mode: str = "require_approval",  # "allow", "require_approval", "block"
    ) -> ActionPolicyResult:
        combined_text = f"{action_type} {element_role} {element_name}"

        # 1. Check for overtly destructive keywords
        if cls.DESTRUCTIVE_KEYWORDS.search(combined_text):
            if policy_mode == "block":
                return ActionPolicyResult(
                    risk_level=ActionRiskLevel.DESTRUCTIVE,
                    action_type=action_type,
                    target_description=combined_text,
                    is_permitted=False,
                    requires_approval=False,
                    reason="Destructive action blocked by policy.",
                )
            if policy_mode == "require_approval":
                return ActionPolicyResult(
                    risk_level=ActionRiskLevel.DESTRUCTIVE,
                    action_type=action_type,
                    target_description=combined_text,
                    is_permitted=False,
                    requires_approval=True,
                    reason="Destructive action requires explicit user approval on decision card.",
                )
            return ActionPolicyResult(
                risk_level=ActionRiskLevel.DESTRUCTIVE,
                action_type=action_type,
                target_description=combined_text,
                is_permitted=True,
                requires_approval=False,
            )

        # 2. Check for general state changes (form submissions, checkout, purchase)
        if cls.STATE_CHANGE_KEYWORDS.search(combined_text) or element_role in ("button", "submit"):
            if policy_mode == "require_approval" and cls.STATE_CHANGE_KEYWORDS.search(
                combined_text
            ):
                return ActionPolicyResult(
                    risk_level=ActionRiskLevel.STATE_CHANGE,
                    action_type=action_type,
                    target_description=combined_text,
                    is_permitted=False,
                    requires_approval=True,
                    reason=(
                        "State-changing action requires confirmation under current scope policy."
                    ),
                )
            return ActionPolicyResult(
                risk_level=ActionRiskLevel.STATE_CHANGE,
                action_type=action_type,
                target_description=combined_text,
                is_permitted=True,
                requires_approval=False,
            )

        # 3. Default to safe read action
        return ActionPolicyResult(
            risk_level=ActionRiskLevel.SAFE_READ,
            action_type=action_type,
            target_description=combined_text,
            is_permitted=True,
            requires_approval=False,
        )
