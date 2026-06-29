"""Confidence Scorer (M4 + Ensemble stretch).

Combines THREE signals into a single calibrated result:
  - Signal A: LLM (semantic)        weight 0.5
  - Signal B: stylometry (structural) weight 0.2
  - Signal C: phrase register (lexical) weight 0.3

Combination = CONFIDENCE-WEIGHTED average: each signal's vote is scaled by both its
fixed weight AND its own self_confidence. This is what lets a signal ABSTAIN safely --
e.g. the phrase signal returns score 0 with low self_confidence when it finds no
clichés, and confidence-weighting means that 0 barely affects the result instead of
acting like a "human" vote.

  raw_score      = sum(w_i * c_i * s_i) / sum(w_i * c_i)     (c_i = self_confidence)
  agreement      = 1 - (max - min) over signals that are "speaking" (c_i >= 0.4)
  length_factor  = clamp(word_count / 150)
  evidence_trust = mean(length_factor, mean_self_confidence, agreement)
  lean_strength  = |raw_score - 0.5| * 2
  confidence     = lean_strength * evidence_trust

Conflict resolution / verdict:
  evidence_trust < 0.60        -> uncertain   (reliability gate; signals disagree or weak)
  raw_score >= 0.75            -> likely_ai    (asymmetric: AI is harder to declare)
  raw_score <= 0.35            -> likely_human
  otherwise                    -> uncertain

Two safety overrides:
  - Graceful degradation: the LLM is the primary semantic signal; if it is unavailable,
    evidence_trust is capped below the gate so the remaining surface signals can't make
    a confident accusation on their own.
  - Phrase boost: AI-cliche phrases are high-precision. A confident phrase hit lifts
    evidence_trust to at least 0.70 so clear cliche-AI isn't gated out by short length.
    (Validated on a labeled set to add 0 false positives -- see eval.py.)
"""

# --- Thresholds & weights (tunable) ---
AI_BAR = 0.75
HUMAN_BAR = 0.35
TRUST_GATE = 0.60
PHRASE_BOOST_TRUST = 0.70
LENGTH_NORM = 150
SPEAKING = 0.40          # a signal "speaks" (counts toward agreement) above this self_conf

WEIGHTS = {"llm": 0.6, "stylometry": 0.1, "phrase": 0.3}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def classify(signals: dict, word_count: int) -> dict:
    """Combine signal results (keyed by name) into the final scored attribution."""
    available = {k: v for k, v in signals.items() if v.get("available")}

    if not available:                              # every signal failed
        return {"attribution": "uncertain", "confidence": 0.0, "raw_score": None,
                "evidence_trust": 0.0, "agreement": 0.0, "degraded": True}

    # Confidence-weighted average (abstaining signals contribute ~nothing).
    den = sum(WEIGHTS[k] * v["self_confidence"] for k, v in available.items())
    if den > 0:
        raw_score = sum(WEIGHTS[k] * v["self_confidence"] * v["score"]
                        for k, v in available.items()) / den
    else:  # all available signals fully abstained -> fall back to plain weighting
        wsum = sum(WEIGHTS[k] for k in available)
        raw_score = sum(WEIGHTS[k] * v["score"] for k, v in available.items()) / wsum

    speaking = [v["score"] for v in available.values()
                if v.get("self_confidence", 0) >= SPEAKING]
    agreement = (1 - (max(speaking) - min(speaking))) if len(speaking) >= 2 else 0.0

    mean_self_conf = _mean([v.get("self_confidence", 0.0) for v in available.values()])
    length_factor = _clamp01(word_count / LENGTH_NORM)
    evidence_trust = _mean([length_factor, mean_self_conf, agreement])

    degraded = not signals.get("llm", {}).get("available")
    if degraded:
        evidence_trust = min(evidence_trust, TRUST_GATE - 0.01)

    phrase = signals.get("phrase", {})
    if phrase.get("available") and phrase.get("score", 0) >= 0.5 \
            and phrase.get("self_confidence", 0) >= 0.6:
        evidence_trust = max(evidence_trust, PHRASE_BOOST_TRUST)

    lean_strength = abs(raw_score - 0.5) * 2
    confidence = _clamp01(lean_strength * evidence_trust)

    if evidence_trust < TRUST_GATE:
        attribution = "uncertain"
    elif raw_score >= AI_BAR:
        attribution = "likely_ai"
    elif raw_score <= HUMAN_BAR:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    return {
        "attribution": attribution,
        "confidence": round(confidence, 3),
        "raw_score": round(raw_score, 3),
        "evidence_trust": round(evidence_trust, 3),
        "agreement": round(agreement, 3),
        "degraded": degraded,
    }


if __name__ == "__main__":
    # Deterministic checks: prove the ensemble matches the documented thresholds.
    def S(score, sc, avail=True):
        return {"available": avail, "score": score, "self_confidence": sc}

    cases = [
        ("strong AI agreement (all 3)",
         {"llm": S(0.95, 0.9), "stylometry": S(0.95, 0.9), "phrase": S(1.0, 1.0)}, 200, "likely_ai"),
        ("strong human, phrase abstains",
         {"llm": S(0.10, 0.9), "stylometry": S(0.10, 0.9), "phrase": S(0.0, 0.2)}, 200, "likely_human"),
        ("false positive: short plain, both lean AI",
         {"llm": S(0.70, 0.6), "stylometry": S(0.70, 0.4), "phrase": S(0.0, 0.1)}, 14, "uncertain"),
        ("cliche AI, short (phrase boost rescues)",
         {"llm": S(0.60, 0.6), "stylometry": S(0.50, 0.4), "phrase": S(1.0, 1.0)}, 40, "likely_ai"),
        ("LLM failed, surface signals strong",
         {"llm": S(None, 0.0, False), "stylometry": S(0.90, 0.9), "phrase": S(0.0, 0.2)}, 200, "uncertain"),
        ("all signals failed",
         {"llm": S(None, 0.0, False), "stylometry": S(None, 0.0, False), "phrase": S(None, 0.0, False)}, 200, "uncertain"),
    ]
    print(f"{'case':46} | {'raw':>6} {'trust':>6} | got          expected")
    print("-" * 92)
    all_ok = True
    for name, sigs, wc, exp in cases:
        r = classify(sigs, wc)
        ok = r["attribution"] == exp
        all_ok = all_ok and ok
        raw = "   n/a" if r["raw_score"] is None else f"{r['raw_score']:>6}"
        print(f"{name:46} | {raw} {r['evidence_trust']:>6} | {r['attribution']:12} "
              f"{'OK' if ok else 'FAIL (exp ' + exp + ')'}")
    print("\nALL THRESHOLD CHECKS PASS" if all_ok else "\nSOME CHECKS FAILED")
