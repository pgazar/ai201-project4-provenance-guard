"""eval.py - tiny labeled benchmark for the detection pipeline.

Runs a small hand-labeled set through the REAL pipeline (the three signals + the live
scorer in scorer.py) and reports how it does -- so any change to signals, weights, or
thresholds can be measured instead of guessed. Run:  python eval.py

This is a smoke-test-sized set, not a research benchmark. Its value is catching
regressions and making tuning decisions evidence-based. The most important metric on a
writing platform is FALSE POSITIVES (a human wrongly flagged likely_ai) -- that should
stay at zero.
"""
import re

from llm_signal import run_llm_signal
from stylometry import run_stylometry_signal
from signal_phrases import run_phrase_signal
from scorer import classify


def _wc(t):
    return len(re.findall(r"[A-Za-z0-9']+", t))


# Ground-truth labeled set: "H" = human, "AI" = AI-generated.
LABELED = [
    ("H", "casual ramen", "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. probably won't go back unless someone drags me"),
    ("H", "formal academic", "The relationship between monetary policy and asset price inflation has been extensively studied. Central banks face a fundamental tension between price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations."),
    ("H", "long narrative", "I never planned to keep bees. It started with a swarm on my neighbor's mailbox one Tuesday, thousands of them humming like a small engine. Carl, who is eighty-three and unbothered by most things, just shrugged. So I called a guy. The guy didn't show. Long story short: I now own a hive, three stings, and a smoker I barely know how to use."),
    ("H", "casual fridge", "ok so the fridge died last night and i salvaged the cheese. now i'm up at 6am writing this instead of sleeping. send coffee, send help, send anything really"),
    ("H", "plain / ESL short", "The cat sits. The dog runs. The bird flies. The sun shines. I am happy."),
    ("H", "human w/ cliche", "Look, at the end of the day I just want the team to ship something we are proud of. We have been arguing about the roadmap for weeks and honestly it is exhausting and I am tired of it."),
    ("AI", "cliche essay", "In today's fast-paced world, it is important to note that technology plays a pivotal role. From navigating the complexities of data to harnessing the power of innovation, organizations must delve into a myriad of strategies. In conclusion, this is a testament to the ever-evolving digital age."),
    ("AI", "templated comm", "In today's fast-paced world, effective communication is essential. There are several key benefits to consider. First, it fosters collaboration. Second, it enhances productivity. In conclusion, strong communication skills are a valuable asset in any professional setting."),
    ("AI", "natural conversational", "Honestly, switching to a standing desk was one of the better decisions I've made this year. The first week was rough, but after that something clicked. I feel more alert in the afternoons and the mid-day slump I used to fight just faded."),
    ("AI", "natural reflective", "There's a quiet kind of joy in cooking for people you love. You chop, you stir, you taste as you go, and somewhere in that rhythm the day's stress loosens its grip. What lingers is the warmth of the table and the easy conversation."),
    ("AI", "robotic uniform", "The system collects data every day. The system stores data every day. The system analyzes data every day. The system reports data every day. The system updates data every day. The system protects data every day. The system manages data every day. The system reviews data every day."),
    ("AI", "normal chatbot", "Great question! There are a few key things to consider when choosing a programming language. First, think about your goals. If you want to build websites, JavaScript is essential. Python is excellent for beginners and data science. Ultimately, the best language depends on what you want to create."),
]


def main():
    print(f"{'truth':5} {'sample':24} {'LLM':>4} {'STY':>4} {'PHR':>4} {'raw':>6} {'conf':>5} | attribution")
    print("-" * 86)
    fp = caught = soft = 0
    n_h = sum(1 for t, _, _ in LABELED if t == "H")
    n_ai = sum(1 for t, _, _ in LABELED if t == "AI")
    for truth, name, text in LABELED:
        signals = {
            "llm": run_llm_signal(text),
            "stylometry": run_stylometry_signal(text),
            "phrase": run_phrase_signal(text),
        }
        r = classify(signals, _wc(text))
        a = r["attribution"]
        print(f"{truth:5} {name:24} {signals['llm']['score']:>4} "
              f"{signals['stylometry']['score']:>4} {signals['phrase']['score']:>4} "
              f"{r['raw_score']:>6} {r['confidence']:>5} | {a}")
        if truth == "H" and a == "likely_ai":
            fp += 1
        if truth == "AI":
            if a == "likely_ai":
                caught += 1
            elif a == "uncertain":
                soft += 1
    print("-" * 86)
    print(f"AI caught (likely_ai):      {caught}/{n_ai}")
    print(f"AI soft-missed (uncertain): {soft}/{n_ai}   (acceptable: not accused)")
    print(f"FALSE POSITIVES (H->AI):    {fp}/{n_h}   (must stay 0)")


if __name__ == "__main__":
    main()
