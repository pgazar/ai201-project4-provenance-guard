"""Signal B - Stylometric heuristics (structural).

Milestone 4, Step 1. A deterministic, pure-Python detection signal that measures how
structurally UNIFORM the writing is. AI text (esp. low-temperature) tends to be more
uniform; human writing is bumpier. It does NOT decide a verdict -- it returns evidence
(a continuous 0-1 AI-likelihood + how sure it is).

Three sub-metrics, each mapped to a 0-1 AI-likeness contribution (higher = more AI-like):
  burstiness  - variation in sentence length (low variation -> AI-like)
  mattr       - moving-average type-token ratio / lexical diversity (low -> AI-like)
  punctuation - variety of 'rich' punctuation marks (low variety -> AI-like)

Output shape:
  {"available": True, "score": 0.68, "self_confidence": 0.4,
   "components": {"burstiness": 0.7, "mattr": 0.6, "punctuation": 0.75}}

self_confidence drops on short text (the length guard): too few sentences/words to
judge structure reliably. That low self-confidence is what makes the M4 scorer treat
short text as honestly UNCERTAIN.

NOTE: the reference points below are HAND-CHOSEN heuristics, not learned from a corpus.
They are documented here and tunable. This is a known limitation of stylometry.
"""
import re

WINDOW = 50            # MATTR window size (words)
CV_REF = 0.7           # sentence-length coeff. of variation at/above which = fully human
MATTR_HUMAN = 0.75     # lexical diversity at/above which = fully human
MATTR_AI = 0.55        # lexical diversity at/below which = fully AI
RICH_PUNCT = set(";:—–()!?\"…")   # variety of these 'rich' marks reads human

# Sub-metric weights (burstiness is the strongest stylometric cue; documented choice).
W_BURST, W_MATTR, W_PUNCT = 0.5, 0.3, 0.2


def _sentences(text: str) -> list:
    return [p.strip() for p in re.split(r"[.!?]+", text) if p.strip()]


def _words(text: str) -> list:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _burstiness_ai(sentence_word_counts: list) -> float:
    """Low sentence-length variation -> more AI-like."""
    if len(sentence_word_counts) < 2:
        return 0.5                      # can't measure variation -> neutral
    mean = sum(sentence_word_counts) / len(sentence_word_counts)
    if mean == 0:
        return 0.5
    var = sum((n - mean) ** 2 for n in sentence_word_counts) / len(sentence_word_counts)
    cv = (var ** 0.5) / mean            # coefficient of variation
    return _clamp01(1 - cv / CV_REF)    # high CV (human) -> ~0; low CV (AI) -> ~1


def _mattr_ai(words: list) -> float:
    """Low lexical diversity -> more AI-like. Uses moving-average TTR (length-robust)."""
    if not words:
        return 0.5
    if len(words) <= WINDOW:
        mattr = len(set(words)) / len(words)
    else:
        ratios = [len(set(words[i:i + WINDOW])) / WINDOW
                  for i in range(len(words) - WINDOW + 1)]
        mattr = sum(ratios) / len(ratios)
    return _clamp01((MATTR_HUMAN - mattr) / (MATTR_HUMAN - MATTR_AI))


def _punctuation_ai(text: str) -> float:
    """Low variety of rich punctuation -> more AI-like."""
    variety = len({ch for ch in text if ch in RICH_PUNCT})
    return _clamp01(1 - variety / 3.0)  # 0 rich marks -> 1 (AI); >=3 -> 0 (human)


def run_stylometry_signal(text: str) -> dict:
    """Run Signal B on `text`. Pure Python, deterministic, never raises."""
    words = _words(text)
    sentences = _sentences(text)
    sentence_word_counts = [len(_words(s)) for s in sentences]

    burstiness = _burstiness_ai(sentence_word_counts)
    mattr = _mattr_ai(words)
    punctuation = _punctuation_ai(text)

    score = W_BURST * burstiness + W_MATTR * mattr + W_PUNCT * punctuation

    # Length guard: need enough words AND enough sentences to trust the structure.
    words_factor = _clamp01(len(words) / 150.0)
    sentence_factor = _clamp01(len(sentences) / 5.0)
    self_confidence = min(words_factor, sentence_factor)

    return {
        "available": True,
        "score": round(_clamp01(score), 3),
        "self_confidence": round(self_confidence, 3),
        "components": {
            "burstiness": round(burstiness, 3),
            "mattr": round(mattr, 3),
            "punctuation": round(punctuation, 3),
        },
    }


if __name__ == "__main__":
    # Same samples used for Signal A, so the two can be compared directly.
    samples = {
        "obvious_AI": (
            "In today's fast-paced world, effective communication is essential. "
            "There are several key benefits to consider. First, it fosters "
            "collaboration. Second, it enhances productivity. In conclusion, strong "
            "communication skills are a valuable asset in any professional setting."
        ),
        "messy_human": (
            "ok so the fridge died last night?? woke up to a puddle. great. anyway i "
            "salvaged the cheese (priorities) and now i'm sitting here at 6am writing "
            "this instead of, idk, sleeping like a normal person. send help. or coffee."
        ),
        "short": "It rained today.",
        "plain_even": "The cat sits. The dog runs. The bird flies. The sun shines. I am happy.",
    }
    for name, txt in samples.items():
        print(f"\n--- {name} ---")
        print(run_stylometry_signal(txt))
