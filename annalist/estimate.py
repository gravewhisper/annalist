import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from .backends import ANTHROPIC_ALIASES, ANTHROPIC_PRICES, ConfigError
from .files import read_json, read_jsonl


@dataclass(frozen=True)
class Rate:
    input_tokens: float
    output_tokens: float
    wall_s: float


RATES = {
    "answers": Rate(input_tokens=2855.32, output_tokens=238.31, wall_s=1.8199),
    "arc": Rate(input_tokens=108.91, output_tokens=60.17, wall_s=0.3706),
    "arcs": Rate(input_tokens=88.99, output_tokens=0.74, wall_s=0.0109),
    "book": Rate(input_tokens=47.7, output_tokens=3.3, wall_s=0.0368),
    "death": Rate(input_tokens=843.25, output_tokens=75.01, wall_s=1.2935),
    "discover": Rate(input_tokens=85.53, output_tokens=14.02, wall_s=0.1265),
    "ending": Rate(input_tokens=2855.32, output_tokens=238.31, wall_s=1.8199),
    "events": Rate(input_tokens=219.48, output_tokens=10.54, wall_s=0.1442),
    "families": Rate(input_tokens=29.2, output_tokens=15.69, wall_s=0.1103),
    "extract": Rate(input_tokens=5531.01, output_tokens=1350.29, wall_s=8.2391),
    "judge": Rate(input_tokens=0.0, output_tokens=0.0, wall_s=0.0),
    "history": Rate(input_tokens=226.0, output_tokens=25.0, wall_s=0.35),
    "identify": Rate(input_tokens=180.0, output_tokens=12.0, wall_s=0.3),
    "link": Rate(input_tokens=96.0, output_tokens=36.4, wall_s=0.27),
    "ladder-spec": Rate(input_tokens=1.7, output_tokens=0.25, wall_s=0.01),
    "ladders": Rate(input_tokens=76.0, output_tokens=10.0, wall_s=0.2),
    "leads": Rate(input_tokens=107.4, output_tokens=16.71, wall_s=0.1243),
    "personality": Rate(input_tokens=146.26, output_tokens=43.35, wall_s=0.7052),
    "premise": Rate(input_tokens=40.0, output_tokens=8.0, wall_s=0.05),
    "profile": Rate(input_tokens=1839.22, output_tokens=578.0, wall_s=4.0735),
    "profile-field": Rate(input_tokens=969.36, output_tokens=68.95, wall_s=1.3222),
    "profile-support": Rate(input_tokens=377.52, output_tokens=108.61, wall_s=1.1326),
    "proofread": Rate(input_tokens=12821.6, output_tokens=228.7, wall_s=2.5728),
    "repeats": Rate(input_tokens=40.0, output_tokens=12.0, wall_s=0.1),
    "relate": Rate(input_tokens=2640.85, output_tokens=368.51, wall_s=2.7741),
    "reread": Rate(input_tokens=936.32, output_tokens=289.19, wall_s=3.7485),
    "reveal": Rate(input_tokens=60.0, output_tokens=5.0, wall_s=0.1),
    "resolve": Rate(input_tokens=266.53, output_tokens=24.89, wall_s=0.568),
    "revival": Rate(input_tokens=843.25, output_tokens=75.01, wall_s=1.2935),
    "retype": Rate(input_tokens=30.72, output_tokens=5.14, wall_s=0.0485),
    "summary": Rate(input_tokens=401.95, output_tokens=88.56, wall_s=1.1207),
    "support": Rate(input_tokens=922.46, output_tokens=285.76, wall_s=2.4106),
    "sweep": Rate(input_tokens=2827.37, output_tokens=186.52, wall_s=1.4525),
    "tiers": Rate(input_tokens=75.32, output_tokens=15.23, wall_s=0.1123),
    "timelines": Rate(input_tokens=3525.82, output_tokens=212.46, wall_s=2.1874),
    "volume": Rate(input_tokens=149.07, output_tokens=4.15, wall_s=0.039),
    "wordings": Rate(input_tokens=29.2, output_tokens=15.69, wall_s=0.1103),
}


def words_read(workdir):
    workdir = Path(workdir)
    read = {int(p.stem) for p in (workdir / "state").glob("[0-9][0-9][0-9][0-9].json")}
    return sum(c["words"] for c in read_json(workdir / "chapters.json", []) if c["index"] in read)


def call_tokens(row):
    usage = row.get("usage") or {}
    prompt = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return prompt, usage.get("output_tokens") or 0


def measure_rates(workdirs, purposes=None):
    words = sum(words_read(w) for w in workdirs)
    totals = {}
    for workdir in workdirs:
        for row in read_jsonl(Path(workdir) / "calls.jsonl"):
            if purposes and row["purpose"] not in purposes:
                continue
            prompt, output = call_tokens(row)
            t = totals.setdefault(row["purpose"], [0, 0, 0.0])
            t[0], t[1], t[2] = t[0] + prompt, t[1] + output, t[2] + (row.get("wall_s") or 0)
    per = 1000 / words
    return {p: Rate(round(i * per, 2), round(o * per, 2), round(w * per, 4)) for p, (i, o, w) in sorted(totals.items())}


def dollars_per_million(settings, model):
    if settings.backend == "fake":
        return {"input": 0.0, "output": 0.0}
    if settings.backend == "openai":
        return settings.options.get("prices", {}).get(model)
    prices = {**ANTHROPIC_PRICES, **settings.options.get("prices", {})}
    return prices.get(ANTHROPIC_ALIASES.get(model, model)) or prices.get(model)


@dataclass(frozen=True)
class Estimate:
    words: int
    dollars: float | None
    seconds: float
    likely: float | None


def estimate(settings, purposes, words, jobs=1, chain=False, rates=RATES, fresh=None):
    dollars, walls = 0.0, []
    for purpose in purposes:
        rate = rates[purpose]
        try:
            prices = [dollars_per_million(settings, model) for model in settings.models_for(purpose)]
        except ConfigError:
            prices = [None]
        if None in prices or dollars is None:
            dollars = None
        else:
            dollars += sum(words / 1000 * (rate.input_tokens * price["input"] + rate.output_tokens * price["output"]) / 1e6 for price in prices)
        walls.append(words / 1000 * rate.wall_s * len(prices))
    seconds = walls[0] + max(walls[1:], default=0) if chain else sum(walls) / max(1, jobs)
    likely = dollars if dollars is None or fresh is None else dollars * fresh
    return Estimate(words=words, dollars=dollars, seconds=seconds, likely=likely)


def main():
    parser = argparse.ArgumentParser(prog="python3 -m annalist.estimate",
                                     description="Print token and wall-time rates per 1,000 words read, measured from runs' calls.jsonl.")
    parser.add_argument("workdir", nargs="+")
    parser.add_argument("--purposes", help="comma-separated purposes to measure; default all")
    args = parser.parse_args()
    rates = measure_rates(args.workdir, set(args.purposes.split(",")) if args.purposes else None)
    print(json.dumps({p: r.__dict__ for p, r in rates.items()}, indent=2))


if __name__ == "__main__":
    main()
