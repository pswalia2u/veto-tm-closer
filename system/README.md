# Veto — transaction-monitoring closer

A policy-bound alert closer. The closer proposes; a **challenger that cannot vote CLOSE** vetoes. It will miss some closable cases. It should not wrongfully close a mule.

No language model. Standard-library Python 3 only. Same bytes every run.

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
- Payments/FX: ≥ £10,000 to anyone other than the client needs an invoice/contract on file before CLOSE.

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

None. Deterministic rules and parsers only. Temperature is irrelevant. Five runs produce identical verdicts, reason codes, reasons and evidence.
