"""Shapes of what the tools return. The MCP SDK publishes these as output schemas.

All money fields are text in dollars with two decimals ("9700.00"), never numbers.
"""  # REQ: FR-10

from pydantic import BaseModel, Field


class Participant(BaseModel):
    participant_id: str
    name: str


class ParticipantList(BaseModel):
    participants: list[Participant]


class Fund(BaseModel):
    fund_id: str
    name: str
    allocation_usd: str = Field(description='Fixed size of the fund in dollars, e.g. "10000.00".')


class FundList(BaseModel):
    funds: list[Fund]


class FundBalance(BaseModel):
    fund_id: str
    name: str
    allocation_usd: str = Field(description="Fixed size of the fund.")
    committed_usd: str = Field(description="Reserved by approved requests that are not paid yet.")
    paid_usd: str = Field(description="Paid out.")
    available_usd: str = Field(description="Still free to approve: allocation - committed - paid.")


class FundingSummary(BaseModel):
    funds: list[FundBalance]


class Request(BaseModel):
    request_id: str
    status: str = Field(description="PENDING, APPROVED, REJECTED or PAID.")
    participant_id: str
    fund_id: str
    amount_usd: str = Field(description='Dollars with two decimals, e.g. "300.00".')
    purpose: str
    created_by: str
    created_at: str
    decided_by: str | None = Field(default=None, description="Staff ID of who approved or rejected.")
    decided_at: str | None = None
    reject_reason: str | None = None
    paid_by: str | None = None
    paid_at: str | None = None


class RequestResult(BaseModel):
    request: Request
    replayed: bool = Field(
        description="True if this call repeated an earlier one: nothing changed and no money moved."
    )


class RequestList(BaseModel):
    requests: list[Request]
