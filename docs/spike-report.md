# Copilot SDK & Reasoning Layer Feasibility Spike Report (Phase 0)

**Date:** 2026-11-07  
**Status:** Completed  
**Objective:** Validate GitHub Copilot SDK (Python) technical preview assumptions, tool registration, deny-by-default permission handling, streaming capabilities, and define the `LLMProvider` contract.

---

## 1. Executive Summary

As identified in Section 6.4 of the Solution Design, the GitHub Copilot SDK for Python is in technical preview. It operates by interfacing with the underlying Copilot CLI over JSON-RPC. To prevent breaking changes from jeopardizing project stability, Phase 0 establishes an abstraction boundary (`LLMProvider`) and validates four critical technical dimensions:
1. Session management & JSON-RPC subprocess lifecycle.
2. Custom tool registration & Appendix C tool compatibility.
3. Permission request interception with **deny-by-default** enforcement.
4. Schema-enforced structured generation with Pydantic.

---

## 2. Key Findings & Technical Decisions

### Finding 1: The Copilot CLI Environment Dependency
* **Observation:** The Copilot SDK requires either the GitHub Copilot CLI with active GitHub authentication or a Bring-Your-Own-Key (BYOK) OpenAI-compatible endpoint.
* **Decision:**
  * The Python engine must not directly import or couple itself to `github-copilot-sdk`.
  * All reasoning interactions are mediated by an internal abstract interface: `qa_engine.llm.provider.LLMProvider`.
  * We provide two concrete implementations:
    1. `CopilotLLMProvider`: Interfaces with GitHub Copilot SDK / CLI when present and authorized.
    2. `MockLLMProvider`: Deterministic, offline provider for CI pipelines, contract testing, and local development without cloud token consumption.

### Finding 2: Permission Handling & Bounded Autonomy
* **Observation:** The Copilot SDK features an automated permission handler callback (`on_permission_request`). Default examples frequently use an insecure blanket-approve pattern (`return PermissionResult.ALLOW`).
* **Decision:**
  * Blanket approvals are strictly prohibited in the engine architecture.
  * The permission handler enforces a **deny-by-default** filter:
    * Rejects any tool name not explicitly registered in Appendix C.
    * Validates tool parameters against the current run's `scope.json` before approval.
    * Refuses any attempt to invoke shell commands, file writing outside the run folder, or network requests outside the allowed domain whitelist.

### Finding 3: Tool Interface Contracts (Appendix C)
* **Observation:** The reasoning model must interact with the application via 12 dedicated, typed tools rather than free-form execution:
  1. `read_requirement`
  2. `get_site_profile`
  3. `browser_navigate`
  4. `browser_snapshot`
  5. `browser_click`
  6. `browser_fill`
  7. `browser_select`
  8. `browser_press_key`
  9. `browser_wait_for`
  10. `browser_screenshot`
  11. `submit_analysis`
  12. `submit_testcases`
  13. `submit_scripts`
  14. `submit_investigation`
* **Decision:**
  * All tools are declared with Pydantic input models. Tool invocations serialize through `qa_engine.browser.tools` and `qa_engine.orchestrator` with argument redaction before logging.

### Finding 4: Streaming & Structured Output
* **Observation:** The UI requires progressive streaming (`message.stream`) during reasoning phases, but structured milestones (`card.show`) require guaranteed JSON syntax.
* **Decision:**
  * Analysis, test cases, and investigations must pass through Pydantic model validation.
  * In the event of malformed JSON from the model, a retry budget (max 2 attempts) prompts the model with the exact schema validation error without discarding prior context.

---

## 3. Abstract Interface Specification (`LLMProvider`)

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any, Dict, List, Optional
from pydantic import BaseModel

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters_schema: Dict[str, Any]

class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: Dict[str, Any]

class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None

class LLMProvider(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize connection to the reasoning engine/CLI."""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2
    ) -> LLMResponse:
        """Execute non-streaming chat turn with tool support."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2
    ) -> AsyncIterator[str]:
        """Stream assistant response text progressively."""
        pass
```

---

## 4. Phase 0 Exit Recommendation
* The abstraction layer protects the system from preview SDK changes.
* `MockLLMProvider` enables Phase 1 to proceed immediately without external network or subscription dependencies.
* **Phase 0 is declared complete.** Proceed to Phase 1 (Engine Core & Orchestrator).

