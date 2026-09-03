# Project Layout Reference

This map describes the current repository. Generated delivery directories are
not alternate source trees.

## Maintained source

~~~text
backend/
├── app/
│   ├── main.py                         # FastAPI app, lifespan, route registration, static serving
│   ├── version.py                      # Canonical SemVer value
│   ├── config.py                       # Pydantic settings, .env and runtime-config paths
│   ├── database.py                     # SQLAlchemy models and database setup
│   ├── security.py                     # Instance-level admin guard
│   ├── api/routes/cad.py               # /api/cad/* endpoints
│   ├── routers/
│   │   ├── translation.py              # /api/translation/*
│   │   ├── projects.py                 # /api/projects/*
│   │   └── files.py                    # /api/files/*
│   ├── services/
│   │   ├── cad_pipeline_service.py     # upload → convert → extract → translate → apply
│   │   ├── autocad_converter.py        # AutoCAD COM bridge
│   │   ├── haochen_optimized_converter.py # GStarCAD/浩辰 and compatible COM bridge
│   │   ├── com_converter_cli.py        # Dedicated COM subprocess entry
│   │   ├── runtime_config_service.py   # Runtime config and API-key masking
│   │   ├── excel_processor.py          # Excel translation operations
│   │   ├── llm/translation_service.py  # Unified LLM engine
│   │   └── tasks/                      # Celery task definitions
│   ├── functions/
│   │   ├── dwg_converter.py            # Backend selection and DWG→DXF orchestration
│   │   ├── autocad_discovery.py        # AutoCAD registry/process discovery
│   │   ├── com_activation_probe.py     # Bounded live COM activation classification
│   │   ├── com_instance_guard.py       # Usable-instance and stale-proxy protection
│   │   ├── text_extractor.py           # DXF text extraction
│   │   ├── text_applier.py             # Translation backfill into DXF
│   │   └── translator.py               # Compatibility translation wrapper
│   ├── schemas/                        # Pydantic request/response models
│   └── utils/
│       ├── file_utils.py               # Safe filenames, paths, and upload validation
│       └── locking.py                  # Cross-process locks and atomic writes
├── requirements.txt
├── .env.example
└── run_server.py                       # Uvicorn launcher

frontend/
├── src/
│   ├── main.tsx                        # React entry
│   ├── App.tsx                         # Current root composition
│   ├── pages/                          # Workbench, translation, project, and gateway pages
│   ├── components/                     # CAD workflow and shared UI components
│   └── services/api.ts                 # Axios API wrapper
├── vite.config.ts                      # Dev proxy and build configuration
└── package.json

agent-harness/
├── cad_translate/
│   ├── cli.py                          # Click command tree; command is cad-translate
│   ├── operations.py                   # CLI-to-backend operation adapters
│   ├── bridge.py                       # Locate/import backend trusted code
│   ├── store.py                        # Project/task file state
│   └── __main__.py
├── setup.py                            # Reads version from ../backend/app/version.py
├── pyproject.toml                      # Dynamic package metadata and entry point
├── README.md
└── MANIFEST.in
~~~

The active backend routes are registered from backend/app/main.py. The separate
translation-FZH.py module is retained in the source tree for compatibility but
is not the registered modern router.

## Generated delivery artifacts — do not edit or commit

~~~text
scale_release/
├── backend/                            # Runtime backend, without dev-only files
├── cli/                                # Bundled cad_translate package and metadata
├── frontend/dist/                      # Built static frontend; intentional dist
├── tools/                              # Runtime tools, including LibreDWG
├── docs/modern/                        # Release documentation subset
├── start_delivery.bat                 # Web launcher
├── cad-cli.bat                         # Direct bundled CLI launcher
├── install_cli.bat                     # Optional editable CLI installer
├── CLI.md
├── README.md
└── requirements.txt

scale_release.zip                       # Compressed copy of the bundle
scale_release_exe/                      # Optional standalone EXE build output
~~~

The build script creates these outputs from source. They are ignored by Git.
Do not fix a bundle by editing files under scale_release; fix the source or the
build script and rebuild. In a OneDrive workspace, verify reparse-point and
staging paths before replacing generated directories.

## Legacy compatibility code

~~~text
trans_CAD_gui_V1.0/                      # customtkinter desktop application
命令行专用/                               # older standalone pipeline scripts
CLI-Anything/                            # generic plugin framework, not the CAD CLI source
electron_release/                       # older Electron experiment, if present
~~~

These trees can explain old behavior but are not the default implementation.

## Router mapping

| Prefix | Source | Domain |
|--------|--------|--------|
| /api/translation | backend/app/routers/translation.py | Text, batch, Excel, providers, runtime translation config |
| /api/cad | backend/app/api/routes/cad.py | CAD upload, extraction, translation application, downloads, task control |
| /api/projects | backend/app/routers/projects.py | Project CRUD and processing status |
| /api/files | backend/app/routers/files.py | Project file upload/list/detail/download |

All sensitive project/file/CAD/config/translation routes use
require_admin_access when ENABLE_ADMIN_GUARD=true. Public liveness and
language-list endpoints are documented in api-routes.md.

## Data and output boundaries

- Default SQLite is resolved under the backend base directory from DATABASE_URL;
  get_upload_path(), get_output_path(), and get_temp_path() create the
  configured directories.
- CAD task artifacts live below the configured output root, with a unique task
  directory and lifecycle locking. Runtime JSON configuration is outside the
  repository by default and uses the cli-anything-cad/config.json path.
- The application is single-tenant. Unique task paths and locks prevent common
  collisions, but they are not per-user authorization or data partitioning.
