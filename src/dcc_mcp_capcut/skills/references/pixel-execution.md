# Pixel execution (`cua`)

Read this before using the `dcc-cua` execution route. It defines what the route
is for, what it can prove, and the three things it will refuse to do.

## What this route is

The CapCut UI is a single opaque QML canvas: the window inventory reports one
node with no children, and `dcc-cua` treats the missing accessibility provider
as **permanent** for the window class. Semantic automation is therefore not
merely hard, it is closed. What remains is the loop this route implements:

```text
typed action -> exact PID/HWND binding -> pixel snapshot -> coordinate input -> verify
```

Tool code keeps emitting typed actions, one per call, exactly as it does for the
host bridge. `dcc_mcp_capcut.cua` is the whole translation layer.

**This route is last, not first.** The loopback bridge and the bundled panel stay
the typed, auditable path for everything the panel can reach. Use pixel
execution only for what the panel cannot reach.

## Addressing is by pixel, and pixels are build-specific

Element addressing is unavailable forever on this window class, so the adapter
rejects `element_index` / `element_token` outright rather than emitting an action
that cannot resolve.

A coordinate is a fact about one captured frame: a function of the build, the
display scale and the window size. Consequences:

- Every coordinate action must be built against the `observation_width` /
  `observation_height` of the frame its coordinates were measured in. The adapter
  refuses coordinates outside that frame.
- The version guard refuses to run against a build the matrix does not list,
  because nobody measured coordinates on it. Pass `allow_unverified=True` to
  proceed knowingly — an acknowledgement, not a default.
- A new build, resolution or UI language means re-measuring. This is recurring
  maintenance, not a one-off cost.

## What `verify` can and cannot prove

`dcc-cua verify` evaluates bounded predicates and returns each as `satisfied`,
`unsatisfied` or `unknown`.

**`unknown` is not success.** The adapter fails closed on it. On a target with no
accessibility tree most element predicates come back `unknown`, so treating
unknown as a pass would record confident successes for state that was never
observed.

**A changed pixel is not a verified edit.** The receipt reports `pixel_changed`
alongside the verdict, never folded into it. A digest difference proves the
window *changed*; it does not prove the *intended* change happened, because a
dialog appearing and the requested edit landing look identical from a digest.

Verifiable expectations are `window_exists`, `window_bounds` (with
`tolerance_px`) and `element_exists`. Asserting absence is rejected: the driver
cannot prove absence either, so such a predicate would only produce a false
unknown.

## Delivery: background first, escalation is the driver's call

Input is delivered `background` first, always. Background never swaps the
foreground, so it does not steal the operator's focus. Only the driver knows when
background delivery is impossible for a given target, so the adapter escalates to
`foreground` **only** on the driver's `background_unavailable` answer — never
pre-emptively because a target "looks like" a toolkit that might need it.

## Boundaries

**Not headless.** Unattended here means unattended on an *interactive* Windows or
macOS desktop. A locked workstation has no desktop to drive, and Linux CI is not
in scope at all — ByteDance publishes no Linux client, so the route refuses up
front rather than failing at a driver timeout.

**Red lines, unchanged from the spike:**

- No injection into the host process. Input is delivered externally only.
- No redistribution of official CapCut files; CapCut is a closed-source runtime
  dependency.
- No automatic upload, and no publishing of drafts.
- No decryption of 剪映 6.0+ draft files.
- No draft path. Drafts carry no renderer and 6.0+ drafts are encrypted, so the
  draft route stays NO-GO and is not a foundation for batch work.

## Install trees are not stable

CapCut upgrades itself in place. Measured live, a `9.5.0.4050` launch deleted the
`9.4.0.4015` install directory it replaced. Snapshot the install tree before
launch and diff it afterwards:

```python
from dcc_mcp_capcut.cua.guards import InstallTreeGuard

guard = InstallTreeGuard.capture()
# ... launch ...
diff = guard.recheck()
if diff.host_replaced:
    ...  # the binding names a process that may no longer exist; rebind
```

A `host_replaced` diff means a binding taken before the event must be
re-established, because a recycled PID can name a different window.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `interactive_desktop_unavailable` | No interactive desktop session — locked workstation or CI runner. | Use a logged-in interactive Windows/macOS session. Linux CI is out of scope. |
| `refusing to run pixel execution on an unpinned build` | The build is not in the version matrix, so coordinates are unvalidated for it. | Record the build in `hosts/versions.py`, or pass `allow_unverified=True` knowingly. |
| `background_unavailable` (escalated, then failed) | Neither delivery route could land the input. | Confirm the window is visible and restored, then re-run. |
| `unknown: <predicate>` | The predicate could not be evaluated — usually an element predicate on the opaque canvas. | Assert on window state, or verify by another perception layer. Unknown is not a pass. |
| `outside the captured frame` | Coordinates were measured against a different frame or window size. | Re-snapshot and re-measure against the current coordinate space. |
| `no visible CapCut main window was found` | Nothing bound, or more than one CapCut window is visible. | Leave exactly one visible, restored CapCut main window. |

## See also

- `host-boundary.md` — the panel, bridge and exact-window binding contract.
- `host-platforms.md` — the per-platform support matrix and version grading.
- `troubleshooting.md` — symptom to cause to remediation.
