# Veto — transaction-monitoring closer

A policy-bound alert closer. The closer proposes; a **challenger that cannot vote CLOSE** vetoes. It will miss some closable cases. It should not wrongfully close a mule.

Rules first. A language model is used only on leftover ask-a-question cases, and only if `XAI_API_KEY` is set. Five runs match: temperature 0, seed 1, and a reply cache.

## How to run

From this directory (or with this file as the executable):

```
./run <institution_folder> <output_file>
```

Example from the hackathon root:

```
system/run institutions/bank output/bank.jsonl
```

The evaluator passes full paths and starts inside `system/`. The script puts its own directory on `sys.path` and does not depend on the working directory.

A run of 200 cases finishes in well under a second on a laptop (~1s for 1,000). Cost: $0.

## How it decides

```
load folder → pack case → parse evidence
  → Challenger A (hard escalate; also blocks RFI)
  → Gate 1 evidence match (per alert)
  → Gate 2 SOP (downgrade CLOSE → RFI only)
  → Challenger B (kill remaining CLOSE; may RFI → ESCALATE)
  → residual RFI by unexplained rule
  → emit allow-listed JSON
```

A case is CLOSE only if **every** alert has a Gate-1 explanation, SOP does not downgrade, and neither challenger fires.

### Gate 1

Markdown evidence is parsed for sterling amounts, payees, dates, officer/PSC rows and gift dates of birth. Amounts are matched **exactly** to `amount_gbp` (never the foreign `amount`) and joined to a counterparty name or a named role column. Amount-only hits are rejected.

Typical closes: invoice/payee/date, collection reports, takings books, gift letters, solicitor/insurer/loan/completion documents, own-account statements, group charts, list matches where the register or gift letter shows a **different** person.

`WITHIN_PROFILE` is not used as a dump code. Previous reviews are never a close ground.

### Gate 2

- Own-account transfers that take TM01 activity to **5×** declared income/volume → `RFI_UPDATED_PROFILE`. A documented event that *is* the excess stays CLOSE.
- Payments/FX: ≥ £10,000 to anyone other than the client needs an invoice or contract that matches the payment. A group chart or own-account statement does not release it. An invoice that only says “payable in instalments”, with no stage amounts, is not a close.

### Challenger A (cannot be overridden by an invoice)

- Sending-bank fraud report or mule chat → `ESC_MULE_ACTIVITY`
- Staff note about staying under a threshold → `ESC_STRUCTURING`
- Unwilling to explain a Lebanon routing → `ESC_HIGH_RISK_CORRIDOR`
- Shared device or higher-risk login country → `ESC_ACCOUNT_MISUSE`
- TM22 officer whose birth month-year matches the list and who still controlled at payment date → `ESC_LISTED_PARTY`
- Gift letter date of birth equals the listed person → `ESC_LISTED_PARTY`

Once there is suspicion, the system escalates. It does not RFI the customer (tipping-off).

### Challenger B

Unexplained TM06 → `ESC_HIGH_RISK_CORRIDOR`. Unexplained TM10 → `ESC_EARLY_REDEMPTION`. TM02+TM04 without collection documents → `ESC_PASS_THROUGH`. Invoice goods/currency mismatch → `ESC_INVOICE_MISMATCH`.

### Residual RFI

If nothing is suspicious and some alert is unexplained: a **specific** ask (`RFI_SOURCE_OF_FUNDS`, `RFI_PURPOSE_DOCUMENTS`, `RFI_BUSINESS_RECORDS`, `RFI_COUNTERPARTY_DETAILS`, `RFI_UPDATED_PROFILE`).

Reasons are filled templates (customer name, amount, counterparty, document id). Evidence IDs are filtered to ids that exist in the institution folder.

## Model

Rules decide every case that has a document match, a suspicion signal, or a hard SOP downgrade. Those never call a model.

Leftover cases (nothing suspicious, paperwork does not explain the alert) are an RFI. If `XAI_API_KEY` is set, that residual is sent to `https://api.x.ai/v1/chat/completions`, model `grok-4.20-0309-non-reasoning` unless `XAI_MODEL` is set. Temperature 0, seed 1. The non-reasoning model is deliberate: it does not sample a chain of thought, so repeats stay stable. The model may close, ask, or escalate. A close is kept only if it cites a document or list ID that exists in the folder. Invented IDs are discarded and the rule RFI stands. Each reply is cached under `system/.llm_cache/` keyed by the exact request, so five judging runs in the same directory return the same verdict, reason code, reason, and evidence. If the key is unset, the rule RFI is the answer.
