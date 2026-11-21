import sys
from argparse import Namespace
from pathlib import Path

from .build import inputs_digest, money, rendered, Run, stale, stamp, stamps, STAGES, status, STAMPS
from .corrections import PROOFREAD_FILE
from .estimate import prompt_pricer
from .export import cmd_export
from .files import read_json, run_lock
from .llm import Budget, BudgetSpent, cached_reply, LLMError, LLMUnavailable, must_hit, Unpriced
from .render import ask_all, prepare, write_view
from .vet import vet

APPLIED = ("render", "export")
UNREAD = ("extract",)
DEFAULT_MARGIN = 1.25


def dollars(amount):
    return money(amount) if amount is None or amount >= 1 else f"${amount:.4f}"


def refuse(message):
    sys.exit(f"annalist apply: {message}; nothing was asked or written")


def built_run(workdir, jobs):
    recorded = read_json(workdir / STAMPS, None)
    if recorded is None:
        refuse(f"{workdir} has no {STAMPS}; run annalist build <epub> {workdir} first")
    if recorded.get("started"):
        refuse(f"the build started {recorded['started']} has not finished; finish it with annalist build <epub> {workdir}")
    last = recorded.get("last")
    if last is None:
        last = 0
        while (workdir / "state" / f"{last + 1:04d}.json").exists():
            last += 1
    return Run(Namespace(workdir=str(workdir), epub=None, to=last, volumes=None, jobs=jobs, budget=None, backend=None, model=None, option=None))


def ran(run, stage):
    if stage.done:
        return stage.done(run)
    return stage.name in stamps(run) and all((run.workdir / o).exists() for o in stage.outputs(run))


def unbuilt(run):
    upstream = STAGES[:[s.name for s in STAGES].index("render")]
    return next((s.name for s in upstream if not s.skip(run) and not ran(run, s)), None)


def leftovers(run):
    return [(stage.name, state) for stage in STAGES if stage.name not in APPLIED + UNREAD and stale(state := status(run, stage))]


def priced_misses(workdir, settings, asks):
    price = prompt_pricer(workdir, settings)
    return {a: price(a.purpose, a.prompt) for a in dict.fromkeys(asks) if cached_reply(workdir, a.purpose, a.prompt, settings) is None}


def total(prices):
    return None if None in prices.values() else sum(prices.values())


def print_quote(asks, misses):
    print(f"render: {len(set(asks))} prompts, {len(misses)} not answered yet")
    by_purpose = {}
    for a, price in misses.items():
        by_purpose.setdefault(a.purpose, []).append((a, price))
    for purpose, rows in sorted(by_purpose.items()):
        pages = list(dict.fromkeys(a.page for a, _ in rows))
        shown = ", ".join(pages[:5]) + (f" and {len(pages) - 5} more" if len(pages) > 5 else "")
        print(f"  {purpose:<12} {len(rows):>5}  {dollars(total(dict(rows))):>10}  {shown}")
    print(f"price: {dollars(total(misses))}")


def budget_cap(args, price):
    if args.budget is not None:
        return args.budget
    if price is None:
        refuse("a model has no price in book.json, so pass --budget")
    if args.yes:
        refuse(f"pass --budget with --yes; the price is {dollars(price)}")
    if not sys.stdin.isatty():
        refuse("this will spend LLM calls; pass --yes and --budget to run without asking, or --dry-run to only see the price")
    cap = price * DEFAULT_MARGIN
    if input(f"Pay up to {dollars(cap)}? [y/N] ").strip().lower() not in ("y", "yes"):
        refuse("stopped before spending anything")
    return cap


def cmd_apply(args):
    workdir = Path(args.workdir).resolve()
    with run_lock(workdir, "apply"):
        run = built_run(workdir, args.jobs)
        missing = unbuilt(run)
        if missing:
            refuse(f"stage {missing} has not run; run annalist build <epub> {workdir} first")
        stages = {s.name: s for s in STAGES}
        before = {name: inputs_digest(run, stages[name]) for name in APPLIED}
        targets = rendered(run)
        whole = prepare(workdir, None)
        reader = [p for p in whole.problems if not p.startswith(PROOFREAD_FILE)]
        if reader:
            refuse("these corrections.json rows would be skipped:\n" + "\n".join(f"  {p}" for p in reader)
                   + "\nfix them and run annalist apply again")
        asks = whole.asks()
        del whole
        asks += [a for t in targets if t is not None for a in prepare(workdir, t).asks()]
        settings = run.settings()
        misses = priced_misses(workdir, settings, asks)
        left = leftovers(run)
        if left:
            print("stale until the next annalist build, which apply does not run:")
            for name, state in left:
                print(f"  {name:<10} {state}")
        print_quote(asks, misses)
        if args.dry_run:
            print("annalist apply: dry run, nothing asked or written")
            return
        price = total(misses)
        cap = budget_cap(args, price) if misses and price != 0 else 0.0
        budget = Budget(cap, {(a.purpose, a.prompt): estimate or 0.0 for a, estimate in misses.items()})
        try:
            ask_all(workdir, list(misses), args.jobs, budget)
        except BudgetSpent as exc:
            print(f"annalist apply: {exc}; the replies paid for are kept, so a rerun prices only the rest. No page was written.", file=sys.stderr)
            sys.exit(3)
        except (LLMError, LLMUnavailable, Unpriced) as exc:
            print(f"annalist apply: {exc}; the replies paid for are kept. No page was written.", file=sys.stderr)
            sys.exit(2)
        for until in targets:
            write_view(prepare(workdir, until), must_hit(workdir), True)
        cmd_export(Namespace(workdir=str(workdir), outdir=str(workdir / "site"), public=False, theme=None))
        for name in APPLIED:
            stamp(run, stages[name], before[name])
        print(f"annalist apply: done, {dollars(budget.spent)} spent; site {workdir / 'site'}")


def cmd_vet(args):
    workdir = Path(args.workdir).resolve()
    if not args.dry_run and args.budget is None:
        sys.exit("annalist vet: pass --budget to spend, or --dry-run to only see the price")
    with run_lock(workdir, "vet"):
        run = built_run(workdir, args.jobs)
        stage = next(s for s in STAGES if s.name == "vet")
        before = inputs_digest(run, stage)
        vet(workdir, args.jobs, args.dry_run, args.budget)
        if not args.dry_run:
            stamp(run, stage, before)
