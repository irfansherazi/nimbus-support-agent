from typing import Any

from pydantic import BaseModel, Field

from app.store.customers import check_pin, get_customer
from app.store.sessions import incr_verify_failures, set_customer
from app.tools.base import ToolEnv, ToolError

MAX_VERIFY_FAILURES = 3


class VerifyCustomerArgs(BaseModel):
    account_id: str = Field(description="Customer account ID, e.g. C-1001")
    pin: str = Field(description="The customer's 4-digit support PIN")


async def verify_customer(env: ToolEnv, args: VerifyCustomerArgs) -> dict[str, Any]:
    if env.session.verify_failures >= MAX_VERIFY_FAILURES:
        raise ToolError(
            "VERIFICATION_LOCKED", "Too many failed attempts in this conversation.", hint="offer_escalation"
        )
    account_id = args.account_id.strip().upper().replace(" ", "")
    async with env.pool.connection() as conn:
        customer = await get_customer(conn, account_id)
        # An unknown account and a wrong PIN look identical, so the tool can't be used to probe account IDs.
        if customer is None or not await check_pin(conn, account_id, args.pin.strip()):
            env.session.verify_failures = await incr_verify_failures(conn, env.session.id)
            if env.session.verify_failures >= MAX_VERIFY_FAILURES:
                raise ToolError("VERIFICATION_LOCKED", "Too many failed attempts.", hint="offer_escalation")
            left = MAX_VERIFY_FAILURES - env.session.verify_failures
            raise ToolError("INVALID_CREDENTIALS", f"Account ID or PIN did not match. {left} attempt(s) left.")
        await set_customer(conn, env.session.id, customer.id)
    env.customer = customer
    env.session.customer_id = customer.id
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "tier": customer.tier,
        "contract_status": customer.contract_status,
    }
