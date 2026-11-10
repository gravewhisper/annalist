---------------------------- MODULE ReadPipeline ----------------------------
(***************************************************************************)
(* The read stage of annalist/read.py (cmd_read and its helpers), as of    *)
(* the sync commit in ../SKILL.md. One main thread extracts chapters in    *)
(* order. A one-worker pool runs the support check of the previous         *)
(* chapter while the next chapter is extracted. Chapters are saved one at  *)
(* a time, each only after its check finished. Any LLM call can fail, and  *)
(* the process can be killed at any point. The user then reruns the same   *)
(* command, possibly with a different --to.                                *)
(*                                                                         *)
(* A chapter's extraction is a fresh version number, so the model does not *)
(* rely on the reply cache returning the same reply on a rerun.            *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    N,          \* chapters in the book
    MaxFaults   \* failed extracts + failed checks + kills, over all runs

Chapters == 1..N
None == [none |-> TRUE]

VARIABLES
    disk,     \* state/NNNN.json per chapter: None, or [ver, saw]
    mem,      \* chapters applied to the in-memory kb: set of <<ch, ver, tag>>
    pc,       \* where the main thread is
    n,        \* the loop index in cmd_read
    end,      \* args.end (--to) of this run
    out,      \* the extraction just returned for chapter n: [ver, saw]
    pending,  \* None, or [n, ver, saw, check] for the chapter whose check runs
    stopN,    \* the n passed to stop_reading
    ver,      \* last extraction version handed out
    faults,   \* faults used so far, all runs
    faulted   \* this run hit a failed call

vars == <<disk, mem, pc, n, end, out, pending, stopN, ver, faults, faulted>>

Saved(c) == disk[c] # None
Alive == pc \notin {"down", "exit", "errOrder", "errLater"}

\* cmd_read line 57: load_states reads every state file, all as checked.
Loaded == {<<c, disk[c].ver, "checked">> : c \in {d \in Chapters : Saved(d)}}

\* extract_chapter / with_unchecked: the kb, plus the previous chapter's
\* unchecked extraction when its check is still pending.
View == mem \cup (IF pending = None THEN {} ELSE {<<pending.n, pending.ver, "unchecked">>})

Init ==
    /\ disk = [c \in Chapters |-> None]
    /\ mem = {}
    /\ pc = "down"
    /\ n = 1 /\ end = N /\ out = None /\ pending = None /\ stopN = 0
    /\ ver = 0 /\ faults = 0 /\ faulted = FALSE

-----------------------------------------------------------------------------
(* The user runs `annalist build` (or `annalist read --to E`) again.       *)
Run ==
    /\ pc \in {"down", "exit"}
    /\ \E e \in Chapters :
         /\ end' = e
         /\ mem' = Loaded
         /\ pc' = "top" /\ n' = 1 /\ pending' = None /\ out' = None /\ faulted' = FALSE
    /\ UNCHANGED <<disk, stopN, ver, faults>>

(* Lines 64-67: past --to, or this chapter is already saved.               *)
LoopEnd ==
    /\ pc = "top" /\ n > end
    /\ pc' = "final"
    /\ UNCHANGED <<disk, mem, n, end, out, pending, stopN, ver, faults, faulted>>

SkipSaved ==
    /\ pc = "top" /\ n <= end /\ Saved(n)
    /\ n' = n + 1
    /\ UNCHANGED <<disk, mem, pc, end, out, pending, stopN, ver, faults, faulted>>

(* Line 68: refuse to read out of order.                                   *)
RefuseOrder ==
    /\ pc = "top" /\ n <= end /\ ~Saved(n)
    /\ n > 1 /\ ~Saved(n - 1) /\ ~(pending # None /\ pending.n = n - 1)
    /\ pc' = "errOrder"
    /\ UNCHANGED <<disk, mem, n, end, out, pending, stopN, ver, faults, faulted>>

ReadyToExtract ==
    /\ pc = "top" /\ n <= end /\ ~Saved(n)
    /\ ~(n > 1 /\ ~Saved(n - 1) /\ ~(pending # None /\ pending.n = n - 1))

(* Lines 70-73: refuse when later chapters were saved against a gap.       *)
RefuseLater ==
    /\ ReadyToExtract
    /\ \E c \in Chapters : c > n /\ Saved(c)
    /\ pc' = "errLater"
    /\ UNCHANGED <<disk, mem, n, end, out, pending, stopN, ver, faults, faulted>>

(* Line 75: extract_chapter makes one LLM call on the view.                *)
ExtractOk ==
    /\ ReadyToExtract
    /\ ~\E c \in Chapters : c > n /\ Saved(c)
    /\ ver' = ver + 1
    /\ out' = [ver |-> ver + 1, saw |-> View]
    /\ pc' = "afterExtract"
    /\ UNCHANGED <<disk, mem, n, end, pending, stopN, faults, faulted>>

(* Lines 80-81: the extract fails; stop_reading(pending, n).               *)
ExtractFails ==
    /\ ReadyToExtract
    /\ ~\E c \in Chapters : c > n /\ Saved(c)
    /\ faults < MaxFaults
    /\ faults' = faults + 1 /\ faulted' = TRUE
    /\ pc' = "stop" /\ stopN' = n
    /\ UNCHANGED <<disk, mem, n, end, out, pending, ver>>

\* save_checked: wait for the check, write the state file, apply it to kb.
SaveDisk(p) == [disk EXCEPT ![p.n] = [ver |-> p.ver, saw |-> p.saw]]
SaveMem(p) == mem \cup {<<p.n, p.ver, "checked">>}

(* Lines 76-79: save the previous chapter, then submit this chapter's check.*)
NoPendingSubmit ==
    /\ pc = "afterExtract" /\ pending = None
    /\ pending' = [n |-> n, ver |-> out.ver, saw |-> out.saw, check |-> "running"]
    /\ n' = n + 1 /\ pc' = "top"
    /\ UNCHANGED <<disk, mem, end, out, stopN, ver, faults, faulted>>

SavePendingThenSubmit ==
    /\ pc = "afterExtract" /\ pending # None /\ pending.check = "ok"
    /\ disk' = SaveDisk(pending) /\ mem' = SaveMem(pending)
    /\ pending' = [n |-> n, ver |-> out.ver, saw |-> out.saw, check |-> "running"]
    /\ n' = n + 1 /\ pc' = "top"
    /\ UNCHANGED <<end, out, stopN, ver, faults, faulted>>

(* Line 77 raises because the check failed; stop_reading(pending, n).      *)
PendingCheckFailed ==
    /\ pc = "afterExtract" /\ pending # None /\ pending.check = "failed"
    /\ pc' = "stop" /\ stopN' = n
    /\ UNCHANGED <<disk, mem, n, end, out, pending, ver, faults, faulted>>

(* Lines 90-98: stop_reading saves an earlier unsaved pending, then exits. *)
StopSaves ==
    /\ pc = "stop" /\ pending # None /\ pending.n < stopN /\ ~Saved(pending.n)
    /\ pending.check = "ok"
    /\ disk' = SaveDisk(pending) /\ mem' = SaveMem(pending)
    /\ pc' = "exit"
    /\ UNCHANGED <<n, end, out, pending, stopN, ver, faults, faulted>>

StopExits ==
    /\ pc = "stop"
    /\ \/ ~(pending # None /\ pending.n < stopN /\ ~Saved(pending.n))
       \/ (pending # None /\ pending.check = "failed")
    /\ pc' = "exit"
    /\ UNCHANGED <<disk, mem, n, end, out, pending, stopN, ver, faults, faulted>>

(* Lines 82-86: after the loop, save the last pending chapter.             *)
FinalSave ==
    /\ pc = "final" /\ pending # None /\ pending.check = "ok"
    /\ disk' = SaveDisk(pending) /\ mem' = SaveMem(pending)
    /\ pc' = "exit"
    /\ UNCHANGED <<n, end, out, pending, stopN, ver, faults, faulted>>

FinalExits ==
    /\ pc = "final"
    /\ \/ pending = None
       \/ (pending # None /\ pending.check = "failed")   \* stop_reading(None, ...) just exits
    /\ pc' = "exit"
    /\ UNCHANGED <<disk, mem, n, end, out, pending, stopN, ver, faults, faulted>>

(* checked_state on the one-worker pool: the audit and rereads finish.     *)
CheckOk ==
    /\ Alive /\ pending # None /\ pending.check = "running"
    /\ pending' = [pending EXCEPT !.check = "ok"]
    /\ UNCHANGED <<disk, mem, pc, n, end, out, stopN, ver, faults, faulted>>

CheckFails ==
    /\ Alive /\ pending # None /\ pending.check = "running"
    /\ faults < MaxFaults
    /\ pending' = [pending EXCEPT !.check = "failed"]
    /\ faults' = faults + 1 /\ faulted' = TRUE
    /\ UNCHANGED <<disk, mem, pc, n, end, out, stopN, ver>>

(* The process dies (kill, crash, Ctrl-C). write_atomic keeps each state   *)
(* file whole or absent, so only memory is lost.                           *)
Killed ==
    /\ Alive /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ pc' = "down" /\ mem' = {} /\ pending' = None /\ out' = None
    /\ UNCHANGED <<disk, n, end, stopN, ver, faulted>>

Next ==
    \/ Run \/ LoopEnd \/ SkipSaved \/ RefuseOrder \/ RefuseLater
    \/ ExtractOk \/ ExtractFails
    \/ NoPendingSubmit \/ SavePendingThenSubmit \/ PendingCheckFailed
    \/ StopSaves \/ StopExits \/ FinalSave \/ FinalExits
    \/ CheckOk \/ CheckFails \/ Killed

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Rules                                                                   *)

\* Saved chapters always form 1..k: no chapter is saved before the one ahead of it.
SavedInOrder == \A c \in Chapters : (c > 1 /\ Saved(c)) => Saved(c - 1)

\* Every saved chapter was read against exactly the earlier chapters the wiki
\* keeps on disk: each one, in the version saved, and nothing later.
ReadAgainstKept ==
    \A c \in Chapters : Saved(c) =>
        /\ {<<x[1], x[2]>> : x \in disk[c].saw} =
              {<<d, IF Saved(d) THEN disk[d].ver ELSE 0>> : d \in 1..(c - 1)}
        /\ \A d \in 1..(c - 1) : Saved(d)

\* Only the chapter just before can be shown unchecked, so its claimed answers
\* stay open; every older chapter was seen after its check was saved.
OnlyPreviousUnchecked ==
    \A c \in Chapters : Saved(c) =>
        \A x \in disk[c].saw : x[3] = "unchecked" => x[1] = c - 1

\* "Rerun the same command to resume" always works: no run hits the
\* read-in-order or later-chapters refusals.
Resumable == pc \notin {"errOrder", "errLater"}

\* A run with no failed call and no kill saves every chapter up to --to.
CleanRunFinishes ==
    (pc = "exit" /\ ~faulted) => \A c \in 1..end : Saved(c)

=============================================================================
