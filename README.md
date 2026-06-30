# Provenance Guard

An AI content-attribution service for a writing platform. A creator submits text; the
system estimates whether it was written by a human or with AI help, returns a
**confidence score** and a plain-language **transparency label**, records every decision
in a structured **audit log**, and lets creators **appeal**.

The guiding principle is **honest uncertainty**. Perfect AI detection is an unsolved
problem, so the system is built to say *"I'm not sure"* rather than force a binary, and
to lean *away* from accusing a human — on a writing platform, wrongly flagging a real
person's work (a false positive) is the worst outcome.

---

## Table of contents
- [How to run](#how-to-run)
- [API](#api)
- [Detection signals](#detection-signals)
- [Confidence scoring](#confidence-scoring)
- [Transparency labels](#transparency-labels)
- [Appeals workflow](#appeals-workflow)
- [Rate limiting](#rate-limiting)
- [Audit log](#audit-log)
- [Ensemble detection (stretch)](#ensemble-detection-stretch)
- [Evaluation](#evaluation)
- [Known limitations](#known-limitations)
- [Spec reflection](#spec-reflection)
- [AI usage](#ai-usage)
- [What I'd change for production](#what-id-change-for-production)
- [Project structure](#project-structure)

---

## How to run

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env                  # then edit .env and set GROQ_API_KEY=...
python app.py                        # opens the browser UI automatically
```

The server runs on **http://localhost:5001** by default (port 5001 because macOS AirPlay
Receiver occupies 5000; override with `PORT=8000 python app.py`). Running `python app.py`
auto-opens the browser UI; disable with `OPEN_BROWSER=0 python app.py`.

There is also a **browser UI** at `GET /` — paste text, see the verdict, confidence,
per-signal breakdown, file an appeal, and view the audit log.

---

## API

| Method & path | Purpose |
|---|---|
| `POST /submit` | Classify text. Returns attribution, confidence, label, per-signal scores. Rate limited. |
| `POST /appeal` | Contest a classification. Sets status to `under_review`, logs the appeal. Rate limited. |
| `GET /log` | Return the structured audit log (decisions + appeals). |
| `GET /` | Browser UI. |
| `GET /health` | Liveness check. |

### `POST /submit`
```bash
curl -s -X POST http://localhost:5001/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Your text here", "creator_id": "writer_a"}'
```
Response (abridged):
```json
{
  "content_id": "f7160f821838",
  "attribution": "likely_ai",
  "confidence": 0.453,
  "label": "Likely AI-generated. Our automated check found strong signs ...",
  "raw_score": 0.823,
  "evidence_trust": 0.7,
  "signals": {
    "llm":        {"available": true, "score": 0.7,   "self_confidence": 0.6, "reason": "..."},
    "stylometry": {"available": true, "score": 0.554, "self_confidence": 0.8,
                   "components": {"burstiness": 0.7, "mattr": 0.0, "punctuation": 1.0}},
    "phrase":     {"available": true, "score": 1.0,   "self_confidence": 1.0,
                   "components": {"hits": 11, "distinct": 11, "per_100_words": 22.9, "matched": ["..."]}}
  },
  "status": "classified",
  "timestamp": "2026-06-29T03:40:13.139Z"
}
```
`content_id` is the spine of the system — it's what an appeal references and what links a
decision to its appeal in the audit log.

---

## Detection signals

The pipeline uses **three distinct, independent signals**, chosen so their blind spots
barely overlap: one reads *meaning*, one counts *structure*, one matches *lexical
markers*. Each returns a continuous 0–1 AI-likelihood plus a `self_confidence`.

### Signal A — Groq LLM classifier (semantic)
- **Captures:** the holistic "feel" of the prose — voice, coherence, idiosyncrasy versus
  the bland, even register default chat models drift into. One call to Groq
  `llama-3.3-70b-versatile` (temperature 0.2), prompted to return JSON.
- **Misses:** non-deterministic (varies run to run); confidence isn't calibrated to
  truth; tends to read plain/non-native-English writing as AI (we push back in the
  prompt); and — the big one — it reads *polished modern AI* as human.

### Signal B — Stylometric heuristics (structural)
- **Captures:** how *uniform* the writing is, from three sub-metrics — sentence-length
  burstiness, MATTR (moving-average lexical diversity, length-robust), and punctuation
  variety. AI tends to be uniform; humans are bumpier. Pure Python, deterministic, with a
  length guard that lowers self_confidence on short text.
- **Misses:** meaning-blind; unreliable on short text; gameable both ways; confounded by
  genre (poetry, lists); reads polished modern AI as human (it varies its sentences).

### Signal C — AI-register phrase detector (lexical)
- **Captures:** density of multi-word phrases characteristic of the "AI essay" register
  (*it is important to note, in today's fast-paced world, delve into, a testament to*).
  Pure Python. High precision when it fires; abstains (low self_confidence) otherwise.
- **Misses:** natural conversational AI that avoids clichés; gameable by avoiding the
  phrases. Deliberately uses multi-word phrases (not generic single words) to avoid
  flagging formal *human* writing.

**Why three:** the LLM and stylometry both get fooled by polished modern AI; the phrase
detector catches the common cliché-AI register that fools them — without false-flagging
real people. Independent failure modes are what make the ensemble worth more than its
parts. (See [Ensemble detection](#ensemble-detection-stretch).)

---

## Confidence scoring

Three numbers, kept distinct:
- **`raw_score`** — how AI-like the text is (0 = clearly human, 1 = clearly AI), the
  **confidence-weighted** average of the signals (each vote scaled by its weight *and* its
  own self_confidence, so an abstaining signal fades out instead of voting "human").
- **`evidence_trust`** — how much we trust the evidence: the mean of text length, the
  signals' mean self_confidence, and how much the signals agree.
- **`confidence`** — the reported headline = `lean_strength × evidence_trust`, where
  `lean_strength = |raw_score − 0.5| × 2`.

A verdict needs **two switches**:
1. **Asymmetric thresholds.** `raw_score ≥ 0.75` → `likely_ai`; `raw_score ≤ 0.35` →
   `likely_human`; otherwise `uncertain`. The AI bar is farther from the midpoint than
   the human bar — it takes *stronger* evidence to call something AI. That asymmetry is
   the false-positive guard.
2. **Reliability gate.** A high-confidence verdict is only allowed when
   `evidence_trust ≥ 0.60`. Signals agreeing on short, weak input is *not* strong
   evidence, so the gate forces `uncertain`.

Two overrides: **graceful degradation** (if the LLM is unavailable, trust is capped below
the gate so the surface signals can't accuse alone) and a **phrase boost** (a confident
cliché hit lifts trust to ≥ 0.70 so clear cliché-AI isn't gated out by short length —
measured to add 0 false positives).

### Two example submissions (real output)

**High-confidence case** — a cliché-heavy AI paragraph; the phrase signal fires and all
three lean AI:

| field | value |
|---|---|
| `llm_score` / `stylometry_score` / `phrase_score` | 0.7 / 0.554 / 1.0 |
| `raw_score` | 0.823 |
| `evidence_trust` | 0.70 |
| **`confidence`** | **0.453** |
| **`attribution`** | **`likely_ai`** |

**Lower-confidence case** — the input `"It rained today."` (too short to judge):

| field | value |
|---|---|
| `llm_score` / `stylometry_score` / `phrase_score` | 0.4 / 0.45 / 0.0 |
| `raw_score` | 0.39 |
| `evidence_trust` | 0.032 |
| **`confidence`** | **0.007** |
| **`attribution`** | **`uncertain`** |

`0.453` vs `0.007` — meaningful variation, not a constant. The short input is `uncertain`
because its `evidence_trust` is far below the gate.

### How the scores were validated
- **Deterministic threshold checks** in `scorer.py` (`python scorer.py`) feed fixed
  signal values through the scorer and assert the bucket — proving it matches the spec
  with no LLM variance. All pass, including the false-positive and signal-failure cases.
- **A labeled benchmark** (`eval.py`) runs 12 hand-labeled samples through the live
  pipeline and reports false positives and AI caught (see [Evaluation](#evaluation)).

---

## Transparency labels

Plain language, no jargon, no raw numbers. The three variants differ in **words**, not
just a number. The AI variant never says "this *is* AI" (only "strong signs / may have")
and is the only one that invites an appeal, because it's the verdict that can harm a
creator. The label is selected from the attribution bucket (derived from the score), so
it provably changes with the score.

| Attribution | Label text (verbatim) |
|---|---|
| `likely_ai` | "Likely AI-generated. Our automated check found strong signs that this text may have been created with AI. This is an automated estimate based on patterns in the writing — it is not proof. If you wrote this yourself, you can appeal this result." |
| `uncertain` | "We couldn't determine how this was written. Our automated check could not reliably tell whether this text was written by a person or with AI help. No determination has been made, and this is not a judgment about the author." |
| `likely_human` | "Likely human-written. Our automated check found no strong signs of AI generation in this text. This is an automated estimate, not a guarantee." |

---

## Appeals workflow

Any creator can contest any result via `POST /appeal` with a `content_id` and
`creator_reasoning`. The endpoint verifies the `content_id` exists (else `404`), captures
the reasoning, flips the content's status from `classified` to `under_review`, and writes
an `appeal` entry into the audit log linked to the original decision. No automatic
re-classification — a human decides.

```json
{
  "appeal_id": "c98db2818f4c",
  "content_id": "f7160f821838",
  "status": "under_review",
  "original_attribution": "likely_ai",
  "appeal_reasoning": "This is templated marketing copy my team wrote; please review.",
  "message": "Your appeal has been recorded; this content is now under review."
}
```

---

## Rate limiting

Flask-Limiter (per client IP) is the **gate** — it runs before the expensive detection
work, so abuse is refused cheaply.

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | **10 / minute; 100 / day** | A real writer checks their own work occasionally; even an active user revising a few pieces rarely exceeds a handful per minute or dozens per day. 10/min absorbs honest bursts while blocking a flooding script; 100/day caps sustained abuse while covering a heavy legitimate day. |
| `POST /appeal` | **5 / minute; 50 / day** | Appeals are rarer and each queues costly human review, so the limit is tighter — flooding appeals would be a denial-of-service on reviewers. |

### Evidence (12 rapid requests, limit 10/min)
```
200 200 200 200 200 200 200 200 200 200 429 429
```
The first ten succeed; the rest return `429 Too Many Requests`. Reproduce:
```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5001/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "rate limit test", "creator_id": "rl"}'
done
```

---

## Audit log

Every decision and appeal is appended to `audit_log.jsonl` (one JSON object per line —
structured, not console output). `GET /log` returns it. Decision entries record the
timestamp, content ID, attribution, confidence, **all three individual signal scores**,
the combined `raw_score`/`evidence_trust`, and which signals were used. Appeal entries
record the reasoning, the `under_review` status, and the original attribution, so they sit
alongside the decision they contest.

```json
[
  {"entry_type": "appeal", "appeal_id": "c98db2818f4c", "content_id": "f7160f821838",
   "appeal_reasoning": "This is templated marketing copy my team wrote; please review.",
   "status": "under_review", "original_attribution": "likely_ai",
   "original_confidence": 0.453, "timestamp": "2026-06-29T03:40:14.352Z"},

  {"entry_type": "decision", "content_id": "539da40f7908", "attribution": "uncertain",
   "confidence": 0.007, "raw_score": 0.39, "evidence_trust": 0.032,
   "llm_score": 0.4, "stylometry_score": 0.45, "phrase_score": 0.0,
   "signals_used": ["llm","stylometry","phrase"], "status": "classified",
   "timestamp": "2026-06-29T03:40:13.964Z"},

  {"entry_type": "decision", "content_id": "a065a40b9d8d", "attribution": "likely_human",
   "confidence": 0.411, "raw_score": 0.177, "evidence_trust": 0.636,
   "llm_score": 0.2, "stylometry_score": 0.217, "phrase_score": 0.0,
   "signals_used": ["llm","stylometry","phrase"], "status": "classified",
   "timestamp": "2026-06-29T03:40:13.608Z"},

  {"entry_type": "decision", "content_id": "f7160f821838", "attribution": "likely_ai",
   "confidence": 0.453, "raw_score": 0.823, "evidence_trust": 0.7,
   "llm_score": 0.7, "stylometry_score": 0.554, "phrase_score": 1.0,
   "signals_used": ["llm","stylometry","phrase"], "status": "classified",
   "timestamp": "2026-06-29T03:40:13.139Z"}
]
```
`content_id f7160f821838` appears twice — the original `likely_ai` decision and the appeal
now `under_review`.

**Two storage mechanisms, on purpose:** the audit log is an append-only *ledger* (history
you never rewrite); a submission's *current status* is mutable state, so it lives
separately in a SQLite database (`submissions.db`). Conflating them would mean rewriting log lines to change
a status, which breaks the integrity of a ledger.

---

## Ensemble detection (stretch)

The system implements the **Ensemble Detection** stretch feature: **three** signals (see
[Detection signals](#detection-signals)) combined with a documented strategy.

- **Weighting:** confidence-weighted average, **LLM 0.6 / stylometry 0.1 / phrase 0.3**.
  Each vote is scaled by both its fixed weight and its own self_confidence, so a signal
  that abstains (e.g. the phrase detector finding no clichés) contributes ~nothing rather
  than skewing the result.
- **Conflict resolution:** when signals disagree, the agreement term drops `evidence_trust`
  and the verdict is forced to `uncertain`. No single signal can produce a high-confidence
  accusation on its own (the asymmetric AI bar + the reliability gate). One targeted
  exception: a *confident* phrase hit lifts `evidence_trust` so clear cliché-AI clears the
  gate — validated to add zero false positives.
- **Individual scores shown alongside the ensemble result:** every `/submit` response and
  every audit entry includes `llm_score`, `stylometry_score`, and `phrase_score` next to
  the combined `raw_score` and final attribution.

---

## Evaluation

`eval.py` runs a 12-sample hand-labeled benchmark (6 human, 6 AI of varying quality)
through the live pipeline and reports the metrics that matter — chiefly false positives.
Current results:

```
AI caught (likely_ai):      2/6
AI soft-missed (uncertain): 4/6   (acceptable: not accused)
FALSE POSITIVES (H->AI):    0/6   (must stay 0)
```

The ensemble reliably catches the **cliché-AI** class with **zero false positives**,
including stress tests (formal academic writing and a human who uses a cliché both stay
safe). Natural conversational AI is not caught — see limitations. Re-run with
`python eval.py`; this harness is how every tuning decision (thresholds, weights, the
third signal) was made on evidence rather than by guessing.

---

## Known limitations

1. **Polished, natural, modern AI is not detected.** This is the system's hard ceiling.
   Conversational AI (the everyday ChatGPT/Claude kind) reads as human to the LLM signal
   (it scored such text ~0.2) *and* to stylometry (it varies its sentences), and contains
   no clichés for the phrase signal. With all three reading "human," no weighting or
   threshold can recover an AI verdict — so this text lands `uncertain` or `likely_human`.
   This is a property of the signals, not a data-quantity problem, and it reflects the
   genuine state of the art (reliable detection of short, natural AI text is unsolved).
2. **Short, plain, or non-native-English (ESL) human writing** is the shared blind spot:
   the LLM and stylometry can both read clean, even prose as AI. The reliability gate and
   asymmetric AI bar push *short* cases to `uncertain` (never `likely_ai`), but a *long*
   plain/ESL human text where both lean AI and trust is high could be misclassified.
3. **Poetry / verse** breaks the stylometry assumptions (repetition, short length) and is
   surfaced honestly as `uncertain`.

Operationally: runs on Flask's development server (a production deploy would use a WSGI
server like Gunicorn), and rate limits use in-memory storage that resets on restart.

---

## Spec reflection

**How the spec helped.** Writing `planning.md` first — signals, the threshold table, the
exact label text — gave the implementation a precise target. The scoring pseudocode
mapped almost line-for-line onto `scorer.py`, and finalizing the label wording up front
meant it never drifted once code hardcoded it.

**How the implementation diverged.** Three ways, all evidence-driven. (1) The AI bar:
planned at 0.85, but the deliberately-conservative LLM prompt capped clear AI near 0.7, so
it was lowered to **0.75** after seeing real output. (2) A **third signal** and
**confidence-weighted** scoring were added (the Ensemble stretch) after measuring that the
original two signals missed cliché AI and that a plain weighted average let an abstaining
signal act like a "human" vote. (3) Most importantly, I accepted that **natural modern AI
is undetectable** and chose to build *honest uncertainty* — a system that says "I can't
tell" and never falsely accuses — rather than chase an accuracy that isn't achievable. The
lesson: tune to the behavior of the signals you actually built, and measure every change.

---

## AI usage

> Built with AI assistance (Claude). Each instance notes what I directed it to do, what it
> produced, and what I revised or overrode.

1. **Generating the signals and scorer from my spec.** I gave the AI my detection-signals
   and uncertainty sections plus the architecture diagram and asked it to implement
   `stylometry.py` and `scorer.py`. It produced working functions. I **verified** them
   against my threshold table with deterministic tests and **overrode** two choices: I
   lowered the AI bar from 0.85 to 0.75 after seeing the LLM cap clear-AI scores near 0.7,
   and I required **MATTR instead of raw TTR** so lexical diversity wouldn't collapse on
   long text.

2. **Evidence-driven tuning with a labeled eval harness.** I directed the AI to build
   `eval.py` (a small labeled benchmark) so changes could be measured, not guessed. Using
   it, I **overrode** several tempting changes: I confirmed that reweighting signals barely
   helped (the LLM ceiling, not the weights, was the bottleneck); I **rejected lowering the
   AI bar to 0.65** after the eval showed it gained nothing and eroded the ESL safety
   margin; and I added the **phrase signal as an ensemble member** only after measuring
   that the two-signal version missed cliché AI — then confirmed it added zero false
   positives before keeping it.

---

## What I'd change for production
- **Calibrate thresholds and weights on a real labeled corpus** instead of hand-chosen
  heuristics and a 12-sample smoke test.
- **Persist rate limits in Redis** so they survive restarts and span multiple workers.
- **Run behind a production WSGI server** (Gunicorn) instead of Flask's dev server.
- **Authenticate `/log`** (open here for grading) and scope rate limits by authenticated
  user, not just IP.
- **Add a real reviewer queue UI** for appeals rather than just a status flag.

---

## Project structure

```
app.py             Flask app: routes, rate limiting, UI, wiring
llm_signal.py      Signal A  (Groq LLM, semantic)
stylometry.py      Signal B  (stylometric heuristics, structural)
signal_phrases.py  Signal C  (AI-register phrase detector, lexical) [ensemble]
scorer.py          Confidence Scorer (3-signal ensemble; deterministic threshold checks)
labels.py          Transparency label text (3 variants)
audit.py           Append-only structured audit log (JSON Lines)
store.py           Mutable submission state (SQLite; atomic status updates)
eval.py            Labeled benchmark harness
index.html         Browser UI (served at GET /)
planning.md        Design spec + architecture diagram
requirements.txt   Dependencies
```
