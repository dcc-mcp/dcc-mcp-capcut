"""Render one template against N variable sets, one verified item at a time.

A batch is a loop over items, and every item is the same three steps the single
tools already perform: assemble the plan, submit the export, read the job to a
terminal state. What this tool adds is everything the single tools leave to the
caller:

* **Failure isolation.** One item's failure is recorded on that item and the
  batch continues. A bridge timeout, a missing asset, a reframe that cannot be
  delivered -- none of them costs the items already rendered, or the ones after.
* **Resumability.** The manifest at ``manifest_path`` is rewritten after every
  item, atomically. Re-running with ``resume=true`` keeps every ``done`` item and
  retries only what is not finished, so a batch interrupted at item 31 of 40
  does not start over.
* **One receipt per item.** Each delivered item carries the host's artifact
  receipt, requested through the same ``verify_output`` flag a single export
  uses, so a batch is accepted one artifact at a time rather than on trust.

Two constraints are worth stating plainly because they are properties of the
host, not of this tool. Rendering is **sequential**: CapCut exposes one bound
foreground window, so this call takes roughly N times one render. And a batch
needs that **visible, bound window for its whole run** -- there is no
unattended path in this adapter today, and this tool does not pretend otherwise.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Optional

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.assemble import assemble, dispatch, resolve_subtitle_alignment
from dcc_mcp_capcut.batch import (
    SUCCESS_EXPORT_STATE,
    TERMINAL_EXPORT_STATES,
    begin_item,
    build_batch,
    complete_item,
    fail_item,
    fresh_overwrite_check,
    load_batch,
    save_batch,
    select_items,
    skip_item,
    summarize,
)
from dcc_mcp_capcut.editplan import plan_to_actions
from dcc_mcp_capcut.export_receipt import (
    RECEIPT_KEY,
    VERIFY_OUTPUT_PARAM,
    validate_export_receipt,
)

# Injected rather than called directly so a batch of forty items can be driven
# to completion in a test without spending forty render times asleep.
_SLEEP: Callable[[float], None] = time.sleep
_CLOCK: Callable[[], float] = time.monotonic

DEFAULT_POLL_INTERVAL_SECS = 5.0
DEFAULT_ITEM_TIMEOUT_SECS = 600.0


class HostStillRunning(RuntimeError):
    """The host is still rendering this item, so the batch cannot go on.

    Distinct from a failed render on purpose: a render that failed is over and
    the next item can start, but a render that merely overran its wait budget is
    still occupying the one bound CapCut window. Starting the next item would
    dispatch into a host that is mid-render.
    """


def _await_export(
    job_id: str,
    *,
    timeout_secs: float,
    poll_interval_secs: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, Any]:
    """Poll ``get_export_status`` until the job reaches a terminal state.

    Unflagged on every poll: the flag asks for an artifact receipt, and before
    the job is terminal there is no artifact, so asking early turns the first
    poll into a failure and hides the progress the poll exists to report. The
    receipt is asked for once, after the terminal state is known.
    """
    deadline = clock() + timeout_secs
    while True:
        status = dispatch("get_export_status", {"job_id": job_id})
        state = status.get("state")
        if state in TERMINAL_EXPORT_STATES:
            return status
        if state is None:
            raise RuntimeError(
                f"get_export_status returned no 'state' for job {job_id!r}; the job "
                "cannot be read to completion"
            )
        if clock() >= deadline:
            # A timeout is not a finished job: the host is still rendering it.
            # What distinguishes it from a failed render is that the next item
            # cannot start -- there is one bound window and this job holds it.
            raise HostStillRunning(
                f"export job {job_id!r} did not reach a terminal state within "
                f"{timeout_secs:g}s (last state {state!r}). The job is still running "
                "host-side: read it with get_export_status, or cancel_export it, "
                "before resuming this batch."
            )
        sleep(poll_interval_secs)


def _read_receipt(
    job_id: str, *, output_path: str, verify_output: bool
) -> Optional[dict[str, Any]]:
    """Ask once for the artifact receipt, and require a real one.

    Batch delivery is exactly the case the export receipt exists for: forty
    renders whose only proof is "the host said done" is forty chances to ship a
    missing, empty or wrongly sized file. So the receipt is requested, and an
    absent one fails the item rather than warning about it.

    The receipt is also **bound to this item's destination**: without that, a
    host could hand back the previous item's probe and every field check would
    still pass. The field rules are not re-implemented here -- ``export_receipt``
    owns them, and validating through it is what makes one batch item's proof
    the same proof a single export gives.
    """
    if not verify_output:
        return None
    params = {"job_id": job_id, VERIFY_OUTPUT_PARAM: True}
    final = dispatch("get_export_status", params)
    receipt = (final.get("verification") or {}).get(RECEIPT_KEY)
    if receipt is None:
        raise RuntimeError(
            f"export job {job_id!r} reached a terminal state but returned no artifact "
            f"receipt under verification.{RECEIPT_KEY}, so the render cannot be proven. "
            "Check the file at output_path yourself, or run the batch with "
            "verify_output=false to accept the host's word."
        )
    return validate_export_receipt("export_video", receipt, expected_path=output_path)


def _settle_orphaned_jobs(
    manifest: dict[str, Any],
    indices: list[int],
    *,
    verify_output: bool,
) -> list[int]:
    """Find out what the last job of each failed item did before re-rendering.

    An item that failed after its export was submitted -- a timeout, most
    likely -- left a job behind. Re-exporting it would put two renders into one
    destination through one bound window, which is exactly what stopping the
    batch on a timeout is meant to prevent. So a failed item carrying a
    ``job_id`` is asked about first:

    * ``done`` — it finished after all; settle it from that job.
    * any other terminal state — the job is over, so a re-export is safe.
    * still running — the batch cannot continue, and says which job holds it.
    """
    remaining: list[int] = []
    for index in indices:
        item = manifest["items"][index]
        job_id = item.get("job_id")
        if item["state"] != "failed" or not job_id:
            remaining.append(index)
            continue
        status = dispatch("get_export_status", {"job_id": job_id})
        state = status.get("state")
        if state == SUCCESS_EXPORT_STATE:
            receipt = _read_receipt(
                job_id, output_path=item["output_path"], verify_output=verify_output
            )
            complete_item(
                manifest,
                index,
                timeline_id=item.get("timeline_id"),
                job_id=job_id,
                receipt=receipt,
            )
            continue
        if state in TERMINAL_EXPORT_STATES:
            # The job ended without a deliverable, so the destination is free.
            remaining.append(index)
            continue
        raise HostStillRunning(
            f"item {index} still has export job {job_id!r} in state {state!r}; the host "
            f"is rendering it and the batch cannot start another export to "
            f"{item['output_path']!r}. Read it with get_export_status, or "
            "cancel_export it, before resuming."
        )
    return remaining


def _run_item(
    manifest: dict[str, Any],
    index: int,
    *,
    media_dir: str,
    strategy: str,
    verify_output: bool,
    poll_interval_secs: float,
    item_timeout_secs: float,
) -> None:
    """Assemble, export and settle one item, recording whatever happens."""
    # Read the build verdict before the item is marked running: begin_item
    # clears ``error`` so a retry starts from a clean slate, and that clear
    # would otherwise erase the only record of why the item never compiled.
    build_error = manifest["items"][index].get("error")
    item = begin_item(manifest, index)
    try:
        plan = item["plan"]
        if plan is None:
            # A build failure is not dispatchable, and retrying it can only
            # fail the same way. Keep the compile reason rather than replacing
            # it with a dispatch error.
            raise RuntimeError(build_error or "this item did not compile")

        # Dispatch a copy. Stripping the adapter-side subtitle directives is
        # part of lowering, not a change to the plan, and the manifest is saved
        # after every item -- mutating the stored plan would mean a retry after
        # a late failure silently drops the requested alignment and imports the
        # un-timed file instead.
        plan = copy.deepcopy(plan)
        script = plan_to_actions(plan, media_dir=media_dir)
        # Same ordering as the single-shot path: alignment is resolved before
        # the strategy is chosen so the host batch action never receives an
        # adapter directive it would silently ignore.
        script = resolve_subtitle_alignment(script)
        for subtitle in plan.get("subtitles", []):
            subtitle.pop("align", None)
            subtitle.pop("output_path", None)

        assembly = assemble(plan, script, media_dir, strategy=strategy)
        timeline_id = assembly.get("timeline_id")
        # Recorded before the export is submitted: an item that fails later is
        # written to the manifest with the handles a resume needs to find out
        # what its last job actually did, instead of re-rendering blind.
        if timeline_id is not None:
            item["timeline_id"] = timeline_id

        params = dict(item["export"] or {})
        params.update({"timeline_id": timeline_id, "output_path": item["output_path"]})
        submit = dispatch("export_video", params)
        job_id = submit.get("job_id")
        if not job_id:
            # Documented degradation for a single export, fatal for a batch:
            # with no handle there is nothing to poll, so the item can never be
            # proven and the operator gets a silent unknown.
            raise RuntimeError(
                "export_video acknowledged the job without a job_id, so this item "
                f"cannot be read to completion (destination {item['output_path']!r}). "
                "Check the host integration; the adapter never synthesises a job_id."
            )
        # Persisted with the failure too, not only with a success: this is the
        # one fact that lets a resume settle the job it already paid for
        # instead of submitting a second export to the same destination.
        item["job_id"] = job_id

        status = _await_export(
            job_id,
            timeout_secs=item_timeout_secs,
            poll_interval_secs=poll_interval_secs,
            sleep=_SLEEP,
            clock=_CLOCK,
        )
        state = status.get("state")
        if state != SUCCESS_EXPORT_STATE:
            raise RuntimeError(
                f"export job {job_id!r} finished in state {state!r} instead of "
                f"{SUCCESS_EXPORT_STATE!r}"
            )
        receipt = _read_receipt(
            job_id, output_path=item["output_path"], verify_output=verify_output
        )
        complete_item(manifest, index, timeline_id=timeline_id, job_id=job_id, receipt=receipt)
    except (RuntimeError, OSError, ValueError) as error:
        fail_item(manifest, index, error)
        if isinstance(error, HostStillRunning):
            # Recorded first, then propagated: the manifest has to carry the
            # job that is still out there, and the caller has to be able to
            # tell "this batch stopped" from "this batch finished".
            raise


@skill_entry
def main(
    template: dict = None,
    variables: list = None,
    media_dir: str = None,
    manifest_path: str = None,
    resume: bool = False,
    retry_failed: bool = False,
    continue_on_error: bool = True,
    verify_output: bool = True,
    dry_run: bool = False,
    fps: float = 30.0,
    media_index: dict = None,
    strategy: str = "auto",
    poll_interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
    item_timeout_secs: float = DEFAULT_ITEM_TIMEOUT_SECS,
):
    if item_timeout_secs <= 0:
        raise ValueError("item_timeout_secs must be > 0")
    if poll_interval_secs < 0 or poll_interval_secs > item_timeout_secs:
        raise ValueError("poll_interval_secs must be >= 0 and <= item_timeout_secs")

    if resume:
        if not manifest_path:
            raise ValueError("resume=true requires manifest_path: that file is the batch")
        manifest = load_batch(manifest_path)
        # A resumed batch keeps the media root it started with, so items that
        # already rendered and items rendered now cannot resolve media from
        # two different delivery directories.
        media_dir = media_dir or (manifest.get("options") or {}).get("media_dir")
    else:
        if template is None:
            raise ValueError(
                "template is required: a canonical plan or vlog recipe carrying "
                "{{placeholder}} fields"
            )
        if variables is None:
            raise ValueError("variables is required: a nonempty list of variable objects")
        manifest = build_batch(
            template,
            variables,
            fps=fps,
            media_index=media_index,
            media_dir=media_dir,
            require_output=True,
        )

    summary = summarize(manifest)
    if dry_run:
        # A dry run promises to touch nothing, and that includes the manifest:
        # writing it would make the next resume believe renders happened.
        return skill_success(
            f"Compiled {summary['total']} batch item(s); no host action was dispatched.",
            manifest_path=None,
            dispatched=False,
            **summary,
        )

    if media_dir is None:
        raise ValueError(
            "media_dir is required unless dry_run is true: the plan stores portable "
            "relative media paths and they must resolve to real files before dispatch"
        )

    if manifest_path and not resume:
        fresh_overwrite_check(manifest_path)

    indices = select_items(manifest, retry_failed=retry_failed or resume)
    # Asked before anything is dispatched: a job left running by an earlier
    # interrupted run would otherwise be joined by a second export to the same
    # destination. Nothing has been touched yet, so there is no state to save
    # if this refuses to continue.
    indices = _settle_orphaned_jobs(manifest, indices, verify_output=verify_output)
    if manifest_path:
        # Written once before the first item so batch_status can see the batch
        # while item 0 is still rendering, rather than only after it lands.
        save_batch(manifest_path, manifest)
    stopped: Optional[str] = None
    for position, index in enumerate(indices):
        try:
            _run_item(
                manifest,
                index,
                media_dir=media_dir,
                strategy=strategy,
                verify_output=verify_output,
                poll_interval_secs=poll_interval_secs,
                item_timeout_secs=item_timeout_secs,
            )
        except HostStillRunning as error:
            # The item is recorded as failed before this propagates, so the
            # manifest keeps the job that is still running host-side.
            stopped = str(error)
        if manifest_path:
            save_batch(manifest_path, manifest)
        if stopped is not None:
            for skipped in indices[position + 1 :]:
                skip_item(
                    manifest,
                    skipped,
                    f"batch stopped while item {index} was still rendering: the host "
                    "is busy and the batch cannot continue",
                )
            if manifest_path:
                save_batch(manifest_path, manifest)
            break
        if not continue_on_error and manifest["items"][index]["state"] == "failed":
            for skipped in indices[position + 1 :]:
                skip_item(
                    manifest,
                    skipped,
                    f"batch stopped after item {index} failed; continue_on_error is false",
                )
            if manifest_path:
                save_batch(manifest_path, manifest)
            break

    summary = summarize(manifest)
    if stopped is not None:
        # The batch is neither complete nor resumable until an operator deals
        # with the job still running host-side, so say so once, plainly.
        summary["stopped"] = stopped
    counts = summary["counts"]
    message = (
        f"Batch delivered {counts['done']} of {summary['total']} item(s); "
        f"{counts['failed']} failed, {counts['skipped']} skipped."
    )
    return skill_success(
        message,
        manifest_path=manifest_path,
        dispatched=True,
        **summary,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
