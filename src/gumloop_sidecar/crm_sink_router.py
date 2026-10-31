"""
Downstream deterministic routers for Gumloop AI structured outputs:
1. Twenty CRM standard Company + Person REST payload builder.
2. HubSpot CRM v3 batch upsert payload builder.
3. Exact-cent Decimal invoice extraction verifier + versioned Retool approval envelope.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def _to_cents_decimal(val: Any) -> Decimal:
    return Decimal(str(val or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_twenty_crm_payload(enriched_lead: dict[str, Any]) -> dict[str, Any]:
    """Formats a Gumloop ICP-scored lead for Twenty CRM `/rest/companies` and `/rest/people`."""
    domain = str(enriched_lead.get("domain") or "").strip().lower()
    if not domain:
        raise ValueError("enriched_lead requires a non-empty domain")

    company_name = str(enriched_lead.get("company_name") or domain).strip()
    icp_tier = str(enriched_lead.get("icp_tier") or "B").upper()
    icp_reason = str(enriched_lead.get("icp_summary") or "").strip()

    company_body: dict[str, Any] = {
        "name": company_name,
        "domainName": {
            "primaryLinkUrl": f"https://{domain}",
            "primaryLinkLabel": domain,
        },
        "idealCustomerProfile": icp_tier == "A",
        "address": {
            "addressCity": str(enriched_lead.get("city") or ""),
            "addressCountry": str(enriched_lead.get("country_code") or ""),
        },
    }
    if enriched_lead.get("employees") is not None:
        company_body["employees"] = int(enriched_lead["employees"])

    person_body: dict[str, Any] | None = None
    primary_email = enriched_lead.get("primary_email")
    if primary_email:
        full_name = str(enriched_lead.get("contact_name") or "Operations Team").strip().split(" ", 1)
        first_name = full_name[0]
        last_name = full_name[1] if len(full_name) > 1 else ""
        person_body = {
            "name": {"firstName": first_name, "lastName": last_name},
            "emails": {
                "primaryEmail": primary_email,
                "additionalEmails": list(enriched_lead.get("additional_emails") or []),
            },
            "jobTitle": str(enriched_lead.get("job_title") or icp_reason[:80]),
        }

    return {"company": company_body, "person": person_body}


def build_hubspot_upsert_batch(enriched_leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Formats Gumloop scored leads for HubSpot `/crm/v3/objects/companies/batch/upsert`."""
    inputs: list[dict[str, Any]] = []
    for lead in enriched_leads:
        domain = str(lead.get("domain") or "").strip().lower()
        if not domain:
            continue
        inputs.append(
            {
                "idProperty": "domain",
                "id": domain,
                "properties": {
                    "domain": domain,
                    "name": str(lead.get("company_name") or domain).strip(),
                    "description": str(lead.get("icp_summary") or "").strip()[:500],
                    "lifecyclestage": "lead",
                },
            }
        )
    return {"inputs": inputs}


def reconcile_invoice_extraction(extracted: dict[str, Any]) -> dict[str, Any]:
    """
    Verifies LLM-extracted invoice line items + tax against invoice total using
    exact Decimal arithmetic before routing to accounting or Retool human review.
    """
    line_items = extracted.get("line_items") or []
    computed_subtotal = Decimal("0.00")
    normalized_lines: list[dict[str, str]] = []

    for idx, item in enumerate(line_items, 1):
        qty = Decimal(str(item.get("quantity", 1)))
        unit_price = _to_cents_decimal(item.get("unit_price", "0"))
        expected_line = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stated_line = _to_cents_decimal(item.get("amount", expected_line))
        computed_subtotal += stated_line
        normalized_lines.append(
            {
                "line_number": str(idx),
                "description": str(item.get("description") or f"Item {idx}"),
                "quantity": str(qty),
                "unit_price": f"{unit_price:.2f}",
                "amount": f"{stated_line:.2f}",
                "line_math_ok": str(expected_line == stated_line).lower(),
            }
        )

    tax = _to_cents_decimal(extracted.get("tax_amount", "0"))
    discount = _to_cents_decimal(extracted.get("discount_amount", "0"))
    stated_total = _to_cents_decimal(extracted.get("total_amount", "0"))
    computed_total = computed_subtotal + tax - discount
    delta = stated_total - computed_total

    all_lines_ok = all(ln["line_math_ok"] == "true" for ln in normalized_lines)
    requires_human_review = (delta != Decimal("0.00")) or (not all_lines_ok) or (not normalized_lines)

    return {
        "invoice_number": str(extracted.get("invoice_number") or "UNKNOWN"),
        "vendor_name": str(extracted.get("vendor_name") or "UNKNOWN"),
        "currency": str(extracted.get("currency") or "USD").upper(),
        "computed_subtotal": f"{computed_subtotal:.2f}",
        "tax_amount": f"{tax:.2f}",
        "discount_amount": f"{discount:.2f}",
        "computed_total": f"{computed_total:.2f}",
        "stated_total": f"{stated_total:.2f}",
        "delta": f"{delta:.2f}",
        "requires_human_review": requires_human_review,
        "line_items": normalized_lines,
    }


def build_retool_versioned_envelope(
    payload: dict[str, Any],
    *,
    app_release: str,
    signing_secret: str,
    workflow_name: str = "gumloop_human_review_queue",
) -> dict[str, Any]:
    """
    Wraps a Gumloop webhook payload with explicit `app_release` schema routing
    and HMAC-SHA256 signature for Retool Workflows and Embedded Retool Apps.
    """
    canonical_body = json.dumps(
        {"workflow": workflow_name, "app_release": app_release, "data": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        canonical_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "workflow": workflow_name,
        "app_release": app_release,
        "signature_sha256": signature,
        "data": payload,
    }
