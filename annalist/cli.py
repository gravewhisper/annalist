import argparse
import sys

from .backends import ConfigError
from .llm import BudgetSpent
from .build import cmd_build, cmd_export_built
from .epub import cmd_extract
from .leads import cmd_leads
from .profile import cmd_profile
from .proofread import cmd_proofread
from .read import cmd_read
from .render import cmd_render
from .discover import cmd_discover
from .families import cmd_families
from .ladders import cmd_ladders
from .link import cmd_link
from .relate import cmd_relate
from .resolve import cmd_resolve
from .scorecard import cmd_eval
from .serve import cmd_serve
from .retype import cmd_retype
from .newtypes import cmd_newtypes
from .review import cmd_review
from .survey import cmd_book
from .answers import cmd_answers
from .ending import cmd_ending
from .sweep import cmd_sweep
from .tiers import cmd_tiers
from .timelines import cmd_timelines
from .verify import cmd_verify
from .volume import cmd_volume
from .wordings import cmd_wordings


def main():
    parser = argparse.ArgumentParser(prog="annalist")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", description="Run every stage from epub to site and review, skipping stages whose outputs are current.")
    p.add_argument("epub")
    p.add_argument("workdir", nargs="?", help="default: runs/<epub name>")
    p.add_argument("--to", type=int, help="read only chapters 1 to N")
    p.add_argument("--yes", action="store_true", help="run without asking after printing the estimate")
    p.add_argument("--dry-run", action="store_true", help="print chapter word counts and the plan with estimated cost and time, then stop")
    p.add_argument("--volumes", help='chapter ranges of the volumes, such as "1-213,214-482" or "Dawn=1-213,Exile=214-482"')
    p.add_argument("--jobs", type=int, default=6)
    p.add_argument("--budget", type=float, help="stop before the next stage once this build has spent this many dollars, counting the earlier invocations it resumes")
    p.add_argument("--strict", type=int, nargs="?", const=0, metavar="N",
                   help="exit 4 when more than N (default 0) main characters have an empty status or power field in the review")
    p.add_argument("--backend", help="backend name written to book.json: claude-cli, anthropic, openai, or fake")
    p.add_argument("--model", help="backend model written to book.json")
    p.add_argument("--option", action="append", help="backend option KEY=VALUE written to book.json; repeat for more")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("serve", description="Serve a built wiki on this computer and save the notes its report button sends to reader-notes.jsonl.")
    p.add_argument("workdir")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("extract")
    p.add_argument("epub")
    p.add_argument("workdir")
    p.add_argument("--min-words", type=int, default=300)
    p.add_argument("--volumes", help='chapter ranges of the volumes, such as "1-213,214-482"; default: detected from the epub')
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("read")
    p.add_argument("workdir")
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", dest="end", type=int, required=True)
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("verify")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("book")
    p.add_argument("workdir")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_book)

    p = sub.add_parser("timelines")
    p.add_argument("workdir")
    p.add_argument("--from", dest="start", type=int, help="relabel this chapter and every later one, even if already labelled")
    p.set_defaults(func=cmd_timelines)

    p = sub.add_parser("retype")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_retype)

    p = sub.add_parser("newtypes", description="Add a type at each finished volume end for a new kind of entry the book has brought in.")
    p.add_argument("workdir")
    p.add_argument("--to", type=int, help="last chapter to consider; default: every chapter read")
    p.set_defaults(func=cmd_newtypes)

    p = sub.add_parser("leads")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_leads)

    p = sub.add_parser("sweep")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--batch", type=int, default=6)
    p.add_argument("--limit", type=int)
    p.add_argument("--only", action="append", help="sweep only this question id; repeat for more")
    p.add_argument("--budget", type=float, help="stop starting batches once this run has spent this many dollars")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("answers", description="Look for answers, leads and false premises to the questions still open at each volume end.")
    p.add_argument("workdir")
    p.add_argument("--to", type=int, help="last chapter read; default every chapter with a state file")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--batch", type=int, default=5)
    p.set_defaults(func=cmd_answers)

    p = sub.add_parser("ending", description="Judge the questions still open at the end of a complete book.")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--batch", type=int, default=5)
    p.set_defaults(func=cmd_ending)

    p = sub.add_parser("tiers")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_tiers)

    p = sub.add_parser("resolve")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("discover", help="add entries for names that recur in the text but the read never listed")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("ladders", help="rank the power ladder steps of each group from the evidence the wiki holds")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_ladders)

    p = sub.add_parser("relate", help="add relations each chapter shows between entries it names close together")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_relate)

    p = sub.add_parser("link", help="add relations that possessive entry names and character facts state")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("wordings", help="split each older one-piece relation wording once into its predicate and the detail after the target")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_wordings)

    p = sub.add_parser("families", help="read each relation wording the rules cannot settle once, to colour the graph by kind")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_families)

    p = sub.add_parser("profile")
    p.add_argument("workdir")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--character", action="append", help="profile only this character; repeat for more")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("proofread", description="Review the wiki of each finished volume against the volume's full text and write "
                                                 "the corrections that pass the quote and chapter checks to proofread.json.")
    p.add_argument("workdir")
    p.add_argument("--to", type=int, help="last chapter read; default every chapter with a state file")
    p.add_argument("--budget", type=float, help="stop before the next uncached session once this run has spent this many dollars")
    p.set_defaults(func=cmd_proofread, started=None)

    p = sub.add_parser("render")
    p.add_argument("workdir")
    p.add_argument("--until", type=int)
    p.add_argument("--html", action="store_true")
    p.add_argument("--jobs", type=int, default=4)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("volume")
    p.add_argument("workdir")
    p.add_argument("--name", required=True)
    p.add_argument("--from", dest="start", type=int, required=True)
    p.add_argument("--to", dest="end", type=int, required=True)
    p.set_defaults(func=cmd_volume)

    p = sub.add_parser("review", description="Write review.md and review.json: problems in a run that code can find.")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("export", description="Write a static, spoiler-filtered wiki site for a run.")
    p.add_argument("workdir")
    p.add_argument("outdir")
    p.add_argument("--public", action="store_true", help="never write chapter text; drop quotes unless book.json sets public_domain")
    p.add_argument("--theme", help="JSON file merged over book.json (title, theme, public_domain)")
    p.add_argument("--allow-stale", action="store_true", help="export even if pipeline code changed since the last build")
    p.set_defaults(func=cmd_export_built)

    p = sub.add_parser("eval", description="Score a built wiki against a gold file and write eval.md and eval.json, "
                                           "and against a reader key and write reader-eval.md and reader-eval.json.")
    p.add_argument("workdir")
    p.add_argument("gold", nargs="?")
    p.add_argument("--reader-key", help="JSON file of a reader's questions, answers, merges, relations and structure to grade")
    p.add_argument("--judge-model", help="model that judges the reader key and the relation sample; default: book.json's model for judge")
    p.add_argument("--relation-sample", type=int, metavar="N",
                   help="ask the judge whether N relations, picked by a fixed seed, are correct as worded given their quotes; "
                        "costs money and adds a relation_precision section to eval.md and eval.json")
    p.add_argument("--out", help="directory for the reports; default: the workdir")
    p.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ConfigError, BudgetSpent) as exc:
        sys.exit(f"annalist: {exc}")
