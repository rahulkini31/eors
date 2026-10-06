"""Strongly-typed Pydantic message models for the Microsoft Agent Framework (MAF) asynchronous message bus."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel




class SwarmResolutionResponse(BaseModel):
    """Final synthesized resolution returned by Planner across the multi-domain workflow."""
    user_query: str
    final_answer: str
    a2a_trace: List[Dict[str, Any]]
    is_shipped: bool
    tracking_number: Optional[str] = None
    session_id: str
    trace_id: Optional[str] = None
