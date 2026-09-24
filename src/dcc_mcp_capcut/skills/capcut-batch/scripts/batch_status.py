"""Read a batch manifest back: per-item state, receipts and failures.

A batch is a long-running, resumable thing, so its record has to be readable
while it is running and after it is gone. This is the read side, and it is
host-free: it reads the manifest file and nothing else, never the host, never
the media.

It does not re-check the artifacts. A ``done`` item was proven when it was
delivered, and the receipt it carries is that proof; re-probing forty files from
here would either duplicate the host's work or, worse, disagree with it.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.batch import load_batch, summarize


@skill_entry
def main(manifest_path: str = None):
    if not manifest_path:
        raise ValueError("manifest_path is required: the manifest file is the batch")
    manifest = load_batch(manifest_path)
    summary = summarize(manifest)
    counts = summary["counts"]
    message = (
        f"Batch has {counts['done']} of {summary['total']} item(s) delivered; "
        f"{counts['pending']} pending, {counts['running']} running, "
        f"{counts['failed']} failed, {counts['skipped']} skipped."
    )
    return skill_success(
        message,
        manifest_path=manifest_path,
        # The full per-item record, including the rendered plan and the reframe
        # report: a failed item is diagnosed from what it was asked to do, not
        # from its index.
        **summary,
        plans=[item["plan"] for item in manifest["items"]],
        reframes=[item["reframe"] for item in manifest["items"]],
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
