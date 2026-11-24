from pydantic import BaseModel, EmailStr, Field

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class GroupIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)

class MemberIn(BaseModel):
    email: EmailStr

class ExpenseIn(BaseModel):
    description: str = Field(min_length=2, max_length=200)
    amount: float = Field(gt=0)
    paid_by: int
    split_between: list[int] = Field(min_length=1)

class SettlementIn(BaseModel):
    payer_id: int
    receiver_id: int
    amount: float = Field(gt=0)
