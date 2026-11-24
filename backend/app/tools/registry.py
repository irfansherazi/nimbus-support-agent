from typing import Any

from app.tools.account import UpdateAccountFieldArgs, update_account_field
from app.tools.base import ToolSpec
from app.tools.billing import IssueRefundArgs, ListInvoicesArgs, issue_refund, list_invoices_tool
from app.tools.identity import VerifyCustomerArgs, verify_customer
from app.tools.policies import SearchPoliciesArgs, search_policies
from app.tools.tickets import CreateEscalationTicketArgs, create_escalation_ticket


def build_registry() -> dict[str, ToolSpec]:
    specs = [
        ToolSpec(
            "verify_customer",
            "Verifying account & tier…",
            "Verify the customer with their account ID and 4-digit support PIN. Required before any account action.",
            VerifyCustomerArgs,
            verify_customer,
        ),
        ToolSpec(
            "search_policies",
            "Searching knowledge base…",
            "Search Nimbus help-centre policies and troubleshooting guides. Results are filtered to the verified "
            "customer's plan. Use for any policy, billing-rule or how-to question.",
            SearchPoliciesArgs,
            search_policies,
        ),
        ToolSpec(
            "list_invoices",
            "Finding invoices…",
            "List the verified customer's invoices with amounts, dates and what has been refunded.",
            ListInvoicesArgs,
            list_invoices_tool,
        ),
        ToolSpec(
            "issue_refund",
            "Issuing refund…",
            "Refund (part of) one invoice. Plan limits and windows are enforced by the system.",
            IssueRefundArgs,
            issue_refund,
        ),
        ToolSpec(
            "update_account_field",
            "Updating account…",
            "Change the verified customer's email, phone or billing contact. Nothing else can be changed here.",
            UpdateAccountFieldArgs,
            update_account_field,
        ),
        ToolSpec(
            "create_escalation_ticket",
            "Creating support ticket…",
            "Hand the conversation to a human specialist with a structured ticket.",
            CreateEscalationTicketArgs,
            create_escalation_ticket,
        ),
    ]
    return {s.name: s for s in specs}


def tool_schemas(registry: dict[str, ToolSpec]) -> list[dict[str, Any]]:
    """OpenAI function-calling schemas for bind_tools."""
    out = []
    for spec in registry.values():
        params = spec.args_model.model_json_schema()
        params.pop("title", None)
        params.setdefault("properties", {})
        out.append(
            {"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": params}}
        )
    return out
