# Veto — how it decides

A program that closes bank alerts only when the paperwork explains them, and refuses to close anything that looks like crime.

## The job

Banks flag odd payments. A person still has to look at every flag. Three choices:

- **Close** when a document explains every alert.
- **Ask one question** when nothing looks criminal yet and one document would settle it.
- **Send it upstairs** when it looks like crime. Do not ask the customer. That warns them, which is an offence.

One case, one verdict, even if several rules fired. The reason names this case's people, amounts, and document IDs.

## Four steps

1. **Documents.** Exact pounds (`amount_gbp`, not the foreign amount) plus the payee or the billed party. Invoice, loan, gift letter, solicitor letter, collection-report totals, takings book, own-account statement, group chart, contract schedule with named stages. An invoice that only says "four instalments", with no stage amounts, is not a match.
2. **Written rules.** Own-account transfers at five times declared income or volume: ask for an updated profile, unless a documented event is the excess. Payments and FX: £10,000 or more to anyone other than the client needs a matching invoice or contract. A group chart does not release it. An earlier review covers only what it describes.
3. **Challenger. It cannot vote close.** Fraud report, mule chat, staff note about staying under a threshold, shared device or higher-risk login, listed person still in control (officer or PSC, same birth month and year, ceased on or after the payment). Any one of those sends the case upstairs. Asking the customer is not allowed at that point.
4. **Grok, leftovers only.** If steps 1–3 found no document and no suspicion, the rule answer is "ask a question". If `XAI_API_KEY` is set, that leftover is sent to `https://api.x.ai/v1/chat/completions`. Model `grok-4.20-0309-non-reasoning` unless `XAI_MODEL` is set. Temperature 0, seed 1. It may close, ask, or escalate. A close is kept only if it cites a document or list ID that exists in the folder. Invented IDs are discarded and the rule answer stands. If the key is unset, or the call fails, the rule answer stands.

## Same answer five times

Rules do not use randomness. Model replies are cached under `system/.llm_cache/`, with a file lock so parallel runs share the first reply. Five runs in the same directory return the same verdict, reason code, reason, and evidence.

## Time and cost

No key: about one second per 1,000 cases. $0.

With a key: only leftover cases call the API. A run of 200 cases stays under 30 minutes. Spend is those residual calls only.

## Run

From this directory, with full paths:

```
./run /path/to/institutions/bank /path/to/output/bank.jsonl
```

The institution folder name is `bank`, `emoney`, `investment`, or `payments_fx`. The program does not depend on the working directory. It reads only that folder and writes only the output file, plus the reply cache inside `system/`.
