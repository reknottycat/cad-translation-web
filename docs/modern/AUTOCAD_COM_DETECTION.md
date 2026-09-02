# AutoCAD COM Auto-Detection & Diagnostics

AutoCAD is converted through its **COM automation interface**. Because AutoCAD COM
is a **Windows-only, host-local capability**, the backend only auto-detects and
uses AutoCAD that is installed and registered **on the same Windows host that runs
the backend** — never on a browser client and never remotely.

## Detection model (no false positives)

`backend/app/functions/dwg_converter.py` decides whether an AutoCAD COM backend is
plausibly usable *before* a conversion starts. Detection combines:

1. **Registry discovery** — enumerates the versioned COM ProgIDs
   (`AutoCAD.Application.<major>[.<minor>]`) registered on the host, across both
   the 32-bit and 64-bit registry views where reachable. This means a future
   AutoCAD release (e.g. 2023+ / `.25`, `.26`, …) is recognised **without editing
   code**, instead of a hard-coded list that stops at 2022.
2. **Process table** — checks whether an `acad.exe` process is already running.
3. **Bridge script presence** — the Python COM bridge
   (`backend/app/services/autocad_converter.py`) must exist on disk.

A COM backend is only reported **detected** when the bridge script is present
**and** the application is either registered or running. **A lone Python script
never implies AutoCAD is installed.**

The detailed probe lives in `backend/app/functions/autocad_discovery.py` and is
unit-tested by mocking `winreg`, the process list, and `win32com` — no real
AutoCAD is needed to run those tests.

### Diagnostic reasons

Probing returns one of these reasons (plus a human `actionable` message):

| Reason | Meaning |
|--------|---------|
| `script_missing` | The Python COM bridge script is absent (broken/partial install). |
| `process_running` | An `acad.exe` process is running; conversion may proceed. |
| `registered` | AutoCAD is installed and registered; conversion may proceed. |
| `activatable` | Registered **and** a live COM activation succeeded. |
| `activation_timeout` | Registered but COM activation did not return within the bounded timeout — the COM server may be hung, blocked by a modal dialog, or hit a licensing/bitness issue. |
| `activation_failed` | Registered but COM activation failed — bitness, permissions, or a damaged registration. |
| `not_detected` | No registration and no running process — not installed on this host. |

The connection layer (`backend/app/services/autocad_converter.py`) runs inside a
subprocess under a timeout, tries the discovered versioned ProgIDs newest-first,
and records a precise diagnostic in `converter.last_error` instead of silently
swallowing why the connection failed. If the application is registered but cannot
be activated it says so (`activation_failed`); if nothing is registered it says
`not_detected` and points the user at installing/registering AutoCAD or choosing
another backend.

## Backend fallback order

Auto mode keeps the configured fallback chain (`haochen_com` → `autocad_com` →
`oda`/LibreDWG by default) but **sieves out** COM backends that probing shows to be
certainly unusable on the host (script missing, or nothing registered and no
process running). ODA/LibreDWG binary backends are kept only when their binary is
found. If every candidate is filtered out, the original chain is preserved so the
conversion reports a descriptive, per-backend error instead of an empty result.

COM conversions remain serialized (default `CAD_COM_CONCURRENCY=1`) to avoid races
on the shared AutoCAD COM instance, and never leak a process or document on a
connection failure or timeout.

## Deployment boundary & prerequisites

- AutoCAD installation and COM availability belong to the **backend Windows host**
  that actually runs the conversion, **not** to any browser client.
- The system remains **single-tenant**: it provides **no per-user task isolation**
  between people sharing one instance. "Auto-detection" only means the backend can
  find AutoCAD registered on its own host.
- "Auto-detect" requires all of these on the backend host:
  - Windows (COM / registry)
  - AutoCAD installed and its COM ProgID registered
  - `pywin32` (Windows) installed in the Python runtime
  - the process account has permission to launch/attach to AutoCAD via COM
- The system **never auto-installs AutoCAD**. If AutoCAD is absent, choose another
  configured backend (ODA File Converter, LibreDWG) or install/register AutoCAD.

## Registered ≠ confirmed activatable: bounded activation probing

A COM ProgID that is merely present in the registry is **not proof** that
`Dispatch` will return. On a real host a registered-but-broken ProgID can block
a COM activation for tens of seconds or forever -- e.g. a bitness mismatch, a
damaged installation, a licensing/modal dialog, or a hung single instance. This
is especially visible with 浩辰 (GStarCAD) / 中望 (ZWCAD), whose ProgIDs may be
registered but whose COM server never answers.

To keep both the **probe** and the **conversion** phases from stalling and to
respect COM apartment ownership:

1. **Probe** (`backend/app/functions/com_activation_probe.py`) runs each
   `GetActiveObject` / `Dispatch` on a **daemon worker thread with a hard
   per-attempt timeout** (single knob `CAD_COM_ACTIVATION_TIMEOUT`, default 30s;
   a real AutoCAD 2026 cold start measures ~6.5s so the default leaves margin).
   The probe is *classification only*: the worker thread initialises its own COM
   apartment, activates the ProgID, reads `Version`/`Documents` to confirm the
   object is usable, **closes it on the same thread**, and uninitialises. Only a
   classification string is returned -- a COM object is **never handed to
   another thread**. On timeout the result is marked `cleanup_required` so a
   still-running CAD process can be reclaimed (`taskkill`) instead of leaking.
2. Both COM connection layers (`autocad_converter.py` and
   `haochen_optimized_converter.py`) activate **synchronously on the current COM
   thread**. They run inside a dedicated subprocess (`com_converter_cli.py`)
   whose main thread owns the apartment and is `CoInitialize`d up front; the
   parent `subprocess.run(timeout=...)` in `dwg_converter` is the process-level
   bound/reclamation. Activation, opening the document, converting and release
   therefore all happen in the **same COM thread/process** -- no worker thread
   `CoUninitialize`s and hands a dead proxy back to the caller.
3. `dwg_converter.inspect_backends()` runs a **bounded live-activation probe**
   when a COM backend is registered but no CAD process is running, and reports
   `activatable` / `activation_timeout` / `activation_failed` instead of
   optimistically reporting plain `registered`. `_select_auto_backends()` drops a
   backend whose bounded activation timed out or failed, so the auto chain does
   not waste a long time on a registered-but-hung 浩辰/中望 backend.

A hung COM server that **never answers `Dispatch`** (the 浩辰/中望 case above)
can still have already started a CAD process (e.g. `gcad.exe`) before it stalls;
the probe's daemon worker cannot close it because it is still blocked inside
`Dispatch`. `dwg_converter._probe_com_activation()` therefore records the
backend's running CAD PIDs **before** probing and, when a per-ProgID outcome
reports `cleanup_required`, reclaims only the PIDs that **newly appeared with a
matching image** -- never a user's already-open CAD. This keeps `inspect` /
auto-sieving from leaving an orphan `gcad.exe`/`acad.exe` behind.

ProgID candidates returned by the discovery helper are de-duplicated
**case-insensitively**, so an entry registered under `HKCR` in mixed case and
another from the lower-case baseline never both appear.

## Probe-then-connect stale-proxy race

A conversion pipeline can first **probe** (activate + immediately `Quit`) a CAD
instance during detection, then a moment later **connect** to run the actual
conversion. Because a CAD application's `Quit()` is asynchronous, the freshly
`Dispatch`-ed process does not deregister from the Running Object Table (ROT)
the instant `Quit()` returns. If the connection's `GetActiveObject` runs inside
that short window it receives a **stale active proxy** pointing at the
half-shut-down CAD -- and, being a live `GetActiveObject` hit, it is not `None`
yet fails `Version`/`Documents` on use (surfacing as `AttributeError`/COM error
mid-conversion). In a fresh process that never probed, `GetActiveObject` finds
nothing so the connection falls through to `Dispatch` and starts a clean
instance -- which is why the failure only appears after a probe.

The fix is three-fold:

1. **The probe confirms the launched instance left the ROT** after `Quit`
   (`com_activation_probe`): after closing the `Dispatch`-ed instance it polls
   `GetActiveObject` for a bounded window (`DEFAULT_QUIT_CONFIRM_TIMEOUT`, cap
   ~8s) until the object is deregistered, so an immediately following connection
   does not see a stale ROT entry. It returns a `quit_confirmed` flag; if the CAD
   still never drains it stops at the cap and relies on (2) rather than blocking.
2. **The connection layer validates `Version`/`Documents`** on the instance it
   acquires (`com_instance_guard.instance_is_usable`). A stale proxy that cannot
   serve these members is **not** accepted as a successful connection.
3. **A stale `GetActiveObject` proxy is discarded and a fresh `Dispatch` is
   issued** automatically (`com_instance_guard.acquire_usable_instance`, used by
   both `autocad_converter.py` and `haochen_optimized_converter.py`). A genuinely
   live already-running CAD (owned by the user) is still attached and left
   running; only an unusable proxy triggers the re-`Dispatch`.

This keeps detection and conversion free of `acad.exe` / ROT residue and makes
the connection resilient to the residual stale-proxy window.

On `disconnect()`, both connection layers quit only an instance they
**started** via `Dispatch` (tracked by `_dispatch_started`); an instance they
merely attached to via `GetActiveObject` (owned by the user) is left running and
only its visibility is restored. This prevents a connection that auto
re-`Dispatch`ed (after discarding a stale proxy) from leaving an extra
`acad.exe` / ROT entry behind.

## GBK-safe machine output

The COM service layers (`backend/app/services/autocad_converter.py` and
`backend/app/services/haochen_optimized_converter.py`) print readable progress and
diagnostic markers to stdout while running inside the dedicated COM subprocess. On
a Chinese Windows host the console code page is typically **GBK (cp936)** and
`PYTHONIOENCODING` is unset, so CPython writes through a **strict GBK stream** that
raises `UnicodeEncodeError` on characters GBK cannot encode.

To keep "detection succeeded" from becoming a non-zero failure purely because of
console encoding, machine-facing markers use **ASCII-stable tokens** — `[OK]` for
success and `[ERROR]` for failure — instead of Unicode symbols such as `✓` (U+2713)
/ `✗` (U+2717). The readable Chinese diagnostic text is GBK-encodable and is
retained. This convention is enforced by
`tests/backend/test_gbk_stdout_ascii_markers.py`, which asserts both service
modules contain **no** character that strict GBK cannot encode and that the real
connect success / failure output paths round-trip through strict GBK without
`UnicodeEncodeError`.
