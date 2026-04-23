"""
Uniform error model for the MCP surface.

Rationale (diary 11/13): enforcing ``SAVE_REQUIRES_RELOAD`` at the protocol
level prevents the whole class of connector-visibility-after-save bugs.
Each error code is enumerated so clients can switch on the code rather
than parsing human-readable messages.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(str, Enum):
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    DOC_NOT_OPEN = "DOC_NOT_OPEN"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    CONNECTOR_GLUE_INVALID = "CONNECTOR_GLUE_INVALID"
    SAVE_REQUIRES_RELOAD = "SAVE_REQUIRES_RELOAD"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    INVALID_TYPE = "INVALID_TYPE"
    PARSE_FAILED = "PARSE_FAILED"
    TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    SELECTOR_NOT_FOUND = "SELECTOR_NOT_FOUND"
    INVALID_OOXML = "INVALID_OOXML"
    RENDER_FAILED = "RENDER_FAILED"
    LIBRARY_EMPTY = "LIBRARY_EMPTY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


@dataclass
class VisioToolError(Exception):
    """Machine-readable error envelope for every MCP tool response."""
    code: ErrorCode
    message: str
    hint: Optional[str] = None
    recoverable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # keep Exception .args populated
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["code"] = self.code.value
        return payload
