"""Unit tests for ActionClassifier (T8 controls)."""

from qa_engine.browser.policy import ActionClassifier, ActionRiskLevel


def test_safe_read_actions():
    res = ActionClassifier.classify_action(
        action_type="click",
        element_role="link",
        element_name="About Us",
        policy_mode="require_approval",
    )
    assert res.risk_level == ActionRiskLevel.SAFE_READ
    assert res.is_permitted is True
    assert res.requires_approval is False


def test_state_change_action_require_approval():
    res = ActionClassifier.classify_action(
        action_type="click",
        element_role="button",
        element_name="Submit Order",
        policy_mode="require_approval",
    )
    assert res.risk_level == ActionRiskLevel.STATE_CHANGE
    assert res.is_permitted is False
    assert res.requires_approval is True


def test_destructive_action_policies():
    # 1. Mode = require_approval
    res1 = ActionClassifier.classify_action(
        action_type="click",
        element_role="button",
        element_name="Delete Account Permanently",
        policy_mode="require_approval",
    )
    assert res1.risk_level == ActionRiskLevel.DESTRUCTIVE
    assert res1.is_permitted is False
    assert res1.requires_approval is True

    # 2. Mode = block
    res2 = ActionClassifier.classify_action(
        action_type="click",
        element_role="button",
        element_name="Delete Account Permanently",
        policy_mode="block",
    )
    assert res2.risk_level == ActionRiskLevel.DESTRUCTIVE
    assert res2.is_permitted is False
    assert res2.requires_approval is False
    assert "blocked by policy" in res2.reason

    # 3. Mode = allow
    res3 = ActionClassifier.classify_action(
        action_type="click",
        element_role="button",
        element_name="Delete Account Permanently",
        policy_mode="allow",
    )
    assert res3.risk_level == ActionRiskLevel.DESTRUCTIVE
    assert res3.is_permitted is True
    assert res3.requires_approval is False
