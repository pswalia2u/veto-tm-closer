# Veto

A program that closes bank alerts only when the paperwork explains them, and refuses to close anything that looks like crime.

Track 1 of the [Grok Bot London Financial Crime Hackathon](https://gb-fincrime-hackathon-11-2026.teamdeel.workers.dev/hackathon#track-1).

## The problem

Banks watch every payment. A computer rule flags anything odd: too much cash, money in and straight out, a name that looks like someone on a bad list.

Most flags are innocent. A bakery bought an oven. A teacher got an inheritance. But a person still has to look at every flag, because closing the wrong one means criminal money walks through.

That person has three choices:

- **Close it.** The paperwork explains it. Done.
- **Ask one question.** Nothing looks criminal yet, but one document would settle it. For example: "Send the invoice."
- **Send it upstairs.** It looks like crime. Do not ask the customer. Asking them warns them, which is itself an offence.

The hackathon asked: build a program that does that job.

You get a folder: the customer, their payments, the alerts, and the documents on file. You must write one decision per case, with a short reason that names the actual people, amounts, and documents.

They score you on cases you have never seen. Closing a real crime is the worst mistake. Closing nothing, and sending everything upstairs, also scores badly. Run the same cases five times and the verdict and reason code must match.

## What we built

A program called **Veto**.

It reads the folder and writes the decision. No website the judges run. Plain Python.

It works in four steps:

1. **Look for a document that explains the payment.** Invoice matches the amount and the company. Loan matches the car. Gift letter matches the payer. Bank statement shows it is their own other account.
2. **Apply the bank's written rules.** For example: if it is only money moving between their own accounts, and it is more than five times what they said they earn, do not close it. Ask them to update their expected income. A payment over £10,000 needs an invoice before you release it.
3. **A second checker that is not allowed to say "close".** It only looks for reasons to stop a close. A bank wrote in saying their customer was scammed into sending that money. Someone on a do-not-deal list still controls the company. The customer asked how to stay under £10,000 so nobody notices. If any of that is true, close is killed. Send it upstairs.
4. **Only the leftovers go to Grok.** If the rules found no document and no sign of crime, the case would have been "ask a question". That is the ambiguous pile. Grok (`grok-4.20`, no reasoning, temperature 0) may close, ask, or send it upstairs. A close is kept only if it names a document that is actually in the folder. A made-up invoice is thrown away. Fraud, list hits, and matched invoices never reach the model.

The name is the point: the first part proposes, the second part can veto. The model does not get a veto override.

## A picture, three real cases

- **Close.** An electrician gets a car loan, then pays a garage the same amount. There is a loan agreement and an invoice. Innocent. Close. No model.
- **Ask.** A civil engineer receives £49,744 from a solicitor, reference "estate of Kit Falcombe". No letter on file. Not obviously crime. Ask for the solicitor's letter.
- **Send upstairs.** A student receives lots of small payments, then sends them on. Two banks say their customers were scammed. He told chat he keeps 8% and forwards the rest. Do not ask him. That would tip him off. The challenger vetoes. No model.

## Run

```
cd system
./run /path/to/institutions/bank /path/to/output/bank.jsonl
```

Same command for `emoney`, `investment`, and `payments_fx`. About one second per thousand cases when no key is set. With `XAI_API_KEY` set, only leftover cases call `https://api.x.ai/v1`. The first reply is cached, so five runs match.

## Layout

```
system/run          the program the judges call
system/README.md    how it decides, which model, time and cost
output/*.jsonl      answers on the 4,000 practice cases
demo/index.html     the three cards above
```

The institution folders are the hackathon dataset and are not in this repo.
