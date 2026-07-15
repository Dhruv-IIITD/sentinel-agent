"""Pydantic argument schemas for every tool.

These are (a) sent to the model so it emits well-formed tool calls, and (b) used
as an input-validation guardrail before execution — malformed args are rejected
before any side effect runs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GetOrderArgs(BaseModel):
    order_id: int = Field(description="The order number, e.g. 4471")


class CheckInventoryArgs(BaseModel):
    sku: str = Field(description="The product SKU to check")


class TrackShipmentArgs(BaseModel):
    order_id: int


class UpdateAddressArgs(BaseModel):
    order_id: int
    new_address: str = Field(description="The full replacement shipping address")


class AddNoteArgs(BaseModel):
    order_id: int
    note: str


class IssueRefundArgs(BaseModel):
    order_id: int
    amount: float = Field(gt=0, description="Refund amount in USD")
    reason: str = ""


class CancelOrderArgs(BaseModel):
    order_id: int
    reason: str = ""


class ApplyCreditArgs(BaseModel):
    customer_id: int
    amount: float = Field(gt=0, description="Store credit amount in USD")
    reason: str = ""
