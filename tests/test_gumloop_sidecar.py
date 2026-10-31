from __future__ import annotations

import json
from pathlib import Path

from gumloop_sidecar import (
    build_hubspot_upsert_batch,
    build_retool_versioned_envelope,
    build_twenty_crm_payload,
    prepare_gumloop_lead_batch,
    reconcile_invoice_extraction,
)


def test_prepare_gumloop_lead_batch_dedupes_and_filters_noise() -> None:
    raw = [
        {
            "website": "https://www.Pineapple.ch/about",
            "companyName": "pineapple AG",
            "emails": ["noreply@sentry.io", "philipp.koch@pineapple.ch", "contact@pineapple.ch"],
            "techStack": ["Retool", "PostgreSQL", "Retool"],
            "description": "Swiss digital efficiency consultancy   with embedded analytics.",
            "countryCode": "ch",
        },
        {
            "domain": "pineapple.ch",
            "companyName": "Duplicate Entry",
            "email": "contact@pineapple.ch",
        },
        {
            "domain": "sentry.io",
            "companyName": "Noise Domain",
        },
    ]
    out = prepare_gumloop_lead_batch(raw, max_summary_chars=40)
    assert out["batch_size"] == 1
    assert out["skipped_duplicates"] == 1
    assert out["skipped_invalid"] == 1

    rec = out["records"][0]
    assert rec["domain"] == "pineapple.ch"
    assert rec["primary_email"] == "philipp.koch@pineapple.ch"
    assert rec["additional_emails"] == ["contact@pineapple.ch"]
    assert rec["tech_stack"] == ["PostgreSQL", "Retool"]
    assert len(rec["context_for_llm"]) <= 40
    assert len(rec["idempotency_key"]) == 24


def test_twenty_and_hubspot_crm_payload_builders() -> None:
    scored = {
        "domain": "wellbayt.com",
        "company_name": "Wellbayt",
        "primary_email": "ops@wellbayt.com",
        "contact_name": "Alvaro Zapata",
        "city": "Dubai",
        "country_code": "AE",
        "employees": 25,
        "icp_tier": "A",
        "icp_summary": "Corporate wellbeing platform scaling outbound automation",
    }
    twenty = build_twenty_crm_payload(scored)
    assert twenty["company"]["domainName"]["primaryLinkUrl"] == "https://wellbayt.com"
    assert twenty["company"]["idealCustomerProfile"] is True
    assert twenty["company"]["employees"] == 25
    assert twenty["person"] is not None
    assert twenty["person"]["name"] == {"firstName": "Alvaro", "lastName": "Zapata"}
    assert twenty["person"]["emails"]["primaryEmail"] == "ops@wellbayt.com"

    hs = build_hubspot_upsert_batch([scored])
    assert len(hs["inputs"]) == 1
    assert hs["inputs"][0]["idProperty"] == "domain"
    assert hs["inputs"][0]["id"] == "wellbayt.com"


def test_invoice_decimal_reconciliation_exact_and_mismatch() -> None:
    clean_invoice = {
        "invoice_number": "INV-2026-1031",
        "vendor_name": "Acme Cloud GmbH",
        "currency": "eur",
        "line_items": [
            {"description": "Managed Postgres", "quantity": 2, "unit_price": "149.95", "amount": "299.90"},
            {"description": "Dedicated Worker", "quantity": 1, "unit_price": "80.10", "amount": "80.10"},
        ],
        "tax_amount": "72.20",
        "discount_amount": "10.00",
        "total_amount": "442.20",
    }
    res_ok = reconcile_invoice_extraction(clean_invoice)
    assert res_ok["delta"] == "0.00"
    assert res_ok["requires_human_review"] is False

    hallucinated_invoice = {
        **clean_invoice,
        "total_amount": "442.25",
    }
    res_bad = reconcile_invoice_extraction(hallucinated_invoice)
    assert res_bad["delta"] == "0.05"
    assert res_bad["requires_human_review"] is True


def test_retool_versioned_envelope_and_blueprints_valid() -> None:
    env = build_retool_versioned_envelope(
        {"invoice_number": "INV-1", "delta": "0.05"},
        app_release="1.7.9",
        signing_secret="whsec_test_key",
    )
    assert env["app_release"] == "1.7.9"
    assert len(env["signature_sha256"]) == 64

    bp_path = Path(__file__).resolve().parents[1] / "blueprints" / "gumloop_3_production_flows.json"
    bp = json.loads(bp_path.read_text(encoding="utf-8"))
    assert len(bp["flows"]) == 3
