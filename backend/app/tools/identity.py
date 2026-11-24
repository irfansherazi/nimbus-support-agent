import re
from typing import Any

from pydantic import BaseModel, Field

from app.store.customers import check_pin, get_customer
from app.store.sessions import incr_verify_failures, set_customer
from app.tools.base import ToolEnv, ToolError

MAX_VERIFY_FAILURES = 3
_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip


def _spoken_digits(text: str) -> str:
    """Digits from text that may come from speech-to-text: '4 3 2 1', '4321.', 'four three two one'."""
    words = re.findall(r"[a-z]+|\d", text.lower())
    return "".join(_DIGIT_WORDS.get(w, w if w.isdigit() else "") for w in words)


def normalize_account_id(raw: str) -> str:
    """'C1001', 'c 1001', 'C–1001' and 'C.1001' all mean C-1001 (speech-to-text drops or mangles the hyphen)."""
    m = re.match(r"^\s*([a-z])\W*(.*)$", raw.strip(), re.IGNORECASE)
    if not m:
        return raw.strip().upper()
    digits = _spoken_digits(m.group(2))
    return f"{m.group(1).upper()}-{digits}" if digits else raw.strip().upper()


def normalize_pin(raw: str) -> str:
    return _spoken_digits(raw) or raw.strip()


class VerifyCustomerArgs(BaseModel):
    account_id: str = Field(description="Customer account ID, e.g. C-1001")
    pin: str = Field(description="The customer's 4-digit support PIN")


async def verify_customer(env: ToolEnv, args: VerifyCustomerArgs) -> dict[str, Any]:
    if env.session.verify_failures >= MAX_VERIFY_FAILURES:
        raise ToolError(
            "VERIFICATION_LOCKED", "Too many failed attempts in this conversation.", hint="offer_escalation"
        )
    account_id = normalize_account_id(args.account_id)
    async with env.pool.connection() as conn:
        customer = await get_customer(conn, account_id)
        # An unknown account and a wrong PIN look identical, so the tool can't be used to probe account IDs.
        if customer is None or not await check_pin(conn, account_id, normalize_pin(args.pin)):
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
