"""Signal C - AI-register phrase detector (lexical).

Milestone 4 stretch (Ensemble). A third, independent signal: it counts multi-word
phrases characteristic of the "AI essay" register (the delve / tapestry / it is
important to note / in today's fast-paced world style). It is independent of the other
two signals -- the LLM reads meaning, stylometry counts structure, this one matches
specific lexical markers.

Deliberately uses MULTI-WORD phrases, not common single words like "however" or
"comprehensive," because those appear in formal *human* writing too. Multi-word clichés
are far more AI-specific, which keeps false positives on formal human prose low.

Output shape:
  {"available": True, "score": 0.0-1.0, "self_confidence": 0.0-1.0,
   "components": {"hits": int, "distinct": int, "per_100_words": float,
                  "matched": [phrases...]}}

Design of self_confidence: this signal is high-precision when it FIRES (these phrases
are strong AI tells) but the ABSENCE of clichés is weak evidence of a human (natural AI
has no clichés either). So it reports higher confidence when it finds markers, and stays
quiet (low confidence) when it doesn't -- it speaks up only when it has something to say.
"""
import re

# Multi-word AI-register markers (lowercased). Curated to be AI-distinctive, not generic
# formal English. Hand-chosen heuristics -- documented and tunable.
AI_PHRASES = [
    "it is important to note", "it's important to note", "it is worth noting",
    "in today's fast-paced world", "in the realm of", "in the world of",
    "navigating the complexities", "navigate the complexities",
    "delve into", "delving into", "a testament to", "testament to the",
    "plays a pivotal role", "plays a crucial role", "plays a vital role",
    "plays a significant role", "a myriad of", "a plethora of", "tapestry of",
    "rich tapestry", "ever-evolving", "ever-changing", "fast-paced", "cutting-edge",
    "game-changer", "game changer", "seamless integration", "unlock the potential",
    "harness the power", "shed light on", "at the end of the day", "last but not least",
    "first and foremost", "when it comes to", "it is essential to", "it is crucial to",
    "in conclusion", "in summary", "to sum up", "underscores the importance",
    "underscore the importance", "the importance of understanding",
    "a wide range of", "wide array of", "stand the test of time", "the digital age",
    "in an increasingly", "paving the way", "pave the way", "a deep dive",
    "the key to", "more than just", "not only ... but also",
]

D_REF = 2.5  # AI-cliche hits per 100 words at/above which score == 1.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def run_phrase_signal(text: str) -> dict:
    """Run Signal C on `text`. Pure Python, deterministic, never raises."""
    low = text.lower()
    words = _word_count(text)

    matched = []
    hits = 0
    for phrase in AI_PHRASES:
        if "..." in phrase:                      # skip the illustrative pattern marker
            continue
        count = low.count(phrase)
        if count:
            hits += count
            matched.append(phrase)
    distinct = len(matched)

    per_100 = (hits / words * 100) if words else 0.0
    score = _clamp01(per_100 / D_REF)

    length_factor = _clamp01(words / 80.0)
    if hits > 0:
        self_confidence = _clamp01(0.6 + 0.1 * distinct)   # fired -> confident
    else:
        self_confidence = 0.3 * length_factor              # silent -> weak evidence

    return {
        "available": True,
        "score": round(score, 3),
        "self_confidence": round(self_confidence, 3),
        "components": {
            "hits": hits,
            "distinct": distinct,
            "per_100_words": round(per_100, 2),
            "matched": matched,
        },
    }


if __name__ == "__main__":
    samples = {
        "AI essay (cliche-heavy)": "In today's fast-paced world, it is important to note that technology plays a pivotal role. From navigating the complexities of data to harnessing the power of innovation, organizations must delve into a myriad of strategies. In conclusion, this is a testament to the ever-evolving digital age.",
        "formal HUMAN (academic)": "The relationship between monetary policy and asset price inflation has been extensively studied. Central banks face a fundamental tension between price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations.",
        "casual HUMAN": "ok so the fridge died last night and i salvaged the cheese. now i'm up at 6am writing this instead of sleeping. send coffee.",
        "natural AI (no cliches)": "Honestly, switching to a standing desk was one of the better decisions I've made this year. The first week was rough, but after that something clicked and the afternoon slump just faded.",
    }
    for name, t in samples.items():
        print(f"\n--- {name} ---")
        print(run_phrase_signal(t))
