from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["md", "admin", "finance", "supervisor", "storekeeper", "hr"]


class LoginIn(BaseModel):
    email: str
    password: str


class DemoLoginIn(BaseModel):
    role: Role


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class UserCreate(BaseModel):
    email: str
    name: str
    role: Role
    branch: Optional[str] = None
    phone: Optional[str] = Field(None, description="Nigerian format, e.g. 0803 123 4567 or +234 803 123 4567")
    password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[Role] = None
    branch: Optional[str] = None
    phone: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)
