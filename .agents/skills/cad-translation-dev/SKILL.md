---
name: cad-translation-dev
description: CAD Translation System development, testing, security audit, and local release guidance. Use for changes to the FastAPI backend, React frontend, maintained cad-translate CLI, CAD converter backends, translation workflow, concurrency behavior, packaging, or project documentation.
---

# CAD Translation System — Development Skill

## Project at a glance

The repository has three runtime surfaces:

- **Web**: React 18/Vite frontend plus the FastAPI backend.
- **CLI**: the maintained cad-translate package in agent-harness/cad_translate/. It delegates to the trusted backend implementation; the command is not cli-anything-cad.
- **Legacy desktop/command-line code**: trans_CAD_gui_V1.0/ and 命令行专用/ are compatibility code. Change them only when the task explicitly targets the legacy surface.

Maintained source is under backend/, frontend/, and agent-harness/ (including
the CLI packaging metadata). The project skill files and release scripts are
also maintained documentation/tooling. scale_release/, scale_release.zip, and
scale_release_exe/ are generated artifacts: never edit them as source and
never commit them. backend/ is the runtime source of truth for shared CAD and
translation behavior.

## Critical paths

| Task | Entry point |
|------|-------------|
| Start backend | cd backend; python run_server.py |
| Start frontend | cd frontend; npm run dev |
| Start Celery worker | cd backend; python run_celery.py |
| Install/test CLI locally | cd agent-harness; python -m pip install -e .; cad-translate --help |
| CLI packaging tests | python -m pytest tests/cli/test_cli_packaging.py -q |
| Full test suite | `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"; python -m pytest tests -q` |
| Build runtime bundle | scripts/build_scale.ps1 |
| Audit a bundle | .agents/skills/cad-translation-dev/scripts/security-audit.ps1 -ReleaseDir <absolute-or-relative-path> |
| API documentation | http://localhost:8000/api/docs or /api/redoc |
| Canonical release version | backend/app/version.py (__version__, SemVer) |
| Runtime config | %USERPROFILE%\\.config\\cli-anything-cad\\config.json, unless an override is set |

The test command disables auto-loaded third-party pytest plugins because old
sibling projects in this workspace can otherwise be collected accidentally.
Prefer the repository's backend virtual environment when it exists.

## Development workflow

### Backend or CAD pipeline change

1. Edit the active implementation under backend/app/.
2. For routes, update the corresponding module under backend/app/routers/ or backend/app/api/routes/.
3. Keep file/path safety checks, task-directory isolation, and admin-guard behavior intact.
4. Run focused tests, then the full tests/ suite. If the change affects packaging, also run tests/cli/test_cli_packaging.py.
5. Update the relevant README or docs/modern/ document when behavior, API, configuration, or the build process changes.

### Frontend change

1. Edit frontend/src/; the active root component is App.tsx and currently mounts the workbench directly.
2. Use npm run lint and npm run build from frontend/.
3. Check API paths against frontend/src/services/api.ts and references/api-routes.md.

### CLI change

1. Edit agent-harness/cad_translate/ and keep the CLI as a thin facade over backend/app.
2. Keep version metadata dynamic: agent-harness/setup.py reads backend/app/version.py; do not add a second hard-coded release version.
3. Verify cad-translate --version, cad-translate --help, cad-translate doctor, and the affected command group. Use --json when testing machine-readable output.
4. Run the CLI packaging tests and confirm that a clean delivery bundle contains cli/, cad-cli.bat, install_cli.bat, and CLI.md.

### Local release bundle

~~~powershell
# Full build, including frontend/dist
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1

# Use only when frontend/dist is already the intended build
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1 -SkipFrontendBuild
~~~

The script regenerates scale_release/ and scale_release.zip under the selected
root. These outputs are ignored and must remain untracked. Audit both the
directory and, when publishing, the ZIP contents; verify required runtime
files, CLI smoke behavior, and a SHA-256 checksum before attaching an artifact
to a GitHub Release. Do not manually delete a broad OneDrive path to clean a
build. If the checkout is a OneDrive reparse-point workspace, use a separately
verified local/G: staging location or a disposable local checkout, and resolve
the exact absolute target before replacing generated output.

Run the read-only audit with:

~~~powershell
& .\.agents\skills\cad-translation-dev\scripts\security-audit.ps1 -ReleaseDir <bundle-path>
~~~

The audit must reject databases, local configuration/secrets, virtual
environments, caches, logs, tests, source frontend files, and packaging
leftovers while allowing the intentional frontend/dist/ and CLI runtime files.
See references/security-checklist.md.

## Agent-assisted use and API-key boundary

This skill is an instruction set; invoking it does not itself require a CAD
project API key. When the user asks the current Agent to inspect drawings,
extract text, translate a bounded result, or explain a failure, the Agent may
use the model and tools already available in the current authorized session.
Do not ask the user to configure a provider key merely to activate this skill.

Keep the execution modes separate:

- **Agent-assisted mode**: the current Agent performs the reasoning or
  translation in-session and writes only the requested artifacts. This uses the
  Agent runtime's existing access and may have context, file-size, rate, or
  privacy limits. It does not create a reusable project credential.
- **Project runtime mode**: the Web app, cad-translate pipeline commands, Celery
  workers, and unattended/bulk jobs call the configured LLM provider from the
  project runtime. These still need the provider's configured API key or other
  supported authentication, unless the selected provider is a local/no-key
  backend.

Before sending drawing text to an Agent or remote provider, confirm the user's
authorization and the data boundary. Never print, commit, or place a supplied
key in a skill file, project JSON, release bundle, or task log. If an Agent
cannot access the needed model/tool or the input is too large, report that
boundary clearly and use the project's configured runtime only when the user
has provided and authorized it.

## Agent drawing-handling deliverable (DXF only)

When the Agent processes a drawing directly in **Agent-assisted mode** and the
user asks for a translated result, deliver the final **DXF** produced by the
backfill (`apply`) step. Do **not** run an extra round-trip that converts the
translated DXF back to DWG. DWG -> DXF is only needed so ezdxf can read and
edit the text; after translation the DXF is already the intended deliverable.
Skip redundant DWG conversion (COM, ODA File Converter, or LibreDWG) unless the
user explicitly asks for a DWG output.

## Agent bilingual translation: auto-detect keep-vs-translate

A drawing often mixes a local/native language with universal English engineering
identifiers. When the user wants the drawing translated into a **target language
T** (which may be Russian, English, Japanese, French, ... it is **not fixed** and
must come from the user / the request, never be assumed), decide per text using
the recommended auto-detection logic (do not blindly translate every string):

    target = T   # user-specified, no hard-coded default

    IF text is already in T:               KEEP
    ELIF text is Chinese:                  TRANSLATE_TO_T
    ELIF text is English (and EN != T):
        IF user asked to keep EN + T bilingual:  KEEP
        ELSE:
            IF it is a name / model / tag /
               standard / code / unit:          KEEP
            ELSE:                                TRANSLATE_TO_T
    ELIF text is another language:
        follow the user intent; when unsure default to KEEP
    ELSE:                                  KEEP

Notes:
- T is a variable driven by the user's target-language request; this logic does
  not hard-code any particular language (e.g. do not default to Russian).
- Chinese text is usually the drawing's native source and is translated to T.
- English is treated as an international engineering language: it is only
  translated to T when the user wants full English unification and it is not a
  protected identifier; when T itself is English, English text is already the
  target and is kept.

For a mixed string such as `XV-101 Solenoid Valve`: protect the identifier
`XV-101` (model/tag) and translate only the descriptive part `Solenoid Valve`
into the chosen T (T=Russian → `Электромагнитный клапан`, T=Chinese → `电磁阀`),
yielding e.g. `XV-101 Электромагнитный клапан` (T=Russian). Never translate
protected identifiers (names, model numbers, tags/位号, standards, codes, units).

## Agent standard bilingual workflow

DWG
→ DWG→DXF
→ extract all TEXT / MTEXT / ATTRIB / ATTDEF / BLOCK
→ language detection
→ build the existing term table
→ confirm target language T (from the user / request)
→ identify source-language-only text to translate (Chinese, etc.)
→ source → T
→ backfill (apply)
→ verify source-language residual = 0
→ does the user require full unification of English to T?
    ├─ no  → done
    └─ yes →
        extract English-only text
        exclude names / models / tags / standards / codes / units
        English → T
        backfill (apply)
        classify remaining English residual
        check CAD layout
        final DXF

This is Agent guidance for how to decide keep vs translate; the actual
extraction/backfill steps reuse backend/app implementations as described above.
The target language comes from the user request / API parameter and the backend
translates into that target without assuming a preset language.


## Windows CAD and internal multi-user boundary

- AutoCAD, GStarCAD/浩辰, and ZWCAD COM are capabilities of the Windows host running the backend, not of a browser client. Detection enumerates registered COM ProgIDs and the process table; it does not install CAD software. For DWG compatibility, prefer an installed vendor CAD COM backend; ODA File Converter and LibreDWG are fallback options and should be validated before production use. See docs/modern/AUTOCAD_COM_DETECTION.md.
- A registered ProgID is not proof that activation works. Bounded activation probes classify timeouts/failures, and real COM conversion keeps activation, document work, and release in one COM thread/process. COM conversions are serialized by default (CAD_COM_CONCURRENCY=1).
- Multiple browser clients can submit independent tasks: task IDs and output directories are unique, metadata/config writes use stable sidecar locks plus atomic replacement, SQLite has a busy timeout, and Excel output names are UUID-prefixed. These safeguards prevent common collisions; they do not create accounts or tenant boundaries.
- The system is single-tenant. ENABLE_ADMIN_GUARD protects the whole instance with ADMIN_API_TOKEN; it is not per-user authorization. For internal multi-user deployment, use a durable shared upload/output location, a database/worker topology appropriate for concurrent access, explicit CORS origins, and a deliberate COM serialization limit. Do not expose the default HTTP service publicly without a TLS-terminating reverse proxy.
- LLM rate-limit buckets are process-local. Recalculate effective capacity when running multiple workers.

## Code and documentation standards

- Keep each module under 800 lines (.trae/rules/project_rules.md).
- Python uses PEP 8, type annotations, and from __future__ import annotations for new modules.
- Frontend components use PascalCase; variables and functions use camelCase.
- Follow SemVer. Change the canonical value in backend/app/version.py, then verify the backend and CLI report the same version; do not hard-code a version in long-lived skill or README text.
- Every new feature or metric must define and verify its temporal shift. Prevent look-ahead leakage: a feature at time t must use only data available at or before the declared shifted observation time.
- After behavior/config/API changes, update help text, errors, metadata, README, and the relevant docs/modern/ page. Keep one canonical source for fast-changing facts and link to it.
- Before completion, run git diff --check, remove generated caches/logs from the change set, and verify the final state rather than documenting abandoned alternatives.

## Key configuration

| Config | Location | Purpose |
|--------|----------|---------|
| Static environment | backend/.env (template: backend/.env.example) | DB, Redis, host/port, converter and guard settings |
| Environment-file override | CAD_TRANSLATION_ENV_FILE | Select a different .env file |
| Runtime config override | CAD_TRANSLATION_RUNTIME_CONFIG_FILE | Select a different JSON runtime config |
| Runtime config default | XDG_CONFIG_HOME/cli-anything-cad/config.json or Path.home()/.config/cli-anything-cad/config.json | LLM/CAD defaults and provider settings |
| Provider presets | backend/app/config.py and the LLM service | Built-in provider/model defaults |

Never commit real API keys, .env, runtime local JSON, databases, logs, or
generated release output.

## Reference documents

- references/project-layout.md — maintained source, generated artifacts, and legacy boundaries.
- references/security-checklist.md — bundle audit and publication gates.
- references/api-routes.md — verified backend endpoint quick reference.
- docs/modern/AUTOCAD_COM_DETECTION.md — AutoCAD/浩辰/中望 detection, activation bounds, and host boundary.
- docs/modern/RELEASE_SCALE.md — runtime and EXE packaging behavior.
