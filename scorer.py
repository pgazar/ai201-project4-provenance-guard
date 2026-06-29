"""Confidence Scorer (M4).

Combines Signal A (LLM) and Signal B (stylometry) into a single calibrated result:
raw_score, evidence_trust, confidence, and an attribution bucket. Implements the
algorithm in planning.md Section 2 exactly.

  raw_score      = weighted average of available signal scores (0.5 / 0.5)
  agreement      = 1 - |scoreA - scoreB|   (0 if only one signal)
  length_factor  = clamp(word_count / 150)
  mean_self_conf = mean of each signal's self_confidence (failed signal contributes 0)
  evidence_trust = mean(length_factor, mean_self_conf, agreement)
  lean_strength  = |raw_score - 0.5| * 2
  confidence     = lean_strength * evidence_trust

  attribution:
    evidence_trust < 0.60        -> uncertain   (reliability gate)
    raw_score >= 0.85            -> likely_ai
    raw_score <= 0.35            -> likely_human
    otherwise                    -> uncertain

Single-signal failure (graceful degradation, planning.md Part 10): the failed signal's
self_confidence counts as 0 AND evidence_trust is capped below the gate, so a lone
surviving signal can NEVER reach a high-confidence (likely_*) attribution.
"""

# --- Thresholds (from planning.md; tunable in this milestone) ---
AI_BAR = 0.75
HUMAN_BAR = 0.35
TRUST_GATE = 0.60
W_A = 0.5
W_B = 0.5
LENGTH_NORM = 150        # words at/above which length_factor == 1.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def classify(sig_a: dict, sig_b: dict, word_count: int) -> dict:
    """Combine two signal results into the final scored attribution."""
    a_ok = bool(sig_a.get("available"))
    b_ok = bool(sig_b.get("available"))

    # Weighted average over AVAILABLE signals only (renormalize weights).
    weighted = []
    if a_ok:
        weighted.append((W_A, sig_a["score"]))
    if b_ok:
        weighted.append((W_B, sig_b["score"]))

    if not weighted:                       # both signals failed
        return {"attribution": "uncertain", "confidence": 0.0, "raw_score": None,
                "evidence_trust": 0.0, "agreement": 0.0, "degraded": True}

    wsum = sum(w for w, _ in weighted)
    raw_score = sum(w * s for w, s in weighted) / wsum

    # Agreement is only meaningful with both signals present.
    agreement = (1 - abs(sig_a["score"] - sig_b["score"])) if (a_ok and b_ok) else 0.0

    mean_self_conf = _mean([
        sig_a.get("self_confidence", 0.0) if a_ok else 0.0,
        sig_b.get("self_confidence", 0.0) if b_ok else 0.0,
    ])

    length_factor = _clamp01(word_count / LENGTH_NORM)
    evidence_trust = _mean([length_factor, mean_self_conf, agreement])

    degraded = not (a_ok and b_ok)
    if degraded:
        # Safety: a single surviving signal can never clear the reliability gate.
        evidence_trust = min(evidence_trust, TRUST_GATE - 0.01)

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
    # Deterministic checks: prove the scorer matches the planning.md thresholds,
    # with no LLM variance. (score, self_confidence, available)
    def S(score, sc, avail=True):
        return {"available": avail, "score": score, "self_confidence": sc}

    cases = [
        ("strong AI agreement",                 S(0.95, 0.9), S(0.95, 0.9), 200, "likely_ai"),
        ("strong human agreement",              S(0.10, 0.9), S(0.10, 0.9), 200, "likely_human"),
        ("false positive: short plain, both lean AI", S(0.70, 0.6), S(0.70, 0.1), 14, "uncertain"),
        ("signals disagree",                    S(0.80, 0.7), S(0.30, 0.7), 200, "uncertain"),
        ("Signal A failed, B strongly AI",      S(None, 0.0, False), S(0.90, 0.9), 200, "uncertain"),
        ("both signals failed",                 S(None, 0.0, False), S(None, 0.0, False), 200, "uncertain"),
    ]
    print(f"{'case':46} | {'raw':>5} {'trust':>6} {'conf':>5} | got          expected")
    print("-" * 92)
    all_ok = True
    for name, a, b, wc, exp in cases:
        r = classify(a, b, wc)
        ok = r["attribution"] == exp
        all_ok = all_ok and ok
        raw = "  n/a" if r["raw_score"] is None else f"{r['raw_score']:>5}"
        print(f"{name:46} | {raw} {r['evidence_trust']:>6} {r['confidence']:>5} | "
              f"{r['attribution']:12} {'OK' if ok else 'FAIL (exp ' + exp + ')'}")
    print("\nALL THRESHOLD CHECKS PASS" if all_ok else "\nSOME CHECKS FAILED")
