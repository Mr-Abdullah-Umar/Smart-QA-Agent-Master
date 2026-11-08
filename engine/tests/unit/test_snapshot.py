"""Unit tests for ARIA accessibility snapshot extraction and reference indexing."""

from qa_engine.browser.snapshot import AriaSnapshotExtractor


def test_aria_snapshot_reference_assignment():
    mock_ax_tree = {
        "role": "WebArea",
        "name": "Login Page",
        "children": [
            {"role": "heading", "name": "Please Sign In", "children": []},
            {"role": "textbox", "name": "Username", "value": "testuser", "children": []},
            {"role": "textbox", "name": "Password", "children": []},
            {"role": "checkbox", "name": "Remember Me", "checked": True, "children": []},
            {"role": "button", "name": "Sign In", "disabled": False, "children": []},
            {"role": "link", "name": "Forgot Password?", "children": []},
        ],
    }

    result = AriaSnapshotExtractor.build_snapshot(
        mock_ax_tree,
        url="https://staging.example.com/login",
        title="Login Page",
    )

    assert result.total_interactive_elements == 5
    assert "#1" in result.elements
    assert "#2" in result.elements
    assert "#3" in result.elements
    assert "#4" in result.elements
    assert "#5" in result.elements

    # Check element details
    user_input = result.elements["#1"]
    assert user_input.role == "textbox"
    assert user_input.name == "Username"

    remember_me = result.elements["#3"]
    assert remember_me.role == "checkbox"
    assert remember_me.checked is True

    btn = result.elements["#4"]
    assert btn.role == "button"
    assert btn.name == "Sign In"

    # Verify text representation includes references
    assert "[#1]" in result.text_representation
    assert "[#4]" in result.text_representation
    assert 'button "Sign In" [#4]' in result.text_representation
