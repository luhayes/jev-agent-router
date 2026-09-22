"""Offline, call-count-matched random fallback controls; never provider calls."""

import random

RANDOM_SEED = 42
RANDOM_TRIALS = 10_000


def random_control(rows, threshold):
    """Hold error handling fixed; randomize only fallback choices among valid Jev answers."""
    rows = sorted(rows, key=lambda r: r["id"])
    gains, forced_gain, forced_count, chosen_count = [], 0, 0, 0
    fixed, harmed, base_correct = 0, 0, 0
    for row in rows:
        jev, llm = row["jev"], row["llm"]
        jev_correct = int(jev["status"] == "ok" and jev["label"] == row["truth"])
        llm_correct = int(llm["status"] == "ok" and llm["label"] == row["truth"])
        base_correct += jev_correct
        if jev["status"] == "request_error":
            continue  # Nonrecoverable errors never become fallback candidates.
        if jev["status"] == "ok":
            gains.append(llm_correct - jev_correct)
            chosen = jev["confidence"] < threshold
            chosen_count += chosen
        else:
            chosen = True  # Recoverable errors always fall back in every trial.
            forced_count += 1
            forced_gain += llm_correct - jev_correct
        if chosen:
            fixed += llm_correct > jev_correct
            harmed += llm_correct < jev_correct
    rng = random.Random(RANDOM_SEED)
    samples = sorted(
        forced_gain + sum(rng.sample(gains, chosen_count)) for _ in range(RANDOM_TRIALS)
    )
    expected = forced_gain + (chosen_count * sum(gains) / len(gains) if gains else 0)
    observed = fixed - harmed
    return {
        "threshold": threshold,
        "count": len(rows),
        "matched_on": "fallback_call_count_not_token_cost",
        "seed": RANDOM_SEED,
        "trials": RANDOM_TRIALS,
        "forced_fallback_count": forced_count,
        "randomized_fallback_count": chosen_count,
        "fallback_count": forced_count + chosen_count,
        "jev_correct": base_correct,
        "cascade_correct": base_correct + observed,
        "corrections": fixed,
        "regressions": harmed,
        "net_correct_gain": observed,
        "random_expected_net_gain": expected,
        "random_expected_accuracy": (base_correct + expected) / len(rows),
        "random_net_gain_central_95": [samples[int(RANDOM_TRIALS * .025)], samples[int(RANDOM_TRIALS * .975) - 1]],
        "random_fraction_ge_observed": sum(g >= observed for g in samples) / RANDOM_TRIALS,
    }
