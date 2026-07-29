# CAD Three-Backend Routing Design

**Date:** 2026-03-16

## Goal

Support three DWG conversion backends in the backend and standalone CLI:

1. `haochen_com`
2. `autocad_com`
3. `oda`

The default behavior should use ordered fallback:

`haochen_com -> autocad_com -> oda`

## Why This Design

The recent `LibreDWG` replacement improved text and geometry conversion, but it still dropped image-bearing content in the user's real `DWG` sample. The user confirmed that `ODA File Converter` preserves the image-bearing output acceptably, and they also want the existing HaoChen and AutoCAD COM paths from `trans_CAD_gui_V1.0` available first.

## Chosen Approach

Keep all DWG conversion routing inside `backend/app/functions/dwg_converter.py`, but treat it as an orchestrator instead of a single-backend converter.

### Backend Order

- explicit `haochen_com` uses only HaoChen COM
- explicit `autocad_com` uses only AutoCAD COM
- explicit `oda` uses only ODA
- explicit `com` preserves old compatibility by trying both COM backends in order
- `auto` and empty backend use:
  - `haochen_com`
  - `autocad_com`
  - `oda`

## Backend Sources

### HaoChen COM

Reuse:

- `trans_CAD_gui_V1.0/haochen_optimized_converter.py`

### AutoCAD COM

Reuse:

- `trans_CAD_gui_V1.0/autocad_converter.py`

### ODA

Use locally installed `ODAFileConverter.exe`.

The backend should auto-discover the executable from:

1. explicit config
2. `PATH`
3. common Windows install locations under `C:\Program Files\ODA\`

If ODA is not installed, the error should tell the user to install it from the official ODA page.

## Scope

### In Scope

- route DWG conversion through the three requested backends
- ordered fallback behavior
- clear backend names in API and CLI
- ODA auto-discovery and install guidance
- regression tests covering fallback and real conversion

### Out of Scope

- bundling ODA binaries into the repository
- restoring `LibreDWG` as a primary path
- changing DXF extract/apply behavior beyond converter selection

## Error Handling

When a backend fails, collect a backend-specific message and continue to the next backend only if fallback is allowed.

If all backends fail, raise one final error that includes:

- attempted backends
- which step failed for each backend
- ODA install guidance when ODA is missing

## Testing

The implementation should prove:

- backend names map correctly
- `auto` tries the three backends in order
- `com` tries HaoChen then AutoCAD
- a real DWG can still round-trip through the default path
- ODA remains available as the last reliable fallback for image-bearing drawings
