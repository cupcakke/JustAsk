import math
import random
from typing import Dict, List, Tuple
from .skills import ALL_L_KEYS

C = math.sqrt(2)


def _ensure(stats: Dict, key: str) -> Dict:
    if key not in stats:
        stats[key] = {"visits": 0, "rewards_sum": 0.0, "rewards": [], "successes": 0}
    return stats[key]


def _avg(s: Dict) -> float:
    v = max(1, s["visits"])
    return s["rewards_sum"] / v


def total_visits(stats: Dict) -> int:
    return sum(s.get("visits", 0) for s in stats.values())


def _pseudo(n: int) -> int:
    return max(1, n)


def ucb_score(stats: Dict, key: str, n_total: int) -> float:
    s = _ensure(stats, key)
    pseudo_visits = max(1, s["visits"])
    avg = (s["rewards_sum"] + 0.5) / (pseudo_visits + 1)
    bonus = C * math.sqrt(math.log(_pseudo(n_total) + 1) / pseudo_visits)
    return avg + bonus


def rank_all(stats: Dict) -> List[Tuple[str, float]]:
    keys = set(list(stats.keys()) + ALL_L_KEYS)
    n = total_visits(stats)
    scored = [(k, ucb_score(stats, k, n)) for k in keys]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def select_next(stats: Dict, rules_for_arch: List[Dict], architecture: str) -> str:
    ranking = rank_all(stats)
    if rules_for_arch:
        high_conf = [r for r in rules_for_arch if r.get("confidence") == "high"]
        medium_conf = [r for r in rules_for_arch if r.get("confidence") == "medium"]
        pool = high_conf + medium_conf
        if pool and random.random() < 0.65:
            rule = random.choice(pool)
            skills = rule.get("skills") or []
            if skills:
                n = total_visits(stats)
                best = max(skills, key=lambda sk: ucb_score(stats, sk, n))
                if ucb_score(stats, best, n) >= ranking[0][1] * 0.7:
                    return best
    return ranking[0][0]


def record_attempt(stats: Dict, combo: str, reward: float):
    s = _ensure(stats, combo)
    s["visits"] += 1
    s["rewards_sum"] += reward
    s["rewards"].append(reward)
    if reward >= 0.8:
        s["successes"] += 1


def reward_bucket(score: float) -> float:
    if score < 0.2:
        return 0.0
    if score < 0.4:
        return 0.25
    if score < 0.6:
        return 0.5
    if score < 0.8:
        return 0.75
    return 1.0
