"""
Bridge between Apify B2B/E-Commerce Actor datasets and Gumloop Webhook Triggers.

Prevents duplicate LLM credit spend in Gumloop Subflows by normalizing company
domains, stripping noisy HTML/tracking fields, capping per-record token length,
and attaching deterministic SHA-256 idempotency keys before invoking Gumloop.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

DISPOSABLE_OR_NOISE_DOMAINS = {
    "example.com",
    "sentry.io",
    "wixpress.com",
    "cloudflare.com",
    "domain.com",
    "test.com",
}

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,12}$")


def normalize_domain(raw_url_or_domain: str) -> str:
    val = (raw_url_or_domain or "").strip().lower()
    if not val:
        return ""
    if "://" not in val:
        val = "https://" + val
    parsed = urlparse(val)
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def clean_email(raw_email: str) -> str | None:
    em = (raw_email or "").strip().lower()
    if not em or not EMAIL_RE.match(em):
        return None
    dom = em.split("@")[-1]
    if dom in DISPOSABLE_OR_NOISE_DOMAINS or dom.endswith((".png", ".jpg", ".svg", ".webp")):
        return None
    return em


def prepare_gumloop_lead_batch(
    raw_items: list[dict[str, Any]],
    *,
    seen_domains: set[str] | None = None,
    max_summary_chars: int = 900,
    actor_source: str = "thanh81646/apify-b2b-lead-and-contact-enricher",
) -> dict[str, Any]:
    """
    Deduplicates and normalizes raw Apify dataset items into a strict,
    credit-efficient payload for a Gumloop Webhook Trigger + Subflow loop.
    """
    dedupe_set: set[str] = set(seen_domains or set())
    accepted: list[dict[str, Any]] = []
    skipped_duplicates = 0
    skipped_invalid = 0

    for item in raw_items:
        domain = normalize_domain(str(item.get("domain") or item.get("website") or item.get("url") or ""))
        if not domain or domain in DISPOSABLE_OR_NOISE_DOMAINS:
            skipped_invalid += 1
            continue
        if domain in dedupe_set:
            skipped_duplicates += 1
            continue
        dedupe_set.add(domain)

        raw_emails = item.get("emails") or []
        if isinstance(raw_emails, str):
            raw_emails = [raw_emails]
        if item.get("email"):
            raw_emails = [item["email"], *raw_emails]

        valid_emails: list[str] = []
        for candidate in raw_emails:
            cleaned = clean_email(str(candidate))
            if cleaned and cleaned not in valid_emails:
                valid_emails.append(cleaned)

        raw_summary = re.sub(r"\s+", " ", str(item.get("description") or item.get("about") or "")).strip()
        trimmed_summary = raw_summary[:max_summary_chars]

        tech_signals = sorted(
            {str(t).strip() for t in (item.get("techStack") or item.get("technologies") or []) if str(t).strip()}
        )

        idem_seed = f"{actor_source}:{domain}:{valid_emails[0] if valid_emails else 'no-email'}"
        idem_key = hashlib.sha256(idem_seed.encode("utf-8")).hexdigest()[:24]

        accepted.append(
            {
                "idempotency_key": idem_key,
                "actor_source": actor_source,
                "company_name": str(item.get("companyName") or item.get("title") or domain).strip(),
                "domain": domain,
                "website_url": f"https://{domain}",
                "primary_email": valid_emails[0] if valid_emails else None,
                "additional_emails": valid_emails[1:5],
                "phone": str(item.get("phone") or "").strip() or None,
                "city": str(item.get("city") or "").strip() or None,
                "country_code": str(item.get("countryCode") or "").strip().upper() or None,
                "tech_stack": tech_signals[:12],
                "context_for_llm": trimmed_summary,
            }
        )

    return {
        "batch_size": len(accepted),
        "skipped_duplicates": skipped_duplicates,
        "skipped_invalid": skipped_invalid,
        "records": accepted,
    }
