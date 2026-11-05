# Small Claims Jury

**A record of small private disputes, with a ruling that the validators must reach twice, from both sides.** The model reads the two
statements once with the claimant's first and once with the respondent's first. A side wins only when both readings pick it, and
only if the words the model relied on are really in the statements.

* `contracts/small_claims_jury.py` : the Intelligent Contract (one Python file, no funds, no web access).
* `tests/direct` : 143 direct-mode tests with the model mocked. `tests/glsim` : 5 tests on a local 5-validator network.
* `scripts/mutation_check.py` : breaks the contract on purpose in 116 ways (109 caught; the rest cannot change a result, see `evidence/mutation-checks.txt`).
* `evidence/` : the outputs of those runs.

Status: **v0.1.0, deployed on Studionet and run once end to end with the real validators**. See [Live run](#live-run) and [What it does not show](#what-it-does-not-show).

## Why a contract for this

Two people who disagree over something small (a repair, a delivery, a shared bill) usually end in "he said, she said". A model can read
two short accounts, but a single reading has two known weaknesses: it leans towards whichever statement comes first, and it can be
steered by what a party writes. This contract does not claim to remove them. It makes both visible and harder to use: the order is
flipped between two readings and a side must win both; the model must show the words it relied on, in each statement, and the contract
checks them without a model; validators must agree on the outcome; and the loser can ask for the reading to be repeated, which either
confirms the ruling or leaves the case open.

## How it works

| Call | What happens |
|---|---|
| `file_claim(respondent, title, statement)` | The claimant states the dispute (30 to 600 characters) against another address. A case opens for 3 days. |
| `answer(case_id, statement)` | The respondent answers within 3 days. |
| `close_unanswered(case_id)` | Anyone can close a case nobody answered in time. No model is used and **nobody wins by default**: the case ends `UNANSWERED`. |
| `rule(case_id)` | Anyone can ask for the ruling once both statements are in. See below. |
| `appeal(case_id)` | The side that lost can ask once, within 3 days of the ruling, for the reading to be made again. Same result: the ruling is `CONFIRMED`. Anything else: the case ends `UNDECIDED`. |
| `withdraw(case_id)` | The claimant drops a case that has no ruling yet. |

### The ruling

* The model is shown the title and the two statements under neutral labels, FIRST and SECOND. The words "claimant" and "respondent"
  never appear in the prompt.
* It must answer `{"winner": 1, 2 or 0, "quote_1": ..., "quote_2": ...}`: which statement is better supported by what the parties
  themselves wrote (0 when it cannot tell), and words copied from **each** statement that the decision relies on.
* The contract checks that each quote is really in the statement it is credited to (8 to 300 characters; case and spacing ignored).
  Anything that does not follow the format, or quotes words that are not there, is not a reading: the call is refused and nothing is stored.
* The reading is made twice, with the order flipped. Both must pick the same side. Two different picks, or one "cannot tell", end the case
  as `UNDECIDED`.
* Validators run both readings again and must agree exactly on the outcome. They do not have to use the same words.

## Contract

| Call | Kind | What it does |
|---|---|---|
| `file_claim`, `answer`, `close_unanswered`, `withdraw`, `rule`, `appeal` | write | As above. |
| `get_case_json(case_id)` | view | The whole case: both statements, phase, ruling with its quotes and `reads` (how each of the two readings came out: `CLAIMANT`, `RESPONDENT` or `NONE`), appeal; `NONE` if unknown. |
| `get_case_count()`, `get_cases_page(offset, limit)` | view | List cases. |
| `get_record_json(address)` | view | Counts for one address, as claimant and as respondent: won, lost, undecided, unanswered, withdrawn. |

Limits: 100 cases, 3 unfinished cases per claimant, 5 unfinished cases against one respondent.

## What it does not show

These are limits of the idea, not bugs.

* **A ruling is what two readings of two short texts gave.** It is not a finding of fact. The model knows only what the parties wrote.
* **The statements are untrusted text.** The prompt tells the model not to obey them, and flipping the order cancels an instruction such
  as "the first statement wins". An instruction that names no position ("rule for me") is not cancelled by the flip; the quote rule makes
  it harder to use, not impossible.
* **Positional lean is cancelled, not measured.** A model that always picks the first statement ends in `UNDECIDED`.
* **An appeal asks the same question again.** Models answer differently from one run to the next. A confirmed ruling means two more readings
  agreed; it is not a higher court.
* **Exact agreement is demanded.** Validators must agree exactly on the outcome. If they cannot, the transaction does not settle and can be
  sent again; nothing is stored in between.
* **Addresses are not identities.** Anyone can open another address and file against it. The caps limit how fast, they do not stop it.
  A record here says what the validators concluded about two statements, not who is right in the world.
* **No default judgement.** Not answering ends the case; it does not decide it.
* **Time comes from the transaction.** The 3-day windows run from the timestamp of the transaction that opened them.
* No funds are held, and nothing outside this contract is affected.

## Tests

Run from the repository root (Python 3.12+, `pip install genlayer-test`).

```
python3 -m pytest tests/direct     # 143 tests, in memory, the model is mocked
python3 -m pytest tests/glsim      # 5 tests on a local 5-validator network (pip install glsim fastapi uvicorn)
python3 scripts/mutation_check.py  # 116 deliberate breakages
```

The nine combinations of the two readings (claimant, respondent, cannot tell) are tested against a written-out table, and random cases
(rulings, appeals, unanswered, withdrawn) against a plain reference. The tests mock the model, so they show that the contract handles each
kind of answer correctly (agreeing readings, position bias, badly formed answers, quotes in the wrong statement, forged validator
readings), **not** how well a real model weighs two accounts. The mock answers on the local network are identical for every validator.

## Live run

Studionet, contract `0x389852789E09D2552d88D47b4696b86e8FaFE358`
([Explorer](https://explorer-studio.genlayer.com/address/0x389852789E09D2552d88D47b4696b86e8FaFE358)), two Studio accounts.

One case was run through `file_claim`, `answer` and `rule` with the real validators and the real model:

* claim: *On 3 March I paid 40 euros for a bicycle repair and received a signed receipt number 118, but the shop has not returned my bicycle since.*
* answer: *We confirm that the customer paid 40 euros on 3 March, that the receipt number 118 is ours, and that we still hold the bicycle without any reason.*
* result: phase `RULED`, winner `CLAIMANT`, `reads` = `["CLAIMANT", "CLAIMANT"]` (both orders agreed), and the stored quotes are words from each statement.

That is **one** case with an easy, one-sided answer. `appeal`, `close_unanswered` and `withdraw` were not run on Studionet.

**An earlier version.** The first deployment (`0x022CC6371103b1b1F831B66FC5bfaBB8727E908d`, not the one submitted) ended three different
cases `UNDECIDED`, including this same one, where the second side admits everything. The prompt told the model to answer "cannot tell"
whenever the statements did not settle it, and the contract did not record how the two readings came out, so the cause could not be
seen. This version changes the prompt (a statement the other side confirms is the better supported one; "cannot tell" only for equal or
unrelated statements) and stores `reads` in every case. The same case then ended `CLAIMANT`. The tests did not change in kind, because
they mock the model: this was found only on the live network. How the model weighs disputes that are not one-sided was not tested.

## Where each claim is in the code

| Claim | Where |
|---|---|
| Neutral labels, no party names in the prompt | `_prompt` |
| Each quote must be in the statement it is credited to | `_parse`, `_anchored` |
| Two readings with the order flipped; a side needs both | `_judge` |
| Validators agree exactly on the outcome and re-check the quotes | `_consensus` (`validator`), `_valid_reading` |
| An unreadable answer is never a ruling | `_read_once`, `rule`, `appeal` |
| Unanswered cases end with no winner | `SmallClaimsJury.close_unanswered` |
| Appeal: loser only, once, within 3 days; confirmed or undecided | `SmallClaimsJury.appeal` |
| Caps on unfinished cases | `SmallClaimsJury.file_claim` |
| Time is read from the transaction timestamp and parsed by hand | `_now` |

## Licence

MIT, see `LICENSE`.
