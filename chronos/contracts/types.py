"""ToolCall / ToolResult shared types. Stdlib only."""

from __future__ import annotations

import dataclasses
from typing import Any, Optional


@dataclasses.dataclass
class ToolCall:
    tool: str
    arguments: Any
    device_id: Optional[str] = None
    proposal_id: Optional[str] = None


@dataclasses.dataclass
class ToolResult:
    tool: str
    result: Any
    events: Any = None
    proposal_id: Optional[str] = None
