"""LibreDWG installation, candidate discovery and DXF normalization."""
from __future__ import annotations
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
import ezdxf
import structlog

logger = structlog.get_logger(__name__)


class LibreDwgSupport:
    def _libredwg_install_root(self) -> Path:
        path = Path(self.libredwg_install_dir)
        if path.is_absolute():
            return path
        return (self._repo_root() / path).resolve()

    def _candidate_libredwg_paths(self) -> Iterable[Path]:
        if self.libredwg_dwg2dxf_path:
            yield self._resolve_support_path(self.libredwg_dwg2dxf_path)

        for binary_name in ("dwg2dxf.exe", "dwg2dxf"):
            discovered = shutil.which(binary_name)
            if discovered:
                yield Path(discovered)

        install_root = self._libredwg_install_root()
        yield install_root / "dwg2dxf.exe"
        yield install_root / "dwg2dxf"

        if install_root.exists():
            yield from sorted(install_root.rglob("dwg2dxf.exe"))
            yield from sorted(install_root.rglob("dwg2dxf"))

    def _resolve_libredwg_binary(self) -> Path:
        seen: set[Path] = set()
        for candidate in self._candidate_libredwg_paths():
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.exists():
                return resolved

        if self.libredwg_auto_download:
            return self._download_libredwg()

        raise ValueError(
            "LibreDWG dwg2dxf executable was not found. Configure LIBREDWG_DWG2DXF_PATH "
            "or enable LIBREDWG_AUTO_DOWNLOAD."
        )

    def _download_libredwg(self) -> Path:
        download_url = self.libredwg_download_url.strip()
        if not download_url:
            raise ValueError("LIBREDWG_DOWNLOAD_URL is empty and no local dwg2dxf executable was found.")

        install_root = self._libredwg_install_root()
        install_root.mkdir(parents=True, exist_ok=True)
        archive_name = Path(urlparse(download_url).path).name or "libredwg-win64.zip"
        archive_path = install_root.parent / archive_name

        if not archive_path.exists():
            logger.info("libredwg_download_started", url=download_url, destination=str(archive_path))
            with urllib.request.urlopen(download_url, timeout=self.cad_converter_timeout) as response:
                archive_path.write_bytes(response.read())

        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(install_root)

        for candidate in self._candidate_libredwg_paths():
            resolved = candidate.resolve()
            if resolved.exists():
                logger.info("libredwg_download_succeeded", binary=str(resolved))
                return resolved

        raise ValueError(
            f"LibreDWG download completed but dwg2dxf.exe was not found under: {install_root}"
        )

    def _repair_libredwg_dxf_structure(self, raw_output_path: Path) -> None:
        lines = raw_output_path.read_text(encoding="utf-8", errors="replace").splitlines()
        repaired_lines: list[str] = []
        expect_group_code = True
        merged_lines = 0

        for line in lines:
            stripped = line.strip()
            if expect_group_code:
                if stripped and stripped.lstrip("+-").isdigit():
                    repaired_lines.append(line)
                    expect_group_code = False
                    continue
                if not repaired_lines:
                    raise ValueError(
                        f"LibreDWG emitted an invalid DXF structure at the start of {raw_output_path.name}."
                    )
                repaired_lines[-1] += line
                merged_lines += 1
                continue

            repaired_lines.append(line)
            expect_group_code = True

        raw_output_path.write_text(
            "\n".join(repaired_lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if merged_lines:
            logger.info("libredwg_structure_repaired", merged_lines=merged_lines, file=str(raw_output_path))

    def _sanitize_materials_for_save(self, doc) -> None:
        invalid_names = []
        for name, entry in list(doc.materials.object_dict.items()):
            material = entry
            if isinstance(entry, str):
                material = doc.entitydb.get(entry)
            if material is None or getattr(material, "dxftype", lambda: None)() != "MATERIAL":
                doc.materials.object_dict.discard(name)
                invalid_names.append(name)

        if invalid_names:
            logger.info("dwg_conversion_sanitized_materials", removed=invalid_names)
            doc.header["$CMATERIAL"] = "0"

        doc.materials.create_required_entries()

    def _validate_and_finalize_dxf(self, raw_output_path: Path, final_output_path: Path) -> str:
        doc = ezdxf.readfile(str(raw_output_path))
        self._sanitize_materials_for_save(doc)

        validated_output = final_output_path.with_suffix(".validated.dxf")
        doc.saveas(str(validated_output))
        validated_output.replace(final_output_path)
        return str(final_output_path)
