import pytest
from sqlalchemy import text

from app.one_rep_max import E1RM_SQL, MAX_REPS, brzycki


def test_a_single_rep_is_the_weight_itself():
    assert brzycki(100, 1) == 100


@pytest.mark.parametrize(
    ("weight", "reps", "expected"),
    [(100, 5, 112.5), (80, 10, 106.67), (60, 8, 74.48), (0, 5, 0)],
)
def test_known_values(weight, reps, expected):
    assert brzycki(weight, reps) == pytest.approx(expected, abs=0.01)


def test_more_reps_at_the_same_weight_means_a_higher_estimate():
    estimates = [brzycki(100, reps) for reps in range(1, MAX_REPS + 1)]
    assert estimates == sorted(set(estimates))


@pytest.mark.parametrize("reps", [0, -1, MAX_REPS + 1])
def test_rejects_reps_outside_the_formula_range(reps):
    with pytest.raises(ValueError):
        brzycki(100, reps)


def test_sql_and_python_formulas_agree(db):
    cases = [(w, r) for w in (0, 20, 62.5, 100, 227.5) for r in (1, 2, 5, 8, 12, 20, MAX_REPS)]
    values = ", ".join(f"(CAST({w} AS float8), {r})" for w, r in cases)
    sql_results = db.execute(
        text(f"SELECT {E1RM_SQL} FROM (VALUES {values}) AS s(weight, reps)")
    ).scalars()
    for (weight, reps), from_sql in zip(cases, sql_results, strict=True):
        assert from_sql == pytest.approx(brzycki(weight, reps))
