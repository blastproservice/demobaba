from pydantic import BaseModel, Field
from typing import Optional


class AdminManualChatPayload(BaseModel):
    session_id: int
    tele_id: int
    message: str


class ManualTransactionPayload(BaseModel):
    account_id: int
    category_id: int
    transaction_type: str
    amount: float
    description: Optional[str] = ""


class TransferPayload(BaseModel):
    from_account_id: int
    to_account_id: int
    amount_out: float
    amount_in: float
    exchange_rate: float = 1.0
    description: str = "Transfer antar rekening"


class PurchaseOrderPayload(BaseModel):
    account_id: int
    supplier_name: Optional[str] = ""
    items: list[dict] = Field(default_factory=list)


class ChatSendPayload(BaseModel):
    tele_id: int
    message: str


class ChatResetPayload(BaseModel):
    tele_id: int


class ChatFeedbackPayload(BaseModel):
    tele_id: int
    rating: int
    complaint: Optional[str] = ""

class StockMutationPayload(BaseModel):
    product_id: int
    mutation_type: str = Field(..., description="'IN' untuk tambah, 'OUT' untuk kurang")
    quantity: int = Field(..., gt=0, description="Kuantitas harus lebih dari 0")
    reason: str = Field(..., min_length=3, description="Alasan mutasi wajib diisi")