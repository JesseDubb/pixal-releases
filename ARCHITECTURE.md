# Pixal architecture: current state

Last verified: 2026-09-05. Architecture/settings checkpoint: `9ff2a43` and
`885dde9`; ownership extraction checkpoint: `905dce0`, `67a9c98`, `016fd30`
and `c10f848` (catalog, Z-Image family, events/ledger, ComfyUI supervision).
Latest memory changes and live evidence are in the
[memory checkpoint](docs/2026-09-05-memory-recovery.md).
Cancellation follow-through and outstanding packaged-Windows validation are in
[release readiness](docs/2026-09-05-release-readiness.md).

This is the maintained engineering map, not a claim that the migration is complete.
Update it when ownership or contracts change. Dated reports record evidence at a
checkpoint; plans describe intended work. Neither overrides the current code and tests.

## Direction and scope

Pixal is becoming a modular monolith: one local Python/aiohttp backend, a React
interface and separate ComfyUI and local-brain processes. No framework replacement,
multi-tenant service or storage migration is part of the current extraction.
`server.py` remains the desktop entry point **and a large legacy implementation**;
it is not yet a thin launcher. Extract ownership and dependencies, not just lines.

The architecture changes through `c10f848` shipped in **1.4.0b**, public and
latest since 2026-09-05 (provenance:
[release 1.4.0b](docs/2026-09-05-release-1.4.0b.md)). Running a newer
checkout does not update the published installer; publication evidence lives in
the release readiness record above. Version/channel authority remains `PIXAL_VERSION` and
`PIXAL_CHANNEL` in [server.py](server.py); promotion follows [RELEASING.md](RELEASING.md).

## Where behavior belongs today

| Concern | Current owner / integration boundary |
| --- | --- |
| Asset, private-data and engine paths | [RuntimePaths](pixal/paths.py); the legacy adapter still selects runtime globals |
| HTTP construction and route registration | [app factory](pixal/app.py), [route table](pixal/http/routes.py); `server.create_app()` supplies legacy handlers and lifecycle hooks |
| Startup task lifetime | [TaskOwner](pixal/lifecycle.py): bridge, GPU watcher, window-exit watcher, brain reaper and optional catalog warmup; not all application tasks |
| Configuration defaults, merge rules and persistence | [rules](pixal/config/rules.py), [ConfigStore](pixal/config/store.py); legacy `load_config` / `save_config` delegate |
| Settings validation and public response | [patch rules](pixal/config/settings.py), [projection](pixal/config/presentation.py), [finisher values](pixal/config/values.py); server adapters resolve inventory and perform post-save effects |
| Extracted pure recipe/version rules | [canvas](pixal/recipes/canvas.py), [style rules](pixal/recipes/style_rules.py), [version comparison](pixal/versioning.py) |
| Scoped H3 reference writer guidance | [prompting](pixal/prompting.py): shared active-recipe direction and typed character-age context; legacy writer assembly and graph builders remain in `server.py` |
| Intent-aware image review | [creative review](pixal/creative_review.py): bounded saved-brief context and validated four-section results, shared by direct vision and ComfyUI review; routing/artifact ownership remain in `server.py` |
| Still post-processing delivery | [postprocessing](pixal/postprocessing.py): copy-on-write stages, validated atomic publication and per-image original/finish provenance; `Hub.add_image` supplies the existing finishers. [PostProcessCompare](web/src/components/PostProcessCompare.jsx) masks the two images with shared zoom/pan. |
| Memory policy | [memory](pixal/memory.py): failure classification, host physical/commit readings and safe still-canvas recovery; `Hub` owns serialized admission, engine reclamation and workload pricing |
| Model roots, recursive inventory, metadata and input catalog | [Catalog](pixal/catalog/store.py): revisioned read-only snapshots, explicit invalidation, shared scan for warmup and TTL reads; server adapters retain call-time patched names and legacy dictionary aliases. Options roots memo is synchronous build-scoped, never a TTL. |
| Z-Image family graph assembly | [zimage](pixal/recipes/families/zimage.py): explicit canvas/model/LoRA stack/sampler seat/overrides/capability facts in, graph/caption/info out; server resolves legacy dependencies and keeps build_zimage/build_fantasy/build_anime signatures. 48 checkpoint fixtures pin both sampler graphs. |
| Event publishing and replay | [EventPublisher](pixal/jobs/events.py): per-app subscribers, sequence/ring, fan-out, poll activity and stream shutdown; Hub delegates and retains lane persistence between record and fan-out. |
| JSONL ledger | [Ledger](pixal/storage/ledger.py): per-owner mtime/size cache, own-append tail parsing and delete rewrite; Hub keeps call-compatible adapters. Each server app gets an independent cache even for the same file. |
| ComfyUI process supervision | [ComfySupervisor](pixal/backends/comfy/supervisor.py): one boot/desired/observed owner; injected ProcessRunner for spawn, poll, listener lookup and tree termination. Server supplies current callbacks and preserves COMFY_BOOT plus public function names. Boot-meter projection and HTTP/network reachability remain adapters. |
| Other recipe builders, jobs, chat and brain supervision | Still predominantly in [server.py](server.py), including shared `Hub`; graph templates also live in [templates/](templates/) |
| Frontend and generated assets | [web/src/](web/src/); [build_web.mjs](tools/build_web.mjs) owns production bundling/cache stamps, invoked by `npm run build` and `web/build.bat` |

## Contracts to preserve

- New `pixal/` modules must not import `server` or perform application I/O at
  import time. Inject narrow dependencies; do not introduce a universal runtime
  object to hide shared state. [Boundary tests](tests/test_import_boundaries.py).
- A settings patch validates a detached working configuration. A successful
  atomic save must precede engine retargeting, bridge closure or brain effects.
  Invalid patches return 400, unreadable configuration 409, write failures 500.
  [HTTP tests](tests/test_config_http.py).
- Config reads retain legacy merge behavior. Saves preserve unknown top-level and
  section extension fields. An unreadable original is not silently overwritten;
  backup is best-effort. Locks are single-process, not cross-process coordination
  or a guarantee against power-loss directory-entry loss. [Store tests](tests/test_config_store.py).
- The public Settings response is a projection, not raw config serialization.
  LLM credentials/private fields remain excluded; the existing key tail remains.
  [Response tests](tests/test_settings_response.py).
- Unrelated settings saves keep the catalog cache valid. Changed model roots or
  engine target invalidate it; TTL and explicit Rescan still apply. Resolved
  validation inventory is request-local, not a new persistent cache.
- Preserve route/schema, recipe graph and user-data compatibility during extraction.
  The approved UI, render algorithms and JSON/JSONL storage authority are unchanged.
- Memory preparation and enqueue are serialized; waiting jobs are cancellable and
  never justify flushing another active render. Reclamation uses current readings,
  not a historical maximum. Unknown readings do not mean an empty memory budget.
- OOM recovery gets at most one retry. Supported stills reduce the actual canvas
  (or batch), including final overrides; fixed PiD presets are not generically
  resized. Saved preferences remain unchanged. CPU/commit failures are distinct
  from CUDA failures. [Failure-case tests](tests/test_memory_recovery.py).
- Stop cancels pending OOM recovery and its retry child, including late prompt
  acknowledgements. Cancellation is marked before engine I/O; the global engine
  interrupt is used only when the observed running prompt belongs to that job.
  [Cancellation tests](tests/test_oom_cancellation.py).
- Activation calibration examines at most 256 recent ledger rows, matching known
  canvas buckets, model, batch and video frame count. These remain conservative
  heuristics, not measured per-operator allocation guarantees.

## Limits and next work

The generic app factory and config store are constructible independently, but
two `server.create_app()` instances still share jobs, chat, catalog and engine/brain
state. Event publishers and ledger caches are independent per app. Narrow
service scopes bind those two owners to requests and lifecycle-created tasks;
async tasks and `asyncio.to_thread` inherit them. Calls outside an app scope use
Hub's own compatibility owners, and patched server.LEDGER remains call-time
resolved there. These scopes do not make the rest of Hub multi-instance safe. Importing `server`
still initializes `Hub` and can touch its selected data directory. Do not import
it casually to inspect the code; use source/AST inspection or an isolated harness.
Temporary test roots are isolation measures, not an OS/network sandbox.

Catalog ownership has moved; its legacy server dictionary aliases remain writable
for compatibility with test patches. New consumers use read-only snapshots.
Z-Image assembly and event/ledger ownership have moved. Remaining `Hub` state, brain supervision,
remaining background work, frontend decomposition and distribution hardening
remain later stages. ComfyUI supervision is still a single desktop owner, not
per-app engine isolation; its writable COMFY_BOOT alias is retained for patches.
Desired/observed state records supervision intent and evidence without changing
the boot payload or adding process probes. Database authority changes and release promotion are
separate decisions, not implied by an approved refactor.

Removing redundant work can improve responsiveness; moving code alone does not
make GPU sampling faster. Record the workload, before/after measurement and
limitations for every performance claim.

## Extracting the next recipe family

1. Map builder dependencies and server patch points before moving code. Capture
   fixed synthetic graph/caption/info results from the old checkpoint, with
   models and capabilities faked and data roots temporary. Pin sorted JSON bytes;
   never regenerate the fixture to accommodate extraction failures.
2. Leave a signature-compatible server adapter that resolves catalog, caption,
   canvas, LoRA plan and sampler choices through current server bindings. Pass
   explicit resolved inputs to a pure family assembler. The Z-Image adapter
   supplies three shared pure graph helpers at call time so existing patches
   remain observable; it supplies no module namespace or universal runtime.
3. Move graph construction, node wiring, family caption prefixes and final graph
   readback into the family owner. Preserve IDs, template values, overrides,
   defaults and info fields. Test direct assembly for repeatability/no I/O and
   test server patch effects alongside byte parity.
4. Run the full gate and unchanged import boundaries, record any source-reading
   test relocation with its behavioral proof, update this map, then commit.

## Verification and evidence

Use the checkout's interpreter; on this Windows development tree:

```powershell
.venv\Scripts\python.exe tools/verify.py
.venv\Scripts\python.exe tools/audit_architecture.py --summary
```

The verification command checks generated web assets, runs pytest scoped to
`tests/` and discovers JavaScript suites. It does not run live smoke tests or
publish anything. Use `--build` only when intentionally regenerating web assets.
Check generated changes before committing; never regenerate frozen compatibility
fixtures merely to make a failing test pass.

The following dated reports are tracked in the development checkout but excluded
from release packages. They may be absent in an installed copy:

- [Approved plan](docs/2026-09-04-pixal-architecture-plan.md): destination and staged gates, not implemented status.
- [Foundation checkpoint](docs/2026-09-04-architecture-implementation.md): paths, HTTP/task ownership, persistence and limitations.
- [Live studio baseline](docs/2026-09-04-architecture-studio-smoke.md): real render/replay/restart evidence, not comprehensive failure coverage.
- [Settings checkpoint](docs/2026-09-04-settings-boundary.md): latest application test totals, scoped benchmarks and live preference parity.
- [Installer hardening](docs/2026-09-04-installer-hardening-implementation.md): bootstrap/runtime ownership, repair and download recovery, verification and the remaining packaged-Windows release gate.
- [Performance pass](docs/2026-09-05-performance-pass.md): measured hot paths, what moved off the event loop and what each change is worth; its limitations are current.
- [Release 1.4.0b](docs/2026-09-05-release-1.4.0b.md): promotion, the three-surface hash check and the still-outstanding clean-Windows rehearsal.

Ordinary tests consume committed synthetic fixtures. Historical capture/benchmark
tools can require private baseline Git commits; they are not runtime dependencies.
Live rendering/restarts require an explicitly approved window, idle checks and
process-identity checks; the verification command is not permission to run them.

Product behavior belongs in [README.md](README.md) / [HELP.md](HELP.md), terminal
operation in [CLAUDE.md](CLAUDE.md), visual rules in `DESIGN.md`, and packaging in
[PACKAGING.md](PACKAGING.md). Local `pixal-dm-ssot.md` and other ignored working
notes retain historical context; they are not the current architecture authority.
