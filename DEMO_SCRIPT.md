# Provenance Guard — Demo Script (~2 min walkthrough)

A scene-by-scene script for the portfolio recording. Shows **submit → appeal → log**
plus **3 design decisions**. Narration lines are short on purpose — read them slowly,
pause between scenes. You can record one scene at a time and stitch them together.

Target length: **~2:00–2:30**.

---

## Before you record (setup)

1. Open a terminal in the project folder and reset the log so the demo starts clean:
   ```bash
   cd ai201-project4-provenance-guard
   source .venv/bin/activate
   rm -f audit_log.jsonl submissions.db submissions.db-wal submissions.db-shm
   python app.py
   ```
   The browser UI opens automatically at **http://localhost:5001**.
2. **Zoom the browser to ~125–150%** so text is readable on video.
3. Have the three demo texts below ready to paste (keep this file open in a second window,
   or copy each one just before its scene).
4. Close noisy tabs/notifications. Start your screen recorder.

---

## The three demo inputs (copy-paste)

**INPUT 1 — AI (cliché register) → expect `likely_ai`**
```
In today's fast-paced world, it is important to note that technology plays a pivotal role. From navigating the complexities of data to harnessing the power of innovation, organizations must delve into a myriad of strategies. In conclusion, this is a testament to the ever-evolving digital age.
```

**INPUT 2 — human (personal story) → expect `likely_human`**
```
I never planned to keep bees. It started with a swarm on my neighbor's mailbox one Tuesday, thousands of them humming like a small engine. Carl, who is eighty-three and unbothered by most things, just shrugged. So I called a guy. The guy didn't show. Long story short: I now own a hive, three stings, and a smoker I barely know how to use.
```

**INPUT 3 — too short to judge → expect `uncertain`**
```
It rained today.
```

---

## Scene plan (at a glance)

| # | Scene | Time | Shows |
|---|---|---|---|
| 1 | Intro | 0:00–0:12 | what it is + the core idea |
| 2 | Submit AI text | 0:12–0:38 | submission endpoint, 3 signals, confidence, label |
| 3 | Submit human text | 0:38–0:58 | contrast: different label + confidence |
| 4 | Submit short text | 0:58–1:13 | honest uncertainty (the whole point) |
| 5 | Appeal | 1:13–1:33 | appeals workflow, under_review |
| 6 | Audit log | 1:33–1:50 | structured log, appeal beside decision |
| 7 | Design decisions + close | 1:50–2:20 | 3 decisions, honest limitation |

(Optional rate-limit scene at the end if you want to show it — see bottom.)

---

## Scene 1 — Intro (0:00–0:12)

**SHOW:** the browser UI at the top (title visible).

**SAY:**
> "This is Provenance Guard. A writer submits text, and it estimates whether it was
> written by a human or with AI — with a confidence score, a plain-language label, and an
> appeal option. The main idea is honest uncertainty: it would rather say 'I'm not sure'
> than wrongly accuse a real person."

---

## Scene 2 — Submit AI text (0:12–0:38)

**SHOW:** paste **INPUT 1** into the text box, click **Submit/Check**. Wait for the result.

**SAY (while it loads, then point at the result):**
> "Here's an AI paragraph in that classic essay register. The verdict is **likely AI**.
> Below it you can see how the three signals voted — the language model, the stylometry
> check, and the phrase detector, which flagged the clichés like 'delve into' and 'in
> today's fast-paced world.' They're combined into one confidence score, and the label is
> written in plain language. Notice it says 'strong signs,' not 'this is AI' — and it
> offers an appeal."

**Point at on screen:** the `likely_ai` verdict, the three signal rows, the confidence
number, the label text.

---

## Scene 3 — Submit human text (0:38–0:58)

**SHOW:** clear the box, paste **INPUT 2**, click Submit.

**SAY:**
> "Now a personal human story. This comes back **likely human** — a different label, and
> the phrase detector stays silent because there are no AI clichés. Same pipeline, very
> different result. The score and the wording both change, not just a number."

**Point at:** the `likely_human` label, phrase signal showing no clichés.

---

## Scene 4 — Submit short text (0:58–1:13)

**SHOW:** clear the box, paste **INPUT 3** (`It rained today.`), Submit.

**SAY:**
> "And this is the part I'm most proud of. Three words — not enough to judge. Instead of
> guessing, it returns **uncertain**, with a very low confidence. The system refuses to
> make a claim it can't back up. That's the honest-uncertainty principle in action."

**Point at:** the `uncertain` label, the near-zero confidence.

---

## Scene 5 — Appeal (1:13–1:33)

**SHOW:** scroll to the appeal section for the **AI** result (Scene 2). Type a reason and
submit the appeal.

**Appeal reason to type:**
```
This is templated marketing copy my team wrote, not AI. Please review.
```

**SAY:**
> "If a creator disagrees, they can appeal. I'll contest the AI verdict with a reason.
> The status flips to **under review** — nothing is auto-reversed; it's queued for a human.
> And the appeal gets logged next to the original decision."

**Point at:** the `under_review` status returned.

---

## Scene 6 — Audit log (1:33–1:50)

**SHOW:** open/refresh the **log** view in the UI (or open `http://localhost:5001/log`).

**SAY:**
> "Every decision and appeal is recorded in a structured audit log. You can see each
> verdict with its confidence, a timestamp, and all three individual signal scores — and
> here's the appeal sitting right beside the decision it contests, linked by the same
> content ID."

**Point at:** a decision entry's signal scores + timestamp, and the appeal entry with the
matching `content_id`.

---

## Scene 7 — Design decisions + close (1:50–2:20)

**SHOW:** can stay on the log, or switch to the README / `scorer.py`.

**SAY (pick the wording that's comfortable — these are the 3 decisions):**
> "Three decisions I want to call out.
> First, false positives are the worst error on a writing platform, so the bar to call
> something AI is deliberately higher than the bar to call it human, and a reliability
> gate blocks any confident verdict on short or weak input.
> Second, it's an ensemble — three signals combined by confidence-weighting, so a signal
> that isn't sure quietly steps back instead of voting.
> Third, I tuned every threshold against a small labeled eval set, not by guessing. That
> same testing showed the honest limit: polished, natural AI reads as human to all three
> signals and isn't reliably detectable — which is an unsolved problem industry-wide. So
> rather than fake accuracy, I built a system that's honest about what it doesn't know.
> Thanks for watching."

---

## Optional — Rate-limiting scene (+~15s)

If you want to show the production layer, add this before the close. Switch to a terminal:

**SHOW:** run the burst loop:
```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:5001/submit \
    -H "Content-Type: application/json" \
    -d '{"text":"rate limit test","creator_id":"rl"}'; done; echo
```

**SAY:**
> "There's also rate limiting. Twelve rapid requests: the first ten succeed with 200, then
> it returns 429 — too many requests. It runs before the expensive detection work, so
> abuse is refused cheaply."

**Expected output:** `200 200 200 200 200 200 200 200 200 200 429 429`
(If you run this, reset the log again before recording the log scene, or record the log
scene first.)

---

## Recording tips
- Keep each narration line short; pause at the end of each scene — easier to edit.
- Record scene by scene; if you fumble a line, just redo that one clip.
- The cliché text reliably comes back `likely_ai`, the bees text `likely_human`, and the
  short text `uncertain` — so the three contrasts are dependable on camera.
- If the AI verdict ever varies slightly between runs, do one practice submission of
  INPUT 1 before recording to confirm, then record.
