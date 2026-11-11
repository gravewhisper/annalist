import ast
import hashlib
import json
import os
import sys
import time
from argparse import Namespace
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path
from typing import Callable

from .answers import cmd_answers
from .backends import parse_settings
from .book import load_book
from .boundaries import detect_volumes
from .epub import cmd_extract, extract_book
from .estimate import estimate
from .export import cmd_export
from .families import cmd_families
from .files import read_json, write_json
from .ladders import cmd_ladders, generate_ladder, ladder_needed
from .leads import cmd_leads
from .llm import ASKED, BudgetSpent, LLMError, LLMUnavailable, spent_since
from .names import slug
from .profile import cmd_profile
from .proofread import cmd_proofread
from .discover import cmd_discover
from .ending import cmd_ending, ending_status
from .read import cmd_read
from .link import cmd_link
from .relate import cmd_relate
from .render import ARCS_FILE, cmd_render
from .resolve import cmd_resolve
from .retype import cmd_retype
from .review import cmd_review
from .state import load_states, unfinished
from .survey import generate_book
from .sweep import cmd_sweep
from .template import overlapping_pairs
from .tiers import cmd_tiers
from .timelines import cmd_timelines
from .volume import cmd_open_volume, cmd_volume
from .wordings import cmd_wordings


MIN_WORDS = 300


class Run:
    def __init__(self, args):
        self.args = args
        self.workdir = Path(args.workdir).resolve()
        self.epub = Path(args.epub).resolve()

    @cached_property
    def extraction(self):
        return extract_book(self.epub, MIN_WORDS)

    @property
    def chapters(self):
        return read_json(self.workdir / "chapters.json", None) or self.extraction.chapters

    @property
    def volumes(self):
        stored = read_json(self.workdir / "volumes.json", None)
        if stored is not None and not self.args.volumes:
            return stored
        return detect_volumes(self.extraction, self.args.volumes)

    @property
    def last(self):
        return min(self.args.to or len(self.chapters), len(self.chapters))

    def state(self, n):
        return self.workdir / "state" / f"{n:04d}.json"

    def words(self, chapters):
        return sum(c["words"] for c in self.chapters if c["index"] in chapters)

    def book(self):
        return {**read_json(self.workdir / "book.json", {}), **self.backend_block()}

    def backend_block(self):
        a = self.args
        if not (a.backend or a.model or a.option):
            return {}
        block = dict(read_json(self.workdir / "book.json", {}).get("backend") or {})
        if a.backend and a.backend != block.get("name"):
            block = {"name": a.backend}
        if a.model:
            block["model"] = a.model
        for option in a.option or []:
            key, _, value = option.partition("=")
            try:
                block[key] = json.loads(value)
            except ValueError:
                block[key] = value
        return {"backend": block}

    def settings(self):
        return parse_settings(self.book(), os.environ)

    def timeline_kind(self):
        return self.book().get("timeline_kind")

    def eligible_volumes(self):
        return [v for v in self.volumes["volumes"] if v["to"] <= self.last]


def all_read(run):
    return all(run.state(n).exists() for n in range(1, run.last + 1))


def unlabelled(run):
    return [n for n in range(1, run.last + 1) if run.state(n).exists() and "timelines" not in read_json(run.state(n), {})]


def described(book):
    return {"power_system", "timeline_kind"} <= set(book) and not overlapping_pairs(book.get("extra_fields") or {})


def book_done(run):
    book = read_json(run.workdir / "book.json", {})
    return described(book) and not ladder_needed(book) and "title" in book


def run_book(run):
    if not described(read_json(run.workdir / "book.json", {})):
        generate_book(run.workdir, load_states(run.workdir, until=run.last), load_states(run.workdir, until=run.last, retypes=False), run.last)
    if ladder_needed(read_json(run.workdir / "book.json", {})):
        generate_ladder(run.workdir)
    if "title" not in read_json(run.workdir / "book.json", {}):
        write_json(run.workdir / "book.json", {**read_json(run.workdir / "book.json", {}), "title": run.extraction.title})
    book = load_book(run.workdir)
    print(f"book.json: {book['timeline_kind']} timeline, power types {', '.join(book['power_types'])}, "
          f"extra fields {', '.join(book['extra_fields']) or 'none'}")


def started_volumes(run):
    return [v for v in run.volumes["volumes"] if v["from"] <= run.last]


def run_volumes(run):
    keep = set()
    for v in started_volumes(run):
        if v["to"] <= run.last:
            keep.add(f"{slug(v['name'])}.json")
            cmd_volume(Namespace(workdir=str(run.workdir), name=v["name"], start=v["from"], end=v["to"]))
        else:
            cmd_open_volume(run.workdir, v["name"], v["from"], v["to"], run.last)
    for path in (run.workdir / "volumes").glob("*.json"):
        if path.name not in keep:
            path.unlink()
    current = {(v["name"], v["from"]) for v in run.volumes["volumes"]}
    arcs = read_json(run.workdir / ARCS_FILE, {"volumes": []})["volumes"]
    write_json(run.workdir / ARCS_FILE, {"volumes": [v for v in arcs if (v["name"], v["from"]) in current]})


def namespace(run, **kw):
    return Namespace(workdir=str(run.workdir), jobs=run.args.jobs, **kw)


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable
    inputs: tuple = ()
    outputs: Callable = lambda run: []
    purposes: tuple = ()
    done: Callable | None = None
    skip: Callable = lambda run: None
    chain: bool = False
    code: tuple = ()
    failed: Callable = lambda run: 0


def failed_items(output):
    return lambda run: sum(map(unfinished, read_json(run.workdir / output, {"questions": {}})["questions"].values()))


def failed_answers(run):
    return sum(d["verdict"] == "error" for b in read_json(run.workdir / "answers.json", {"boundaries": {}})["boundaries"].values()
               for d in b["questions"].values())


STATE = ("state", "book.json", "wordings.json")


STAGES = (
    Stage("extract", lambda run: cmd_extract(Namespace(epub=str(run.epub), workdir=str(run.workdir), min_words=MIN_WORDS,
                                                       volumes=run.args.volumes)),
          outputs=lambda run: ["chapters.json", "source.json", "volumes.json"], code=("epub",)),
    Stage("book", run_book, purposes=("book", "ladder-spec"), done=book_done),
    Stage("read", lambda run: cmd_read(Namespace(workdir=str(run.workdir), start=1, end=run.last)),
          purposes=("extract", "support", "reread", "timelines"), done=all_read, chain=True),
    Stage("timelines", lambda run: cmd_timelines(Namespace(workdir=str(run.workdir), start=None)),
          purposes=("timelines",), done=lambda run: not unlabelled(run),
          skip=lambda run: "the story is linear" if run.timeline_kind() == "linear" else None),
    Stage("wordings", lambda run: cmd_wordings(Namespace(workdir=str(run.workdir))), ("state", "book.json"),
          lambda run: ["wordings.json"], ("wordings",), code=("wordings",)),
    Stage("retype", lambda run: cmd_retype(namespace(run)), STATE, lambda run: ["types.json"], ("retype",), code=("retype",)),
    Stage("discover", lambda run: cmd_discover(namespace(run)), STATE + ("types.json",),
          lambda run: ["discover.json"], ("discover",), code=("discover",)),
    Stage("resolve", lambda run: cmd_resolve(namespace(run)), STATE + ("types.json", "discover.json"), lambda run: ["merges.json"],
          ("resolve", "reveal", "identify"), code=("resolve",)),
    Stage("relate", lambda run: cmd_relate(namespace(run)), STATE + ("types.json", "merges.json", "discover.json"),
          lambda run: ["relate.json"], ("relate",), code=("relate",)),
    Stage("link", lambda run: cmd_link(namespace(run)), STATE + ("types.json", "merges.json", "discover.json", "relate.json"),
          lambda run: ["link.json"], ("link",), code=("link",)),
    Stage("leads", lambda run: cmd_leads(namespace(run)), ("state", "types.json", "merges.json"),
          lambda run: ["leads.json"], ("repeats", "leads"), code=("leads",)),
    Stage("sweep", lambda run: cmd_sweep(namespace(run, batch=6, limit=None, only=None, budget=None)),
          ("state", "types.json", "merges.json", "leads.json", "corrections.json#questions"), lambda run: ["sweep.json"], ("sweep",), code=("sweep",),
          failed=failed_items("sweep.json")),
    Stage("tiers", lambda run: cmd_tiers(namespace(run)),
          STATE + ("types.json", "merges.json", "leads.json", "sweep.json"), lambda run: ["tiers.json"], ("tiers",), code=("tiers",)),
    Stage("profile", lambda run: cmd_profile(namespace(run, character=None)),
          STATE + ("types.json", "merges.json", "discover.json", "relate.json", "link.json", "volumes.json"), lambda run: ["profiles.json"],
          ("profile", "profile-support", "profile-field", "death", "revival"), code=("profile",)),
    Stage("ladders", lambda run: cmd_ladders(Namespace(workdir=str(run.workdir))),
          STATE + ("types.json", "merges.json", "discover.json", "relate.json", "link.json", "profiles.json"), lambda run: ["ladders.json"],
          ("ladders", "resolve", "reveal"), skip=lambda run: "the book has no power ladder" if run.book().get("ladder", {}) is None else None,
          code=("ladders", "resolve")),
    Stage("families", lambda run: cmd_families(namespace(run)),
          STATE + ("types.json", "merges.json", "discover.json", "relate.json", "link.json", "ladders.json"), lambda run: ["families.json"],
          ("families",), code=("families",)),
    Stage("answers", lambda run: cmd_answers(namespace(run, batch=3, to=run.last)),
          STATE + ("chapters.json", "types.json", "merges.json", "discover.json", "relate.json", "link.json", "leads.json", "sweep.json", "profiles.json", "volumes.json",
                   "answers.json", "corrections.json#questions"),
          lambda run: ["answers.json"], ("answers", "reread", "premise"),
          skip=lambda run: None if run.eligible_volumes() else f"no volume ends by chapter {run.last}", code=("answers",), failed=failed_answers),
    Stage("ending", lambda run: cmd_ending(namespace(run, batch=5)),
          STATE + ("chapters.json", "types.json", "merges.json", "discover.json", "relate.json", "link.json", "leads.json", "sweep.json", "tiers.json", "profiles.json",
                   "answers.json", "ending.json", "corrections.json#questions"),
          lambda run: ["ending.json"], ("ending", "reread"), skip=lambda run: ending_status(run.workdir, run.last, len(run.chapters)), code=("ending",),
          failed=failed_items("ending.json")),
    Stage("volumes", run_volumes,
          STATE + ("types.json", "merges.json", "discover.json", "relate.json", "link.json", "leads.json", "sweep.json", "tiers.json", "profiles.json", "volumes.json"),
          lambda run: [ARCS_FILE] + [f"volumes/{slug(v['name'])}.json" for v in run.eligible_volumes()], ("arcs", "arc", "volume", "events"),
          skip=lambda run: None if started_volumes(run) else "no chapter read", code=("volume",)),
    Stage("proofread", lambda run: cmd_proofread(namespace(run, to=run.last, budget=run.args.budget,
                                                           started=read_json(run.workdir / STAMPS, {}).get("started"))),
          STATE + ("chapters.json", "types.json", "merges.json", "discover.json", "relate.json", "link.json", "leads.json", "sweep.json", "profiles.json",
                   "ladders.json", "answers.json", "ending.json", "volumes.json"),
          lambda run: ["proofread.json"], ("proofread",),
          skip=lambda run: None if run.eligible_volumes() else f"no volume ends by chapter {run.last}", code=("proofread",)),
    Stage("render", lambda run: cmd_render(namespace(run, until=None, html=True)),
          STATE + ("chapters.json", "types.json", "merges.json", "discover.json", "relate.json", "link.json", "leads.json", "sweep.json", "tiers.json", "profiles.json", "answers.json",
                   "ending.json", "volumes", ARCS_FILE, "ladders.json", "corrections.json", "proofread.json"),
          lambda run: ["wiki/index.md"], ("summary", "personality", "appearance", "history"), code=("render",)),
    Stage("export", lambda run: cmd_export(Namespace(workdir=str(run.workdir), outdir=str(run.workdir / "site"), public=False, theme=None)),
          STATE + ("chapters.json", "types.json", "merges.json", "discover.json", "relate.json", "link.json", "leads.json", "sweep.json", "tiers.json", "profiles.json", "answers.json",
                   "ending.json", "volumes", ARCS_FILE, "ladders.json", "families.json", "corrections.json", "proofread.json"),
          lambda run: ["site/data/wiki.json"], code=("export", "site", "themes")),
    Stage("review", lambda run: cmd_review(Namespace(workdir=str(run.workdir))),
          STATE + ("types.json", "merges.json", "discover.json", "relate.json", "link.json", "profiles.json", "ladders.json"),
          lambda run: ["review.json", "review.md"], code=("review",)),
)


UNSTAMPED_BOOK_KEYS = ("backend", "models")
DISPLAY_BOOK_KEYS = ("title", "theme")


def file_digest(path):
    if path.name == "book.json":
        book = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k not in UNSTAMPED_BOOK_KEYS + DISPLAY_BOOK_KEYS}
        return hashlib.sha1(json.dumps(book, sort_keys=True).encode()).hexdigest()
    return hashlib.sha1(path.read_bytes()).hexdigest()


def digest(run, stage):
    h = hashlib.sha256(json.dumps({"stage": stage.name, "to": run.last}).encode())
    if stage.name == "extract":
        h.update(hashlib.sha1(run.epub.read_bytes()).digest())
        h.update(json.dumps([MIN_WORDS, run.args.volumes]).encode())
    if stage.name == "export":
        book = read_json(run.workdir / "book.json", {})
        h.update(json.dumps({k: book.get(k) for k in DISPLAY_BOOK_KEYS}, sort_keys=True).encode())
    for rel in stage.inputs:
        rel, _, key = rel.partition("#")
        path = run.workdir / rel
        if key:
            h.update(f"{rel}#{key} {json.dumps(read_json(path, {}).get(key), sort_keys=True)}\n".encode())
            continue
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path] if path.exists() else []
        h.update(f"{rel}:{len(files)}\n".encode())
        for f in files:
            h.update(f"{f.relative_to(run.workdir)} {file_digest(f)}\n".encode())
    return h.hexdigest()


PACKAGE = Path(__file__).resolve().parent


def package_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            yield from [node.module.split(".")[0]] if node.module else [a.name for a in node.names]


@cache
def code_digest(roots):
    seen, todo = set(), list(roots)
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            if (PACKAGE / f"{name}.py").exists():
                todo += package_imports(PACKAGE / f"{name}.py")
    h = hashlib.sha256()
    for name in sorted(seen):
        module = PACKAGE / f"{name}.py"
        files = [module] if module.exists() else sorted(p for p in (PACKAGE / name).rglob("*") if p.is_file())
        for f in files:
            h.update(f"{f.relative_to(PACKAGE)} {hashlib.sha1(f.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


STAMPS = "build.json"


def stamps(run):
    return read_json(run.workdir / STAMPS, {"stages": {}})["stages"]


def cache_shares(run):
    return read_json(run.workdir / STAMPS, {}).get("cache", {})


def write_stamps(run, **parts):
    write_json(run.workdir / STAMPS, {**read_json(run.workdir / STAMPS, {"stages": {}}), **parts})


def status(run, stage):
    reason = stage.skip(run)
    if reason:
        return f"skip: {reason}"
    if stage.done:
        return "done" if stage.done(run) else "run"
    stamp = stamps(run).get(stage.name)
    if stamp is None or not all((run.workdir / o).exists() for o in stage.outputs(run)):
        return "run"
    if isinstance(stamp, str):
        stamp = {"input": stamp}
    changed = [part for part, now in (("input", digest(run, stage)), ("code", code_digest(stage.code))) if stamp.get(part) != now]
    if changed:
        return f"run: {' and '.join(changed)} changed"
    failed = stage.failed(run)
    return f"run: {failed} unfinished" if failed else "done"


def export_problem(workdir):
    recorded = read_json(workdir / STAMPS, None)
    if recorded is None:
        return f"{workdir} has no {STAMPS}, so its stage outputs may come from older code"
    stamped = {name: stamp if isinstance(stamp, dict) else {"input": stamp} for name, stamp in recorded["stages"].items()}
    upstream = STAGES[:[s.name for s in STAGES].index("export")]
    changed = [s.name for s in upstream if s.name in stamped and stamped[s.name].get("code") != code_digest(s.code)]
    if changed:
        return f"the code of stage {', '.join(changed)} changed since {workdir} was built"


def cmd_export_built(args):
    problem = export_problem(Path(args.workdir).resolve())
    if problem and not args.allow_stale:
        sys.exit(f"annalist export: {problem}; run annalist build <epub> {args.workdir} first")
    cmd_export(args)


def stale(state):
    return state.startswith("run")


def stage_words(run, stage):
    if stage.name == "read":
        return run.words({n for n in range(1, run.last + 1) if not run.state(n).exists()})
    if stage.name == "timelines":
        return run.words(set(unlabelled(run)))
    if stage.name == "proofread":
        return run.words({n for v in run.eligible_volumes() for n in range(v["from"], v["to"] + 1)})
    return run.words(set(range(1, run.last + 1)))


def stage_purposes(run, stage):
    if stage.name == "read" and run.timeline_kind() == "linear":
        return tuple(p for p in stage.purposes if p != "timelines")
    if stage.name == "book" and described(run.book()):
        return ("ladder-spec",) if ladder_needed(run.book()) else ()
    return stage.purposes


def plan(run):
    settings = run.settings()
    shares = cache_shares(run)
    rows = []
    for stage in STAGES:
        state = status(run, stage)
        cost = None
        if stale(state) and stage.purposes:
            cost = estimate(settings, stage_purposes(run, stage), stage_words(run, stage), jobs=run.args.jobs, chain=stage.chain,
                            fresh=shares.get(stage.name, {}).get("fresh_share"))
        rows.append((stage, state, cost))
    return settings, rows


def money(dollars):
    return "unknown" if dollars is None else f"${dollars:,.2f}"


def duration(seconds):
    minutes = round(seconds / 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def print_plan(run, settings, rows, per_chapter=False):
    chapters = [c for c in run.chapters if c["index"] <= run.last]
    print(f"annalist build: {run.epub.name} -> {run.workdir}")
    print(f"chapters 1-{run.last} of {len(run.chapters)}, {sum(c['words'] for c in chapters):,} words; "
          f"backend {settings.backend}, model {settings.default_model or 'per purpose'}")
    if per_chapter:
        for c in chapters:
            print(f"  ch {c['index']:>4}  {c['words']:>7,}  {c['title']}")
    volumes = run.volumes
    print(f"volumes ({volumes['source']}): " + "; ".join(f"{v['name']} {v['from']}-{v['to']}" for v in volumes["volumes"]))
    if run.timeline_kind() is None:
        print("read includes timeline labelling until book.json says the story is linear")
    print(f"  {'stage':<10} {'status':<28} {'words':>10} {'est. cost':>10} {'est. time':>9} {'likely':>10}")
    total, likely, seconds = 0.0, 0.0, 0.0
    for stage, state, cost in rows:
        line = f"  {stage.name:<10} {state:<28}"
        if cost:
            line += f" {cost.words:>10,} {money(cost.dollars):>10} {duration(cost.seconds):>9}"
            line += f" {money(cost.likely):>10}" if cost.likely != cost.dollars else ""
            total = None if total is None or cost.dollars is None else total + cost.dollars
            likely = None if likely is None or cost.likely is None else likely + cost.likely
            seconds += cost.seconds
        print(line)
    tail = f" {money(likely):>10}" if likely != total else ""
    print(f"  {'total':<10} {'':<28} {'':>10} {money(total):>10} {duration(seconds):>9}{tail}")
    print("  estimates scale token rates measured on earlier runs by this backend's prices and count every prompt as new;")
    print("  likely counts only the share of prompts the cache did not answer on the stage's last rerun")
    return total, likely


def confirm(total, likely):
    if not sys.stdin.isatty():
        sys.exit("annalist build: this will spend LLM calls; pass --yes to run without asking, or --dry-run to only see the plan")
    cost = f"up to {money(total)}, likely {money(likely)}" if likely != total else f"about {money(total)}"
    answer = input(f"Run the build ({cost})? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        sys.exit("annalist build: stopped before spending anything")


def stop(stage, message):
    print(f"annalist build: stage {stage.name} stopped: {message}", file=sys.stderr)
    print("annalist build: rerun the same command to resume; finished work is kept", file=sys.stderr)
    sys.exit(2)


def run_stage(run, stage):
    rerun = stage.name in stamps(run)
    before = ASKED.copy()
    try:
        stage.run(run)
    except LLMError as exc:
        if stage.name == "book":
            stop(stage, f"book.json failed validation after every retry ({exc}); nothing was read")
        stop(stage, str(exc))
    except LLMUnavailable as exc:
        stop(stage, str(exc))
    except BudgetSpent as exc:
        print(f"annalist build: {exc}", file=sys.stderr)
        sys.exit(3)
    except SystemExit as exc:
        if exc.code not in (0, None):
            stop(stage, str(exc.code) if not isinstance(exc.code, int) else f"exit status {exc.code}")
    asked = ASKED - before
    if rerun and asked:
        write_stamps(run, cache={**cache_shares(run), stage.name: {"fresh_share": round(asked["fresh"] / asked.total(), 4)}})
    if not stage.done:
        write_stamps(run, stages={**stamps(run), stage.name: {"input": digest(run, stage), "code": code_digest(stage.code)}})


def cmd_build(args):
    if args.workdir is None:
        args.workdir = str(Path("runs") / slug(Path(args.epub).stem))
    run = Run(args)
    settings, rows = plan(run)
    total, likely = print_plan(run, settings, rows, per_chapter=args.dry_run)
    if args.dry_run:
        return
    if any(stale(state) and cost and cost.dollars != 0 for _, state, cost in rows) and not args.yes:
        confirm(total, likely)
    block = run.backend_block()
    if block:
        write_json(run.workdir / "book.json", {**read_json(run.workdir / "book.json", {}), **block})
    started = read_json(run.workdir / STAMPS, {}).get("started") or time.strftime("%Y-%m-%dT%H:%M:%S")
    write_stamps(run, started=started)
    for stage in STAGES:
        state = status(run, stage)
        if not stale(state):
            continue
        spent = spent_since(run.workdir, started)
        if args.budget is not None and spent >= args.budget:
            print(f"annalist build: spent {money(spent)} of the {money(args.budget)} budget; stopping before {stage.name}", file=sys.stderr)
            sys.exit(3)
        print(f"== {stage.name}", flush=True)
        run_stage(run, stage)
    write_json(run.workdir / STAMPS, {k: v for k, v in read_json(run.workdir / STAMPS, {}).items() if k != "started"})
    print(f"annalist build: done, {money(spent_since(run.workdir, started))} spent since this build started; "
          f"site {run.workdir / 'site'}, review {run.workdir / 'review.md'}")
    report = read_json(run.workdir / "review.json", {"checks": []})
    print("review:")
    for check in report["checks"]:
        print(f"  {len(check['findings']):>5}  {check['title']}")
    if args.strict is not None:
        gaps = next((c["findings"] for c in report["checks"] if c["key"] == "empty_fields"), [])
        if len(gaps) > args.strict:
            for gap in gaps:
                print(f"  {gap['character']}: no {', '.join(gap['missing'])}", file=sys.stderr)
            print(f"annalist build: {len(gaps)} main characters have an empty status or power field, more than the "
                  f"{args.strict} --strict allows", file=sys.stderr)
            sys.exit(4)
