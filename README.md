# Veto

Policy-bound **transaction-monitoring closer** for the [Grok Bot London Financial Crime Hackathon](https://gb-fincrime-hackathon-11-2026.teamdeel.workers.dev/hackathon#track-1) — Track 1.

The closer proposes CLOSE / RFI / ESCALATE. A **challenger that is not allowed to close** can only veto. It will miss some closable cases. It should not wrongfully close a mule.

No language model. Python 3 standard library only. Same bytes every run.

## Run

```
cd system
./run /path/to/institutions/bank /path/to/output/bank.jsonl
```

~1 second per 1,000 cases. $0.

## Layout

```
system/run          executable (cwd-safe)
system/veto/        load, parse, match, SOP, challenger, emit
system/README.md    how it decides
output/*.jsonl      development-set answers, produced by ./run
demo/index.html     three-case workbench (CLOSE / RFI / ESCALATE)
HACKATHON.md        organiser short brief
```

The institution folders (`bank`, `emoney`, `investment`, `payments_fx`) are the hackathon dataset and are not in this repo.

## Demo

Open `demo/index.html`. Fernbrook Bakery A / B / C as live cases: invoice match, unexplained estate inflow, mule with sending-bank fraud reports.
