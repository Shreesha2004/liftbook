"""Estimated one-rep max (e1RM) via the Brzycki formula: weight * 36 / (37 - reps).

The Python and SQL versions live side by side so they can't drift apart;
tests/test_one_rep_max.py checks that both give the same numbers.
"""

# The formula divides by zero at 37 reps; the API and a DB check constraint cap reps here.
MAX_REPS = 36

# SQL fragment for queries that alias workout_sets as "s".
E1RM_SQL = "(s.weight * 36.0 / (37 - s.reps))"


def brzycki(weight: float, reps: int) -> float:
    if not 1 <= reps <= MAX_REPS:
        raise ValueError(f"reps must be between 1 and {MAX_REPS}, got {reps}")
    return weight * 36 / (37 - reps)
