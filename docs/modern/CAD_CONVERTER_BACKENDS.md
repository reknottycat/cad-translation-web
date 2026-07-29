# DWG Converter Backends

## Default Route B Stack

The backend now treats DWG conversion as a Route B normalization step:

`DWG -> converter backend -> DXF -> text extraction -> translation -> DXF write-back`

Default order:

1. `acadsharp`
2. `oda` fallback when configured

## Configuration

Set these values in `backend/.env`:

```env
DWG_CONVERTER_BACKEND=acadsharp
ACADSHARP_BRIDGE_PROJECT=../tools/AcadSharpBridge/AcadSharpBridge.csproj
ACADSHARP_BRIDGE_DLL=
ODA_FILE_CONVERTER_PATH=C:\\Program Files\\ODA\\ODAFileConverter\\ODAFileConverter.exe
ODA_OUTPUT_VERSION=ACAD2018
ODA_OUTPUT_FORMAT=DXF
CAD_CONVERTER_TIMEOUT=300
```

## Supported Values

- `acadsharp`: Use the bundled .NET ACadSharp bridge first.
- `oda`: Use ODA File Converter directly.
- `com`: Use the existing COM bridge for desktop-only fallback.
- `dxf_only`: Skip DWG conversion and accept DXF only.

Frontend selector mapping:

- `auto` -> `acadsharp`
- `oda_cli` -> `oda`
- `autocad_com` / `gstar_com` -> `com`
- `dxf_native` -> `dxf_only`

## Notes

- `acadsharp` is now the primary open-code backend, but some DWG versions can still fail with `File version not recognized`.
- When `acadsharp` fails and `ODA_FILE_CONVERTER_PATH` is configured, the backend falls back to ODA automatically.
- If neither `acadsharp` nor `oda` can handle the file, the API returns a clear error instead of hanging in COM.
