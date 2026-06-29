# Provenance Guard

An AI content-attribution service for a writing platform. A creator submits text; the
system estimates whether it was written by a human or with AI help, returns a
**confidence score** and a plain-language **transparency label**, records every decision
in a structured **audit log**, and gives creators a way to **appeal**.

The guiding principle is **honest uncertainty**. Perfect AI detection is an unsolved
problem, so this system is built to say *"I'm not sure"* rather than force a binary, and
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
- [Known limitations](#known-limitations)
- [Spec reflection](#spec-reflection)
- [AI usage](#ai-usage)
- [What I'd change for production](#what-id-change-for-production)
- [Architecture & project structure](#architecture--project-structure)

---

## How to run

```bash
# 1. create + activate a virtual environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. add your Groq API key
cp env.example .env                  # then edit .env and set GROQ_API_KEY=...

# 4. run the server
python app.py
```

The server runs on **http://localhost:5001** by default. (Port 5001 rather than 5000
because macOS AirPlay Receiver occupies 5000; override with `PORT=8000 python app.py`.)

---

## API

| Method & path | Purpose |
|---|---|
| `POST /submit` | Classify a piece of text. Returns attribution, confidence, and label. Rate limited. |
| `POST /appeal` | Contest a classification. Sets status to `under_review` and logs the appeal. Rate limited. |
| `GET /log` | Return the structured audit log (decisions + appeals). |
| `GET /health` | Liveness check. |

### `POST /submit`

Request:
```bash
curl -s -X POST http://localhost:5001/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon...", "creator_id": "writer_a"}'
```

Response (abridged):
```json
{
  "content_id": "97770520c1a0",
  "attribution": "likely_ai",
  "confidence": 0.823,
  "label": "Likely AI-generated. Our automated check found strong signs ...",
  "raw_score": 0.975,
  "evidence_trust": 0.867,
  "signals": {
    "llm": {"available": true, "score": 0.95, "self_confidence": 0.9, "reason": "..."},
    "stylometry": {"available": true, "score": 1.0, "self_confidence": 0.8,
                   "components": {"burstiness": 1.0, "mattr": 1.0, "punctuation": 1.0}}
  },
  "status": "classified",
  "timestamp": "2026-06-29T01:00:17.132Z"
}
```

`content_id` is the spine of the system — save it; it's what an appeal references and
what ties a decision to its appeal in the audit log.

---

## Detection signals

The pipeline uses **two distinct signals**, chosen so their blind spots barely overlap:
one reads *meaning*, the other counts *form*. Their agreement (or disagreement) is itself
information that drives the confidence score.

### Signal A — Groq LLM classifier (semantic)
- **What it measures:** the holistic *feel* of the prose — voice, coherence,
  idiosyncrasy, versus the bland, even, hedging register that default chat models drift
  into. Implemented as one call to Groq `llama-3.3-70b-versatile` (temperature 0.2),
  prompted to return a continuous AI-likelihood, a self-confidence, and a one-line reason.
- **Why this signal:** an LLM can perceive the gestalt of "this reads like AI" in a way
  that no simple statistic can.
- **What it misses:** it's non-deterministic (same text varies run to run), its
  confidence isn't calibrated to truth, it's a black box, and — critically — it tends to
  flag plain or non-native-English writing as AI. We push back on that last bias directly
  in the prompt, but it can't be eliminated.

### Signal B — Stylometric heuristics (structural)
Pure-Python, deterministic. Measures how *uniform* the writing is, from three sub-metrics
(each mapped to a 0–1 AI-likeness contribution, then weighted 0.5 / 0.3 / 0.2):
- **burstiness** — variation in sentence length. Humans mix short and long; default AI is
  more uniform. (Low variation → more AI-like.)
- **mattr** — moving-average type-token ratio (lexical diversity), computed over a fixed
  50-word window so it doesn't collapse on long text the way raw TTR does.
- **punctuation** — variety of "rich" marks (dashes, semicolons, parentheses…). Human
  punctuation habits are more varied.
- **Why this signal:** it's transparent, reproducible, and independent of the LLM — it
  fails for completely different reasons, which is the point of an ensemble.
- **What it misses:** it's meaning-blind, unreliable on short text (too few sentences to
  judge), easily gamed in both directions, confounded by genre (poetry, lists, dialogue),
  and its reference points are hand-chosen heuristics, not learned from a corpus. A
  length guard lowers its self-confidence on short input.

**Why the pairing works:** Signal A is meaning-aware but moody and bias-prone; Signal B
is steady but meaning-blind. When they agree, that's strong multi-perspective evidence.
When they disagree, that's exactly the *uncertain* zone we want to surface honestly. Their
one shared blind spot — plain/ESL writing — is the reason the scorer leans toward
"human/uncertain" on weak evidence (see below).

---

## Confidence scoring

The scorer keeps three numbers distinct:
- **`raw_score`** — *how AI-like* the text is (0 = clearly human, 1 = clearly AI),
  the weighted average of the available signal scores.
- **`evidence_trust`** — *how much we trust the evidence*, the mean of three factors:
  text length, the signals' self-confidence, and how much the two signals agree.
- **`confidence`** — the reported headline number = `lean_strength × evidence_trust`,
  where `lean_strength = |raw_score − 0.5| × 2`.

A verdict needs **two switches** to pass:
1. **Asymmetric thresholds.** `raw_score ≥ 0.75` → `likely_ai`; `raw_score ≤ 0.35` →
   `likely_human`; otherwise `uncertain`. The AI bar sits farther from the 0.5 midpoint
   than the human bar — it takes *stronger* evidence to call something AI than to call it
   human. That asymmetry is the false-positive guard.
2. **Reliability gate.** A high-confidence verdict is only allowed when
   `evidence_trust ≥ 0.60`. Two signals agreeing on short, weak input is *not* strong
   evidence — it's two unreliable guesses pointing the same way, so the gate forces
   `uncertain`.

**Why this approach:** the hardest part of the assignment isn't detection, it's *honestly
representing uncertainty*. We decided what a low score should mean to a user first ("we
don't know"), then built the math to produce it. The gate — not the threshold — is what
protects the false-positive case, which is why short/weak text can never be confidently
accused.

### Two example submissions (real output)

**High-confidence case** — a repetitive, uniform paragraph; both signals strongly agree:

| field | value |
|---|---|
| `llm_score` | 0.95 |
| `stylometry_score` | 1.0 |
| `raw_score` | 0.975 |
| `evidence_trust` | 0.867 |
| **`confidence`** | **0.823** |
| **`attribution`** | **`likely_ai`** |

**Lower-confidence case** — the input `"It rained today."` (too short to judge):

| field | value |
|---|---|
| `llm_score` | 0.4 |
| `stylometry_score` | 0.45 |
| `raw_score` | 0.425 |
| `evidence_trust` | 0.36 |
| **`confidence`** | **0.054** |
| **`attribution`** | **`uncertain`** |

`0.823` vs `0.054` — the scoring produces meaningful variation, not a constant. The short
input lands in `uncertain` because its `evidence_trust` (0.36) is below the gate, even
though the raw scores aren't far apart.

### How I validated the scores
- **Deterministic threshold checks** in `scorer.py` (run `python scorer.py`) feed fixed
  signal values through the scorer and assert the bucket — proving the scorer matches the
  spec's thresholds with no LLM variance. All checks pass, including the false-positive
  case (short + both-lean-AI → `uncertain`) and the single-signal-failure case.
- **Four hand-picked inputs** spanning the range (clearly AI, clearly human, formal human,
  lightly-edited AI) were run end-to-end; the scores ordered as intuition expects.

---

## Transparency labels

Plain language, no jargon, no raw numbers in the text. The three variants differ in
**words**, not just a number. The AI variant never says "this *is* AI" (only "strong
signs / may have") and is the only one that invites an appeal, because it's the verdict
that can harm a creator. The uncertain variant explicitly states that no judgment was
made.

| Attribution | Label text (verbatim) |
|---|---|
| `likely_ai` | "Likely AI-generated. Our automated check found strong signs that this text may have been created with AI. This is an automated estimate based on patterns in the writing — it is not proof. If you wrote this yourself, you can appeal this result." |
| `uncertain` | "We couldn't determine how this was written. Our automated check could not reliably tell whether this text was written by a person or with AI help. No determination has been made, and this is not a judgment about the author." |
| `likely_human` | "Likely human-written. Our automated check found no strong signs of AI generation in this text. This is an automated estimate, not a guarantee." |

The label is selected from the attribution bucket, which is derived from the confidence
score — so the label provably changes with the score. All three are reachable (see the
audit log below, which contains one of each).

---

## Appeals workflow

Any creator can contest any result via `POST /appeal` with a `content_id` and
`creator_reasoning`. The endpoint:
1. verifies the `content_id` exists (else `404`),
2. captures the reasoning verbatim,
3. flips the content's status from `classified` to `under_review`,
4. writes an `appeal` entry into the audit log, linked to the original decision so a human
   reviewer sees the verdict and the creator's words side by side.

There is no automatic re-classification — a human decides.

```bash
curl -s -X POST http://localhost:5001/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "97770520c1a0", "creator_reasoning": "I wrote this myself..."}'
```
```json
{
  "appeal_id": "41156f433dbe",
  "content_id": "97770520c1a0",
  "status": "under_review",
  "original_attribution": "likely_ai",
  "appeal_reasoning": "I wrote this myself...",
  "message": "Your appeal has been recorded; this content is now under review."
}
```

---

## Rate limiting

Rate limiting (Flask-Limiter, per client IP) is the **gate** — it runs before the
expensive detection work, so abuse is refused cheaply.

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | **10 / minute; 100 / day** | A real writer checks their own work occasionally; even an active user revising a few pieces rarely exceeds a handful of submissions per minute or dozens per day. 10/min absorbs honest bursts while blocking a script that fires hundreds of requests; 100/day caps sustained abuse while comfortably covering a heavy legitimate day. |
| `POST /appeal` | **5 / minute; 50 / day** | Appeals are rarer than submissions, and each one queues costly human review, so the limit is tighter — flooding appeals would be a denial-of-service on reviewers. |

### Evidence (12 rapid requests, limit 10/min)
```
200
200
200
200
200
200
200
200
200
200
429
429
```
The first ten succeed; the rest return `429 Too Many Requests` ("10 per 1 minute").
Reproduce with:
```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5001/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "This is a test submission for rate limit testing purposes only.", "creator_id": "ratelimit-test"}'
done
```

---

## Audit log

Every decision and every appeal is appended to `audit_log.jsonl` as one structured JSON
object per line (not console output). `GET /log` returns it. Each **decision** entry
records the timestamp, content ID, attribution, confidence, both individual signal scores,
the combined `raw_score`/`evidence_trust`, and which signals were used. Each **appeal**
entry records the reasoning, the `under_review` status, and the original attribution, so it
sits alongside the decision it contests.

Curated sample (`GET /log`) — one of each attribution plus an appeal:
```json
[
  { "entry_type": "appeal", "appeal_id": "41156f433dbe", "content_id": "97770520c1a0",
    "creator_id": "writer_a", "appeal_reasoning": "This is automated documentation text ...",
    "status": "under_review", "original_attribution": "likely_ai",
    "original_confidence": 0.823, "timestamp": "2026-06-29T01:00:18.699Z" },

  { "entry_type": "decision", "content_id": "dc9b85155ac2", "creator_id": "writer_c",
    "attribution": "uncertain", "confidence": 0.054, "raw_score": 0.425,
    "evidence_trust": 0.36, "llm_score": 0.4, "stylometry_score": 0.45,
    "signals_used": ["llm", "stylometry"], "status": "classified",
    "timestamp": "2026-06-29T01:00:18.187Z" },

  { "entry_type": "decision", "content_id": "605b2971550e", "creator_id": "writer_b",
    "attribution": "likely_human", "confidence": 0.556, "raw_score": 0.134,
    "evidence_trust": 0.759, "llm_score": 0.2, "stylometry_score": 0.067,
    "signals_used": ["llm", "stylometry"], "status": "classified",
    "timestamp": "2026-06-29T01:00:17.680Z" },

  { "entry_type": "decision", "content_id": "97770520c1a0", "creator_id": "writer_a",
    "attribution": "likely_ai", "confidence": 0.823, "raw_score": 0.975,
    "evidence_trust": 0.867, "llm_score": 0.95, "stylometry_score": 1.0,
    "signals_used": ["llm", "stylometry"], "status": "classified",
    "timestamp": "2026-06-29T01:00:17.132Z" }
]
```
Note `content_id 97770520c1a0` appears twice — once as the original `likely_ai` decision
and once as the appeal now `under_review`.

**Two storage mechanisms, on purpose:** the audit log is an append-only *ledger* (history
you never rewrite); a submission's *current status* is mutable state, so it lives
separately in `submissions.json`. Conflating them would mean rewriting log lines to change
a status, which breaks the integrity of a ledger.

---

## Known limitations

1. **Short, plain, or non-native-English (ESL) human writing.** This is the system's
   sharpest failure mode and its one *shared* blind spot. Signal A tends to read clean,
   even prose as AI; Signal B reads uniform sentence length and sparse punctuation as
   AI. So both signals can lean AI on a genuine human's plain writing. The reliability
   gate and asymmetric AI bar push *short* versions of this to `uncertain` (never
   `likely_ai`), but a **long** plain human text where both signals lean AI and trust is
   high could still be misclassified — the gate can't catch it because it's long. This is
   a direct consequence of what the signals measure, not a data-quantity problem.
2. **Polished, long-form AI.** Well-written AI varies its sentence length enough to evade
   the stylometry signal, so unless the LLM is confident on its own, such text lands in
   `uncertain` (a false negative). That's the acceptable error here — we'd rather miss AI
   than accuse a human.
3. **Poetry / verse.** Deliberate repetition and short length break the stylometry
   assumptions; surfaced honestly as `uncertain` rather than guessed.

---

## Spec reflection

**How the spec helped.** Writing `planning.md` before any code — the signals, the
threshold table, and the exact label text — gave the implementation a precise target. The
scoring pseudocode in `planning.md` mapped almost line-for-line onto `scorer.py`, and
finalizing the label wording up front meant it never drifted once code hardcoded it.

**How the implementation diverged.** The AI bar. I planned `raw_score ≥ 0.85` for
`likely_ai`. But after building the LLM signal with a deliberately conservative prompt
(told to use the full range and not snap to extremes), clearly-AI text capped around 0.7
raw — so 0.85 made `likely_ai` effectively unreachable on real text. I lowered the bar to
**0.75** after seeing real output, having confirmed that the *reliability gate*, not the
threshold, is what protects the false-positive case. The lesson: a threshold has to be
calibrated to the behavior of the signal you actually built, not the one you imagined.

---

## AI usage

> Built with AI assistance (Claude). Each instance below notes what I directed it to do,
> what it produced, and what I revised or overrode.

1. **Generating Signal B and the confidence scorer from my spec.** I gave the AI my
   detection-signals and uncertainty sections from `planning.md` and the architecture
   diagram and asked it to implement `stylometry.py` and `scorer.py`. It produced working
   functions. I **verified** the scorer against my threshold table with deterministic
   tests, and **overrode** two things: I lowered the AI bar from 0.85 to 0.75 after seeing
   that my conservative LLM prompt capped real AI scores around 0.7, and I specified
   **MATTR over raw TTR** so lexical diversity wouldn't collapse on long text — a length
   bias the first draft would have had.

2. **Designing the failure / uncertainty model.** I directed the AI to propose how to
   combine two signals with different reliability profiles. It proposed a weighted
   average. I **decided** the additional structure that makes it honest: a separate
   `evidence_trust` gate, the false-positive asymmetry, and the rule that a single
   surviving signal can **never** reach a high-confidence verdict (graceful degradation).
   I then wrote a deterministic test to prove that safety rule actually holds, rather than
   trusting the description.

*(Adjust this section to match your own recollection before submitting.)*

---

## What I'd change for production

- **Calibrate thresholds on a labeled corpus** instead of hand-chosen heuristics.
- **Persist rate limits in Redis** so they survive restarts and work across multiple
  workers (current in-memory storage resets on restart).
- **Run behind a production WSGI server** (e.g. Gunicorn) instead of Flask's dev server.
- **Authenticate `/log`** (it's open here for grading visibility) and scope rate limits by
  authenticated user, not just IP.
- **Add a real reviewer queue UI** for appeals rather than just a status flag.

---

## Architecture & project structure

The full architecture diagram (ASCII + Mermaid) and the submission/appeal flow narrative
live in [`planning.md`](planning.md). In brief: text → rate-limit gate → both signals →
confidence scorer → transparency label → audit log → response; an appeal looks up the
original decision, flips status to `under_review`, and logs alongside it.

```
app.py            Flask app: routes, rate limiting, wiring
llm_signal.py     Signal A  (Groq LLM, semantic)
stylometry.py     Signal B  (stylometric heuristics, structural)
scorer.py         Confidence Scorer (combines signals; deterministic threshold checks)
labels.py         Transparency label text (3 variants)
audit.py          Append-only structured audit log (JSON Lines)
store.py          Mutable submission state (for appeal status)
planning.md       Design spec + architecture diagram
requirements.txt  Dependencies
```
