# LibreDWG Replacement Design

**Date:** 2026-03-16

## Goal

Replace the current `acadsharp` DWG conversion path with `LibreDWG/dwg2dxf`, and make the backend automatically download the official GitHub Windows package when `dwg2dxf` is not already available on the machine.

## Why Replace It

The current `acadsharp` path can produce DXF files that open as empty or fail later round-trip saves because the converted DXF contains invalid material references. The CLI pipeline only succeeds today because later steps sanitize the DXF before saving, which means `convert` by itself is not trustworthy.

## Chosen Approach

Use `LibreDWG` as the primary open-source converter backend and make it the default DWG conversion path across backend and CLI bridge code.

### Converter Resolution Order

When the backend needs `dwg2dxf`, it should resolve it in this order:

1. `LIBREDWG_DWG2DXF_PATH` if explicitly configured
2. `dwg2dxf` found on `PATH`
3. repo-local extracted tool under `tools/libredwg/<version>/dwg2dxf.exe`
4. automatic download from the official GitHub release and extraction into `tools/libredwg/<version>/`

### Auto Download

Auto download should:

1. Use the official GitHub release zip for Windows x64
2. Download only when no usable local binary is found
3. Extract into a stable repo-local folder under `tools/libredwg/`
4. Reuse the extracted binary on later runs instead of downloading again

## Scope

### In Scope

- Replace `acadsharp` as the default backend with `libredwg`
- Add repo-local `LibreDWG` binary discovery and auto-download
- Update backend converter routing and CLI bridge wiring
- Add conversion health checks so obviously bad output fails early
- Update tests and docs to validate the new path

### Out of Scope

- Publishing LibreDWG binaries into git
- Replacing COM or ODA fallback paths
- Adding remote package publishing or installers

## Data Flow

1. CLI or API requests DWG conversion
2. Backend resolves `libredwg` backend
3. Backend locates `dwg2dxf.exe` or auto-downloads it
4. Backend runs `dwg2dxf` to produce DXF
5. Backend validates the DXF can be parsed and saved cleanly
6. Pipeline continues with extract/apply only if validation passes

## Error Handling

The backend should raise clear errors for:

- GitHub download failure
- zip extraction failure
- missing `dwg2dxf.exe` after extraction
- non-zero `dwg2dxf` exit code
- output DXF missing
- output DXF failing parse or round-trip validation

## Testing

The replacement should be covered by:

- unit tests for backend mapping and auto-download resolution
- regression tests for real DWG conversion producing a readable, round-trip-safe DXF
- CLI end-to-end tests for `convert -> extract -> apply`

## Notes

The repo should treat downloaded LibreDWG artifacts as local tooling, not source. They should stay ignored by git while remaining usable for local development and verification.
