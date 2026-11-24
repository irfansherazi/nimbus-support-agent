import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.store.customers import update_customer_field
from app.tools.base import ToolEnv, ToolError

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[0-9][0-9 ()\-]{6,18}[0-9]$")


class UpdateAccountFieldArgs(BaseModel):
    field: Literal["email", "phone", "billing_contact"] = Field(description="The only fields that can be changed")
    value: str = Field(description="The new value")


def _validate(field: str, value: str) -> str:
    value = value.strip()
    if field == "email" and not _EMAIL.match(value):
        raise ToolError("INVALID_VALUE", "That doesn't look like a valid email address.")
    if field == "phone" and not _PHONE.match(value):
        raise ToolError("INVALID_VALUE", "That doesn't look like a valid phone number.")
    if field == "billing_contact" and not (0 < len(value) <= 120):
        raise ToolError("INVALID_VALUE", "Billing contact must be 1-120 characters.")
    return value


async def update_account_field(env: ToolEnv, args: UpdateAccountFieldArgs) -> dict[str, Any]:
    customer = env.require_customer()
    value = _validate(args.field, args.value)
    async with env.pool.connection() as conn:
        await update_customer_field(conn, customer.id, args.field, value)
    return {"field": args.field, "value": value}
