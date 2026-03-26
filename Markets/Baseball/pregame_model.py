"""
Statistical pre-game win probability estimator.

Uses the log5 formula (Bill James) to combine each team's historical
win percentage with a fixed home field advantage adjustment.

This is the fallback when no Kalshi market price is available (i.e.,
all games before 2025 during backtesting).

References:
    Log5: https://www.baseball-reference.com/about/log5.shtml
    MLB HFA: empirically ~54% for home teams vs equal opponents (~+4 pts)
"""

# MLB home field advantage: home teams win ~54% against an equal opponent.
# Expressed as an additive shift on the neutral-site probability.
HOME_FIELD_ADV = 0.038

# Probability clamp — never output extreme certainties from pre-game stats alone.
_MIN_PROB = 0.05
_MAX_PROB = 0.95


def log5(home_win_pct: float, away_win_pct: float) -> float:
    """
    Compute P(home team wins on a neutral field) using the log5 formula.

    log5(A, B) = (A - A*B) / (A + B - 2*A*B)

    Degrades gracefully to 0.5 when both teams have equal win% or when
    the denominator is zero.
    """
    h, a = home_win_pct, away_win_pct
    denom = h + a - 2 * h * a
    if denom == 0:
        return 0.5
    return (h - h * a) / denom


def estimate(home_win_pct: float, away_win_pct: float) -> float:
    """
    Return P(home team wins) as a percentage in [0, 100].

    Steps:
      1. Neutral-site probability via log5.
      2. Add home field advantage.
      3. Clip to [MIN_PROB, MAX_PROB] to avoid extreme outputs.
    """
    neutral = log5(home_win_pct, away_win_pct)
    prob = neutral + HOME_FIELD_ADV
    return round(max(_MIN_PROB, min(_MAX_PROB, prob)) * 100, 1)
