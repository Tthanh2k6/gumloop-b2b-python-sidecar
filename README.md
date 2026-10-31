# gumloop-b2b-python-sidecar

Deterministic Python companion utilities and reference flow blueprints for production **Gumloop** AI workflows connected to **Apify Actors**, **Twenty CRM**, **HubSpot**, and **Retool** human-in-the-loop approval queues.

## Why Pair Gumloop Flows With a Thin Python Sidecar

Gumloop handles multi-step AI orchestration, PDF extraction, and subflow routing cleanly. In B2B production deployments, three deterministic guardrails prevent wasted AI credits and downstream CRM corruption:

1. **Pre-Flow Domain Deduplication & Token Budgeting (`apify_gumloop_bridge.py`):** Normalizes domains from Apify scraper datasets (`thanh81646/apify-b2b-lead-and-contact-enricher`), removes noise emails (`sentry.io`, asset filenames), trims raw page copy to a strict character budget, and assigns a 24-character SHA-256 `idempotency_key` before invoking a Gumloop Webhook Trigger.
2. **Exact-Cent Invoice Math Verification (`reconcile_invoice_extraction`):** Validates LLM-extracted invoice line items, tax, and discounts using Python `decimal.Decimal` (`ROUND_HALF_UP`). Invoices with `delta == 0.00` pass straight through; any 1-cent discrepancy sets `requires_human_review = True`.
3. **CRM & Versioned Retool Routing (`crm_sink_router.py`):** Formats validated outputs for Twenty CRM (`/rest/companies` + `/rest/people`), HubSpot v3 batch upserts, and HMAC-signed Retool Workflow webhooks pinned to explicit `app_release` schema versions.

## Reference Blueprints Included

See `blueprints/gumloop_3_production_flows.json`:
- `flow_01_apify_b2b_to_crm`: Apify B2B Lead Enricher -> Dedupe Sidecar -> Gumloop ICP Scorer -> Twenty CRM / HubSpot.
- `flow_02_invoice_ocr_to_retool`: Inbound PDF Invoice -> Gumloop Extract Data -> Decimal Reconciliation -> Retool Approval Queue.
- `flow_03_ecommerce_price_intelligence`: Apify E-Commerce Price Tracker -> Gumloop Margin Delta Analyzer -> PostgreSQL & Slack.

## Local Verification

```bash
pip install -e ".[dev]"
pytest -v
```

## Author

- **Trung Thanh Tran** (`ttrungthanh90@gmail.com`)
- Portfolio: https://trungthanhtran.vercel.app
- Commercial Apify Actors: https://apify.com/thanh81646
- GitHub: https://github.com/Tthanh2k6
