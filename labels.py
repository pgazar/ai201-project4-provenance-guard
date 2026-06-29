"""Transparency labels (M5).

Maps an attribution bucket to the exact, reader-facing label text. The three variants
are verbatim from planning.md Section 3. Because the attribution bucket is itself
derived from the confidence score (via the scorer's thresholds), the label changes with
the score -- it is never the same text regardless of result.

Plain language, no jargon, no raw numbers. The AI variant never says "this IS AI"
(only "strong signs / may have") and is the only one that invites an appeal, because it
is the attribution that can harm a creator.
"""

LABELS = {
    "likely_ai": (
        "Likely AI-generated. Our automated check found strong signs that this text "
        "may have been created with AI. This is an automated estimate based on patterns "
        "in the writing — it is not proof. If you wrote this yourself, you can appeal "
        "this result."
    ),
    "uncertain": (
        "We couldn't determine how this was written. Our automated check could not "
        "reliably tell whether this text was written by a person or with AI help. No "
        "determination has been made, and this is not a judgment about the author."
    ),
    "likely_human": (
        "Likely human-written. Our automated check found no strong signs of AI "
        "generation in this text. This is an automated estimate, not a guarantee."
    ),
}


def generate_label(attribution: str) -> str:
    """Return the reader-facing label text for an attribution bucket.

    Falls back to the 'uncertain' label for any unexpected value -- we never want to
    accidentally show an accusatory or over-confident label.
    """
    return LABELS.get(attribution, LABELS["uncertain"])


if __name__ == "__main__":
    for bucket in ("likely_ai", "uncertain", "likely_human"):
        print(f"\n[{bucket}]\n{generate_label(bucket)}")
