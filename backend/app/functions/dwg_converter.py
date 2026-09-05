#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DWG to DXF conversion helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from csv import reader as csv_reader
from io import StringIO
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import ezdxf
import structlog

try:  # pragma: no cover - depends on package context
    from app.functions import autocad_discovery
    from app.functions import com_activation_probe as _com_probe
    from app.functions.autocad_discovery import (
        AUTOCAD_BASELINE_PROGIDS as _AUTOCAD_BASELINE_PROGIDS,
    )
except Exception:  # pragma: no cover - standalone/odd sys.path
    autocad_discovery = None
    _AUTOCAD_BASELINE_PROGIDS = []
    _com_probe = None


logger = structlog.get_logger(__name__)

# Serialize COM-based DWG conversions: multiple subprocesses concurrently
# Dispatching the same AutoCAD/ZWCAD/GStarCAD COM instance causes races and
# intermittent COM errors. A module-level semaphore keeps at most N conversions
# running at once (default 1, configurable via env CAD_COM_CONCURRENCY).
_com_concurrency = max(1, int(os.environ.get("CAD_COM_CONCURRENCY", "1")))
_COM_SEMAPHORE = threading.BoundedSemaphore(_com_concurrency)


from app.functions.libredwg_support import LibreDwgSupport


class DWGConverter(LibreDwgSupport):
    """Convert DWG files to DXF using the configured backend."""

    def __init__(
        self,
        converter_backend: str = "dxf_only",
        dwg_auto_backends: str = "haochen_com,autocad_com,oda",
        dwg_disabled_backends: str = "",
        oda_path: str = "",
        oda_output_version: str = "ACAD2018",
        oda_output_format: str = "DXF",
        cad_converter_timeout: int = 120,
        libredwg_dwg2dxf_path: str = "",
        libredwg_install_dir: str = "tools/libredwg/0.13.3-win64",
        libredwg_download_url: str = (
            "https://github.com/LibreDWG/libredwg/releases/download/0.13.3/"
            "libredwg-0.13.3-win64.zip"
        ),
        libredwg_auto_download: bool = True,
    ) -> None:
        self.converter_backend = converter_backend.strip().lower()
        self.dwg_auto_backends = dwg_auto_backends
        self.dwg_disabled_backends = dwg_disabled_backends
        self.oda_path = oda_path
        self.oda_output_version = oda_output_version
        self.oda_output_format = oda_output_format
        self.cad_converter_timeout = cad_converter_timeout
        self.libredwg_dwg2dxf_path = libredwg_dwg2dxf_path
        self.libredwg_install_dir = libredwg_install_dir
        self.libredwg_download_url = libredwg_download_url
        self.libredwg_auto_download = libredwg_auto_download
        # When a COM backend is registered but no process is running, registry
        # presence does not prove Dispatch will return (a registered-but-hung
        # 浩辰/中望 ProgID can block for tens of seconds).  Bounded live-activation
        # probing during inspection distinguishes "confirmed activatable" from
        # "registered but activation timed out / failed" so the auto chain does
        # not waste a long time on a backend whose COM server never answers.
        self.com_activation_probe_enabled = True
        # Unified activation bound shared with com_activation_probe: a single
        # CAD_COM_ACTIVATION_TIMEOUT knob drives both the probe and the connection
        # layer.  Default 30s gives a real AutoCAD 2026 cold start (~6.5s) clear
        # margin while still bounding a hung COM server.
        if _com_probe is not None:
            _probe_default = _com_probe.default_activation_timeout()
        else:
            _probe_default = float(os.environ.get("CAD_COM_ACTIVATION_TIMEOUT", "30"))
        self.com_activation_probe_timeout = _probe_default

    def _backend_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _repo_root(self) -> Path:
        return self._backend_root().parent

    def _resolve_support_path(self, value: str) -> Path:
        """Resolve support files relative to backend/ first, then repo root."""
        path = Path(value)
        if path.is_absolute():
            return path

        backend_candidate = (self._backend_root() / path).resolve()
        if backend_candidate.exists():
            return backend_candidate

        repo_candidate = (self._repo_root() / path).resolve()
        if repo_candidate.exists():
            return repo_candidate

        # Default to backend-relative resolution for clearer error messages.
        return backend_candidate

    def convert(
        self,
        dwg_file_path: str,
        output_dir: Path,
        backend_override: Optional[str] = None,
    ) -> str:
        backend = (backend_override or self.converter_backend).strip().lower()

        if backend == "dxf_only":
            raise ValueError(
                "DWG conversion backend is dxf_only. Upload DXF or configure a real DWG converter backend."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_dxf = output_dir / f"{Path(dwg_file_path).stem}.dxf"

        if backend in {"", "auto"}:
            selected_backends = self._select_auto_backends()
            return self._convert_with_fallback(
                dwg_file_path,
                output_dir,
                str(output_dxf),
                selected_backends,
            )
        if backend == "haochen_com":
            return self._convert_via_haochen_com(dwg_file_path, str(output_dxf))
        if backend == "autocad_com":
            return self._convert_via_autocad_com(dwg_file_path, str(output_dxf))
        if backend == "com":
            return self._convert_with_fallback(
                dwg_file_path,
                output_dir,
                str(output_dxf),
                ["haochen_com", "autocad_com"],
            )
        if backend == "libredwg":
            return self._convert_via_libredwg(dwg_file_path, output_dir, str(output_dxf))
        if backend == "oda":
            return self._convert_via_oda(dwg_file_path, output_dir, str(output_dxf))

        raise ValueError(f"Unsupported DWG conversion backend: {backend}")

    def _service_script_path(self, filename: str) -> Path:
        return self._backend_root() / "app" / "services" / filename

    def _ensure_service_script(self, filename: str) -> Path:
        script_path = self._service_script_path(filename)
        if not script_path.exists():
            raise ValueError(f"Required converter script is missing: {script_path}")
        return script_path

    def _com_attempt_timeout(self) -> int:
        return max(5, min(self.cad_converter_timeout, 20))

    def _subprocess_run_kwargs(self) -> dict[str, object]:
        if os.name != "nt":
            return {}

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            "startupinfo": startupinfo,
        }

    def _ascii_safe_stem(self, stem: str, fallback: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
        return cleaned or fallback

    def _prepare_com_paths(
        self,
        dwg_file_path: str,
        output_dxf_path: str,
        backend_slug: str,
    ) -> tuple[Path, Path, Path]:
        final_output = Path(output_dxf_path)
        safe_backend = self._ascii_safe_stem(backend_slug, "com")
        work_dir = final_output.parent / "_com_ascii_tmp" / safe_backend
        work_dir.mkdir(parents=True, exist_ok=True)

        source_path = Path(dwg_file_path)
        input_copy = work_dir / "input.dwg"
        shutil.copy2(source_path, input_copy)

        raw_output = work_dir / "output.dxf"
        raw_output.unlink(missing_ok=True)
        return input_copy, raw_output, final_output

    def _convert_with_fallback(
        self,
        dwg_file_path: str,
        output_dir: Path,
        output_dxf_path: str,
        backends: list[str],
    ) -> str:
        failures: list[str] = []
        for backend in backends:
            try:
                if backend == "haochen_com":
                    return self._convert_via_haochen_com(dwg_file_path, output_dxf_path)
                if backend == "autocad_com":
                    return self._convert_via_autocad_com(dwg_file_path, output_dxf_path)
                if backend == "oda":
                    return self._convert_via_oda(dwg_file_path, output_dir, output_dxf_path)
            except Exception as exc:
                logger.warning("dwg_backend_failed", backend=backend, error=str(exc))
                failures.append(f"{backend}: {exc}")
        raise ValueError("DWG conversion failed. " + " | ".join(failures))

    def _parse_backend_list(self, value: str, default: list[str]) -> list[str]:
        raw = [item.strip().lower() for item in value.split(",")] if value.strip() else default
        normalized: list[str] = []
        for backend in raw:
            if backend and backend not in normalized:
                normalized.append(backend)
        return normalized

    def _configured_auto_backends(self) -> list[str]:
        return self._parse_backend_list(self.dwg_auto_backends, ["haochen_com", "autocad_com", "oda"])

    def _disabled_backends(self) -> set[str]:
        return set(self._parse_backend_list(self.dwg_disabled_backends, []))

    def _backend_prog_ids(self, backend: str) -> list[str]:
        mapping = {
            "haochen_com": [
                "GStarCAD.Application",
                "Gcad.Application",
                "GStarCAD.Application.26",
                "Gcad.Application.26",
                "ZWCAD.Application",
            ],
            # AutoCAD uses dynamic versioned discovery via the registry so future
            # releases (AutoCAD.Application.<major>[.<minor>]) are recognised even
            # when this code has not been updated to list them explicitly.
            "autocad_com": list(_AUTOCAD_BASELINE_PROGIDS)
            if autocad_discovery is None
            else autocad_discovery.discovered_autocad_progids(),
        }
        return mapping.get(backend, [])

    def _backend_process_names(self, backend: str) -> set[str]:
        mapping = {
            "haochen_com": {"gcad.exe", "gstarcad.exe", "zwcad.exe"},
            "autocad_com": {"acad.exe"},
        }
        return mapping.get(backend, set())

    def _running_process_names(self) -> set[str]:
        try:
            completed = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                **self._subprocess_run_kwargs(),
            )
        except Exception:
            return set()
        if completed.returncode != 0:
            return set()

        names: set[str] = set()
        for row in csv_reader(StringIO(completed.stdout)):
            if not row:
                continue
            names.add(row[0].strip().lower())
        return names

    def _registered_prog_ids(self) -> set[str]:
        if os.name != "nt" or autocad_discovery is None:
            # Fall back to a fixed ProgID probe when the discovery helper is not
            # importable (odd sys.path) but winreg exists.
            if os.name != "nt":
                return set()
            try:
                import winreg
            except ImportError:
                return set()
            registered: set[str] = set()
            for backend in ("haochen_com", "autocad_com"):
                for prog_id in self._backend_prog_ids(backend):
                    try:
                        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id):
                            registered.add(prog_id.lower())
                    except OSError:
                        continue
            return registered

        # Prefer the dedicated discovery module: it enumerates versioned AutoCAD
        # ProgIDs and distinguishes registry views.
        from app.functions.autocad_discovery import _iter_registered_autocad_keys

        registered: set[str] = set()
        try:
            for prog_id, _ in _iter_registered_autocad_keys():
                registered.add(prog_id.lower())
        except Exception:
            pass
        # haochen/ZWCAD/GStarCAD ProgIDs are still resolved via a classic open.
        for backend in ("haochen_com",):
            for prog_id in self._backend_prog_ids(backend):
                try:
                    import winreg as _wr

                    with _wr.OpenKey(_wr.HKEY_CLASSES_ROOT, prog_id):
                        registered.add(prog_id.lower())
                except Exception:
                    continue
        return registered

    def _probe_com_activation(self, backend: str) -> str:
        """Boundedly activate a registered-but-not-running COM backend.

        Returns one of ``"activatable"`` / ``"activation_timeout"`` /
        ``"activation_failed"`` / ``"registered"`` (the last when probing is
        disabled or the probe cannot run, e.g. a non-Windows host).  Runs each
        candidate ProgID under a per-attempt timeout so a hung COM server never
        blocks the caller.

        On Windows a *hung* COM server (one that never answers ``Dispatch``)
        can still have started a CAD process (e.g. ``gcad.exe``) before it
        stalls.  The probe flags such an attempt ``cleanup_required`` so the
        caller can reclaim the stray process.  We record the CAD PIDs present
        before probing and, only when a per-ProgID attempt timed out and asked
        for cleanup, kill the PIDs that newly appeared with a matching image --
        never a user's already-open CAD."""
        if not self.com_activation_probe_enabled or _com_probe is None:
            return "registered"
        prog_ids = self._backend_prog_ids(backend)
        if not prog_ids:
            return "registered"
        cad_images = self._backend_process_names(backend)
        try:
            # Snapshot of this backend's running CAD PIDs before any probe could
            # start an instance, so a timeout reclaims only what *this* probe
            # launched and leaves a user's open CAD untouched.
            before = self._cad_pids(cad_images)
            overall, per = _com_probe.probe_registered_prog_ids(
                prog_ids, self.com_activation_probe_timeout
            )
            # The daemon worker closes an instance once Dispatch returns; but
            # when a COM server *never* answers, the worker stays blocked inside
            # Dispatch and cannot close the CAD process it already started.  That
            # per-attempt outcome carries cleanup_required=True -- reclaim the
            # newly-started matching CAD now so no orphan gcad.exe / acad.exe is
            # left behind by inspect / auto-sieving.
            if any(
                isinstance(out, dict) and out.get("cleanup_required")
                for out in per
            ):
                after = self._cad_pids(cad_images)
                new_pids = after - before
                if new_pids:
                    self._kill_pids(new_pids)
                    logger.warning(
                        "com_probe_reclaimed_stray_cad",
                        backend=backend,
                        pids=sorted(new_pids),
                    )
            return overall  # activatable | activation_timeout | activation_failed
        except Exception:  # pragma: no cover - probe must never crash inspection
            logger.warning("com_activation_probe_failed", backend=backend)
            return "registered"

    def inspect_backends(self) -> dict[str, dict[str, object]]:
        """Inspect configured DWG backends and report availability.

        For the AutoCAD COM backend the reasons are:
          ``script_missing``, ``process_running``, ``registered``,
          ``not_detected`` (=== not installed on this host).  ``detected`` is
          True only when the Python bridge script exists AND the backend is
          registered or running -- a lone Python script never implies AutoCAD
          is installed.
        """
        processes = self._running_process_names()
        registered_prog_ids = self._registered_prog_ids()
        disabled = self._disabled_backends()
        inspected: dict[str, dict[str, object]] = {}

        for backend in self._configured_auto_backends():
            if backend == "oda":
                oda_candidates = [candidate for candidate in self._candidate_oda_paths() if candidate.exists()]
                inspected[backend] = {
                    "detected": bool(oda_candidates),
                    "disabled": backend in disabled,
                    "reason": "binary_found" if oda_candidates else "binary_missing",
                    "actionable": (
                        "ODA File Converter binary found."
                        if oda_candidates
                        else "ODA File Converter was not found; install it or set ODA_FILE_CONVERTER_PATH."
                    ),
                }
                continue

            script_ok = False
            reason = "unsupported"
            actionable = reason
            if backend == "haochen_com":
                script_ok = self._service_script_path("haochen_optimized_converter.py").exists()
            elif backend == "autocad_com":
                script_ok = self._service_script_path("autocad_converter.py").exists()

            running = bool(self._backend_process_names(backend) & processes)
            registered = any(prog_id.lower() in registered_prog_ids for prog_id in self._backend_prog_ids(backend))
            detected = script_ok and (running or registered)
            if not script_ok:
                reason = "script_missing"
                actionable = (
                    "Python COM bridge script is missing for this backend; "
                    "the backend package is incomplete."
                )
            elif running:
                reason = "process_running"
                actionable = "CAD application is running; conversion may proceed via COM."
            elif registered:
                # Registry presence does not prove Dispatch will return.  Bound a
                # real activation so a registered-but-hung 浩辰/中望 ProgID is not
                # optimistically treated as usable and first in the fallback chain.
                reason = self._probe_com_activation(backend)
                actionable = {
                    "activatable": "CAD application is installed and COM activation succeeded.",
                    "activation_timeout": (
                        "CAD application is registered but COM activation timed out "
                        "(the COM server may be hung, blocked by a modal dialog, or "
                        "hit a licensing/bitness/permission issue). The backend is "
                        "skipped in the auto chain; check the installation."
                    ),
                    "activation_failed": (
                        "CAD application is registered but COM activation failed "
                        "(bitness / permissions / damaged registration). The backend "
                        "is skipped in the auto chain."
                    ),
                }.get(reason, "CAD application is installed and registered.")
            else:
                reason = "not_detected"
                actionable = (
                    "No CAD registration or process was detected on this host; "
                    "the application is not installed/registered here."
                )

            inspected[backend] = {
                "detected": detected,
                "disabled": backend in disabled,
                "reason": reason,
                "actionable": actionable,
            }

        return inspected

    def _select_auto_backends(self) -> list[str]:
        # Auto mode: honour the configured fallback chain but sieve out COM
        # backends that are *certainly* unusable on this host: the bridge script
        # is missing, nothing is registered and no process is running, or a
        # bounded live activation probe found the backend registered-but-hung or
        # activation-failed.  A lone Python bridge script must never be treated
        # as "AutoCAD is installed", and a merely-registered-but-not-activatable
        # 浩辰/中望 backend must not be first in the chain (it would stall).
        configured = [
            backend
            for backend in self._configured_auto_backends()
            if backend not in self._disabled_backends()
        ]
        inspected = self.inspect_backends()

        selected: list[str] = []
        for backend in configured:
            info = inspected.get(backend, {})
            reason = info.get("reason")
            detected = info.get("detected", False)
            if backend == "oda":
                # ODA/LibreDWG-style binary fallbacks are kept only when present.
                selected.append(backend)
                continue
            # COM backends: drop when the bridge script is missing, nothing is
            # registered/running, or a bounded activation probe timed out/failed.
            if reason in {
                "script_missing",
                "not_detected",
                "activation_timeout",
                "activation_failed",
            } or not detected:
                continue
            selected.append(backend)

        # If the sieve removed every backend but something is configured, keep the
        # original ordered chain so _convert_with_fallback produces a descriptive
        # multi-backend error naming each failure instead of an empty list.
        if not selected and configured:
            selected = configured

        logger.info(
            "dwg_auto_backends_selected",
            selected=selected,
            strategy="probe_sieved_fallback_chain",
            inspected=inspected,
        )
        return selected

    def _cad_pids(self, images: set[str]) -> set[str]:
        """Return PIDs of running processes whose image name is in ``images``
        (Windows only).  Used to reclaim a CAD process a timed-out COM conversion
        may have launched."""
        if os.name != "nt":
            return set()
        try:
            completed = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                **self._subprocess_run_kwargs(),
            )
        except Exception:
            return set()
        if completed.returncode != 0:
            return set()
        wanted = {im.lower() for im in images}
        pids: set[str] = set()
        for row in csv_reader(StringIO(completed.stdout)):
            if not row or len(row) < 2:
                continue
            if row[0].strip().lower() in wanted:
                pids.add(row[1].strip())
        return pids

    def _kill_pids(self, pids: set[str]) -> None:
        """Best-effort terminate the given PIDs (Windows only)."""
        if not pids or os.name != "nt":
            return
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    **self._subprocess_run_kwargs(),
                )
            except Exception:
                continue

    def _run_com_converter(
        self,
        converter_module: str,
        class_name: str,
        dwg_file_path: str,
        output_dxf_path: str,
    ) -> str:
        repo_root = self._repo_root()
        backend_dir = self._backend_root()
        com_input_path, com_output_path, final_output_path = self._prepare_com_paths(
            dwg_file_path,
            output_dxf_path,
            converter_module.rsplit(".", 1)[-1],
        )
        python_path_parts = [str(backend_dir), str(repo_root)]
        existing = os.environ.get("PYTHONPATH")
        if existing:
            python_path_parts.append(existing)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(python_path_parts)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        command = [
            sys.executable,
            "-m",
            "app.services.com_converter_cli",
            "--module",
            converter_module,
            "--class",
            class_name,
            "--dwg",
            str(com_input_path),
            "--output",
            str(com_output_path),
        ]
        # Acquire the global COM semaphore to avoid concurrent subprocesses racing
        # on the same CAD COM instance. Released in finally to survive exceptions/timeouts.
        backend = "haochen_com" if "haochen" in converter_module else "autocad_com"
        cad_images = self._backend_process_names(backend)
        _COM_SEMAPHORE.acquire()
        try:
            # Record CAD PIDs before launching so, on a timeout, we can reclaim
            # only the instance this conversion started (not a user's open CAD).
            before = self._cad_pids(cad_images)
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._com_attempt_timeout(),
                env=env,
                cwd=str(repo_root),
                **self._subprocess_run_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            # Process-level reclamation: kill any CAD process this hung conversion
            # launched so a late-returning COM server does not leave an orphan.
            try:
                after = self._cad_pids(cad_images)
                self._kill_pids(after - before)
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            raise ValueError(
                f"{class_name} timed out after {self._com_attempt_timeout()}s while opening or converting DWG; "
                "any CAD process started by this attempt was reclaimed."
            ) from exc
        finally:
            _COM_SEMAPHORE.release()
        if completed.returncode != 0:
            raise ValueError((completed.stderr or completed.stdout or "").strip() or f"exit {completed.returncode}")
        if not com_output_path.exists():
            raise ValueError(f"COM conversion finished but output file is missing: {com_output_path}")
        finalized = self._validate_and_finalize_dxf(com_output_path, final_output_path)
        self._cleanup_com_workspace(com_input_path.parent)
        logger.info("com_conversion_succeeded", converter=class_name, output=finalized)
        return finalized

    def _cleanup_com_workspace(self, workspace_dir: Path) -> None:
        for attempt in range(3):
            try:
                shutil.rmtree(workspace_dir, ignore_errors=False)
                return
            except OSError as exc:
                if attempt == 2:
                    logger.warning("com_workspace_cleanup_failed", workspace=str(workspace_dir), error=str(exc))
                    return
                time.sleep(0.5 * (attempt + 1))

    def _convert_via_haochen_com(self, dwg_file_path: str, output_dxf_path: str) -> str:
        self._ensure_service_script("haochen_optimized_converter.py")
        return self._run_com_converter(
            "app.services.haochen_optimized_converter",
            "OptimizedHaoChenCADConverter",
            dwg_file_path,
            output_dxf_path,
        )

    def _convert_via_autocad_com(self, dwg_file_path: str, output_dxf_path: str) -> str:
        self._ensure_service_script("autocad_converter.py")
        return self._run_com_converter(
            "app.services.autocad_converter",
            "AutoCADConverter",
            dwg_file_path,
            output_dxf_path,
        )

    def _convert_via_libredwg(self, dwg_file_path: str, output_dir: Path, output_dxf_path: str) -> str:
        binary = self._resolve_libredwg_binary()
        raw_output_path = output_dir / "_libredwg_raw_output.dxf"
        command = [str(binary), dwg_file_path, "-o", str(raw_output_path)]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.cad_converter_timeout,
            **self._subprocess_run_kwargs(),
        )
        if completed.returncode != 0 and not raw_output_path.exists():
            raise ValueError(
                f"LibreDWG conversion failed: {(completed.stderr or completed.stdout).strip()}"
            )
        if not raw_output_path.exists():
            raise ValueError(
                f"LibreDWG conversion finished but output file is missing: {raw_output_path}"
            )
        if completed.returncode != 0:
            logger.warning(
                "libredwg_conversion_completed_with_warnings",
                returncode=completed.returncode,
                stderr=(completed.stderr or "").strip()[:2000],
            )

        self._repair_libredwg_dxf_structure(raw_output_path)
        finalized = self._validate_and_finalize_dxf(raw_output_path, Path(output_dxf_path))
        try:
            raw_output_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("libredwg_raw_cleanup_failed", file=str(raw_output_path))
        logger.info("libredwg_conversion_succeeded", output=finalized)
        return finalized

    def _candidate_oda_paths(self) -> Iterable[Path]:
        if self.oda_path:
            yield self._resolve_support_path(self.oda_path)

        discovered = shutil.which("ODAFileConverter.exe") or shutil.which("ODAFileConverter")
        if discovered:
            yield Path(discovered)

        for root in (
            Path("C:/Program Files/ODA"),
            Path("C:/Program Files (x86)/ODA"),
        ):
            if not root.exists():
                continue
            yield from sorted(root.rglob("ODAFileConverter.exe"))

    def _resolve_oda_path(self) -> Path:
        for candidate in self._candidate_oda_paths():
            resolved = candidate.resolve()
            if resolved.exists():
                return resolved
        raise ValueError(
            "ODA File Converter was not found. Install it from "
            "https://www.opendesign.com/GUESTFILES/ODA_FILE_CONVERTER "
            "or set ODA_FILE_CONVERTER_PATH."
        )

    def _convert_via_oda(self, dwg_file_path: str, output_dir: Path, output_dxf_path: str) -> str:
        oda_exe = self._resolve_oda_path()

        command = [
            str(oda_exe),
            str(Path(dwg_file_path).parent),
            str(output_dir),
            self.oda_output_version,
            self.oda_output_format,
            "0",
            "1",
            Path(dwg_file_path).name,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.cad_converter_timeout,
            **self._subprocess_run_kwargs(),
        )
        if completed.returncode != 0:
            raise ValueError(f"ODA conversion failed: {completed.stderr or completed.stdout}")
        if not Path(output_dxf_path).exists():
            raise ValueError(f"ODA conversion finished but output file is missing: {output_dxf_path}")
        finalized = self._validate_and_finalize_dxf(Path(output_dxf_path), Path(output_dxf_path))
        logger.info("oda_conversion_succeeded", output=finalized)
        return finalized
