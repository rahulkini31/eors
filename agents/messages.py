"""Strongly-typed Pydantic message models for the Microsoft Agent Framework (MAF) asynchronous message bus."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class UserQueryMessage(BaseModel):
    """Inbound user question directed to the Gemini Planner."""
    query: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ERPOrderLookupRequest(BaseModel):
    """Message sent by Planner to ERP_Agent requesting order resolution in db-01-dev."""
    customer_query: str
    item_query: str
    correlation_id: str
    prompt_context: str = ""


class ERPOrderLookupResponse(BaseModel):
    """Message returned by ERP_Agent to Planner containing commercial order details."""
    order_id: str
    po_number: str
    customer_name: str
    item_sku: str
    quantity: int
    order_status: str
    payment_status: str
    raw_records: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_id: str = ""
    error: Optional[str] = None


class WMSExecutionLookupRequest(BaseModel):
    """Message sent by Planner to WMS_Agent with ERP reference to trace physical execution."""
    erp_order_ref: str
    customer_po_ref: Optional[str] = None
    correlation_id: str = ""
    prompt_question: str = ""


class WMSExecutionLookupResponse(BaseModel):
    """Message returned by WMS_Agent to Planner with physical pick & handling unit data."""
    pick_id: str
    handling_unit_id: str
    status_id: int
    status_description: str
    staged_dock_code: Optional[str] = None
    raw_records: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_id: str = ""
    error: Optional[str] = None


class TMSDispatchLookupRequest(BaseModel):
    """Message sent by Planner to TMS_Agent with Handling Unit reference to trace carrier manifest."""
    handling_unit_ref: str
    correlation_id: str = ""
    prompt_question: str = ""


class TMSDispatchLookupResponse(BaseModel):
    """Message returned by TMS_Agent to Planner with tracking and carrier dispatch details."""
    manifest_id: str
    carrier_name: str
    tracking_number: str
    waybill_number: str
    shipment_status: str
    dispatched_at: Optional[str] = None
    estimated_delivery: Optional[str] = None
    raw_records: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_id: str = ""
    error: Optional[str] = None


class SwarmResolutionResponse(BaseModel):
    """Final synthesized resolution returned by Planner across the multi-domain workflow."""
    user_query: str
    final_answer: str
    a2a_trace: List[Dict[str, Any]]
    is_shipped: bool
    tracking_number: Optional[str] = None
    session_id: str
