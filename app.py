
"""Desktop window and local data operations for SRAM Wafer Studio."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import islice
from pathlib import Path
from threading import Lock, Thread
import json
import re
import base64
import binascii
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree
import sys

from engine import Config, MATCH_LABELS, MODES, csv_config, fbc_voltage_comparison, identity, load_wafer, match_counts_by_voltage, voltage_text
from workbook_settings import workbook_config
from workbook_results import read_existing
from exports import AUDIT_COLUMNS, MAPS, VMIN_COLUMNS, batch_name, compare_order, save_report, test_headers
from pattern_reports import save_pattern_report

HERE = Path(__file__).resolve().parent
DEMO = HERE / "examples" / "sim128"
SETTINGS = HERE / "defaults.json"
PROFILES = HERE / "settings.local.json"
LOCK = Lock()
STATE = {"working": False, "message": "", "error": "", "output": [], "warnings": [], "wafer": None}


def get_settings():
    defaults = json.loads(SETTINGS.read_text(encoding="utf-8"))
    if PROFILES.exists():
        defaults.update(json.loads(PROFILES.read_text(encoding="utf-8")))
    return defaults


def save_settings(key, config):
    current = json.loads(PROFILES.read_text(encoding="utf-8")) if PROFILES.exists() else {}
    current[key] = config.json()
    tmp = PROFILES.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PROFILES)


def progress(message):
    with LOCK:
        STATE["message"] = message


def run_job(action, data):
    warnings, output = [], []
    wafer = None
    try:
        if action == "reopen":
            wafer, warnings = read_existing(Path(data["path"]), progress)
            progress("Rechecking Excel Address and FBC data")
            wafer.map_stats
        elif action == "pattern-export":
            wafer = data["wafer"]
            folder = Path(data["folder"])
            wt = wafer.wt_numbers.index(int(data["wt"]))
            chip = tuple(map(int, data["chip"]))
            blk = int(data["blk"])
            pattern = data["pattern"]
            if wafer.source_mode == "address" or chip not in wafer.chips or not 0 <= blk < 256:
                raise ValueError("Select a Chip and BLK with FBC data.")
            if pattern not in wafer.config.patterns:
                raise ValueError("Select an available Pattern.")
            progress(f"Exporting WT{wafer.wt_numbers[wt]} BLK {blk} · {pattern}")
            output.extend(map(str, save_pattern_report(wafer, folder, wt, chip, blk, pattern, data["kind"])))
        elif action == "export":
            wafer = data["wafer"]
            folder = Path(data["folder"]) if data.get("folder") else wafer.phases[0].source.path.parent
            kind = data.get("kind", "full")
            if kind not in {"full", "address", "fbc", "cat", "ppt", "monitor"}:
                raise ValueError("Unsupported export format.")
            if (wafer.source_mode != "full" and kind not in (wafer.source_mode, "cat")
                    or kind == "ppt" and not wafer.full):
                raise ValueError("Complete the full analysis or import the corresponding data first.")
            progress(f"Exporting {kind.upper()} report")
            selected = data.get("chip")
            chip = tuple(map(int, selected)) if kind == "full" and selected else None
            if chip is not None and chip not in wafer.chips:
                raise ValueError("The selected Chip is not in the current wafer.")
            if kind == "monitor":
                folder = folder / f"Analysis_{date.today():%Y%m%d}"
            output.append(str(save_report(wafer, folder, kind, chip=chip,
                                          monitor_chips=correlation_chips(data.get("chips"), wafer) if kind == "monitor" else None)))
        else:
            full = action == "analyze"
            config = Config.create(data["rows"], data.get("mode", "FBC0"), full=full, tail_bits=data.get("tail_bits"))
            paths = list(dict.fromkeys(Path(p).resolve() for p in data["paths"]))
            if not paths:
                raise ValueError("Select ASC files first.")
            groups = defaultdict(list)
            for path in paths:
                try:
                    source = identity(path)
                    groups[source.key].append(source)
                except ValueError as exc:
                    if full:
                        raise
                    warnings.append(str(exc))
            if full and len(groups) != 1:
                raise ValueError("Full analysis requires the same Lot/Wafer. Use batch export for multiple wafers.")
            for group in groups.values():
                try:
                    source_mode = data.get("source_mode", "full") if full else "full"
                    if source_mode not in ("full", "address", "fbc"):
                        raise ValueError("Invalid import mode.")
                    wafer = load_wafer(group, config, full=full, source_mode=source_mode, report=progress)
                    for row in wafer.manifest:
                        if row["missing"]:
                            warnings.append(f"{Path(row['path']).name} is missing TNO " + ", ".join(map(str, row["missing"])))
                        warnings.extend(f"{Path(row['path']).name} · {issue}" for issue in row["issues"])
                    if not full:
                        if any(phase.fbc_error for phase in wafer.phases):
                            raise ValueError("Invalid FBC format. Check the file diagnostics.")
                        folder = group[0].path.parent / f"Address_{date.today():%Y%m%d}"
                        progress(f"Exporting {wafer.label}")
                        output.append(str(save_report(wafer, folder, "batch", batch_name(wafer))))
                    elif source_mode == "full":
                        progress("Computing Wafer Maps, Address audit and Chip Vmin")
                        wafer.map_stats
                        wafer.all_vmin
                    elif source_mode == "fbc":
                        progress("Computing FBC Wafer Maps and Chip Vmin")
                        wafer.all_vmin
                except (OSError, ValueError) as exc:
                    if full:
                        raise
                    warnings.append(f"{group[0].label} · {exc}")
                    wafer = None
            if not full and not output:
                raise ValueError("No wafer was successfully exported in this batch.")
        with LOCK:
            STATE.update(working=False, message="Completed", output=output, warnings=warnings, error="")
            if action in ("analyze", "reopen"):
                STATE["wafer"] = wafer
    except Exception as exc:
        with LOCK:
            STATE.update(working=False, error=str(exc), output=output, warnings=warnings, message="Stopped")
        if not isinstance(exc, (OSError, ValueError)):
            import traceback
            traceback.print_exc()


def settings_import(path):
    return {"rows": csv_config(path), "mode": "FBC0"} if path.suffix.lower() == ".csv" else workbook_config(path)


def correlation_chips(raw, wafer):
    if raw is None:
        return None
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, list) or any(not isinstance(xy, list) or len(xy) != 2
            or any(type(v) is not int for v in xy) for xy in value):
        raise ValueError("Chip selection must be a list of integer X/Y pairs.")
    chips = list(dict.fromkeys(tuple(xy) for xy in value))
    if not set(chips).issubset(wafer.chips):
        raise ValueError("The selected Chip is not in the current wafer.")
    return chips


def view(wafer, query):
    get = query.get
    number = int(get("wt", wafer.wt_numbers[0]))
    if number not in wafer.wt_numbers:
        raise ValueError(f"No data imported for WT{number}.")
    wt = wafer.wt_numbers.index(number)
    kind = get("view", "map")
    pattern = get("pattern", next(iter(wafer.config.patterns), ""))
    if kind == "map":
        layer = get("layer", "fail")
        if (layer not in MAPS and layer not in ("vmin_pattern", "vmin_merge")) or (layer in ("fail", "wr", "loss", "vmin_pattern") and pattern not in wafer.config.patterns):
            raise ValueError("Invalid Map type or Pattern.")
        return wafer.map(wt, pattern, layer)
    chip = None
    if "x" in query and "y" in query:
        chip = int(get("x")), int(get("y"))
        if chip not in wafer.chips:
            raise ValueError("Chip coordinates do not exist.")
    if kind == "grid" and chip is not None:
        return wafer.grid(chip)
    if kind in ("vmin_distribution", "monitor_correlation"):
        scope = get("scope", "chip")
        patterns = wafer.config.patterns
        merge_available = {"scan", "march"} <= {name.casefold() for name in patterns}
        if not (scope == "chip" or (scope == "merge" and merge_available)
                or (scope.startswith("pattern:") and scope.removeprefix("pattern:") in patterns)):
            raise ValueError("Invalid Vmin scope.")
        if kind == "monitor_correlation":
            if scope not in wafer.monitor_scopes:
                raise ValueError("Select Scan, March or Scan & March.")
            return wafer.monitor_correlation(wt, scope, chips=correlation_chips(get("chips"), wafer))
        if chip is None:
            raise ValueError("Select a Chip first.")
        return wafer.vmin_distribution(wt, chip, scope, with_matches=get("matches") == "1")
    if kind == "detail" and chip is not None:
        blk = int(get("blk"))
        if not 0 <= blk < 256:
            raise ValueError("BLK must be between 0 and 255.")
        detail = wafer.detail(wt, chip, blk)
        detail["addresses"] = []
        detail["wr_matches"] = {"labels": MATCH_LABELS, "patterns": {}}
        detail["voltage_comparisons"] = []
        covered_patterns = set()
        for name, scope in wafer.config.patterns.items():
            if name not in covered_patterns:
                comparison = fbc_voltage_comparison(detail["sweep"], name)
                detail["voltage_comparisons"].append(comparison)
                covered_patterns.update(comparison["patterns"])
            matches = list(wafer.pattern_matches(wt, chip, blk, scope))
            detail["addresses"].extend(row | {"pattern": name} for row in matches)
            detail["wr_matches"]["patterns"][name] = match_counts_by_voltage(scope, matches)
        return detail
    if kind == "audit":
        headers = list(AUDIT_COLUMNS.values())
        source = ([row[k] for k in AUDIT_COLUMNS] for row in wafer.audit()
                  if row["wt"] == number and (not pattern or row["pattern"] == pattern)
                  and (chip is None or (row["x"], row["y"]) == chip))
    elif kind == "address":
        headers = ["X", "Y", "BLK", "WL", "BL", "IO", "Cat.", *test_headers(wafer)]
        source = ((*row[:7], *(1 if test.tno in flags else None for flags in row[7] for test in wafer.config.tests))
                  for row in wafer.address_rows(chip))
    elif kind == "fbc":
        headers = ["X", "Y", "BLK", *test_headers(wafer, True)]
        order = compare_order(wafer)
        source = ((*row[:3], *(row[i] for i in order)) for row in wafer.fbc_rows(chip))
    elif kind == "vmin":
        headers = ["X", "Y", *VMIN_COLUMNS.values()]
        source = ((*xy, *(f"≥ {voltage_text(result[k])}" if k == "voltage" and result.get("relation") == ">=" else result[k] for k in VMIN_COLUMNS)) for (p, xy), result in wafer.all_vmin.items()
                  if p == wt and (chip is None or chip == xy))
    else:
        raise ValueError("View does not exist.")
    page = max(0, int(get("page", "0")))
    highlighted = None
    if kind == "address" and get("target") and chip is not None:
        target = tuple(int(n) for n in get("target").split(","))
        source_row = next((i for i, row in enumerate(wafer.address_rows(chip)) if row[2:6] == target), None)
        if source_row is None:
            raise ValueError("No matching Fail Address row found.")
        page, highlighted = divmod(source_row, 100)
    rows = list(islice(source, page * 100, page * 100 + 101))
    return {"headers": headers, "rows": rows[:100], "more": len(rows) > 100,
            "page": page, "highlighted": highlighted}


def chart_image_bytes(data):
    kind = data.get("format")
    content = data.get("content")
    if kind not in ("svg", "png") or not isinstance(content, str) or len(content) > 48 * 1024 * 1024:
        raise ValueError("Invalid chart image format or size.")
    if kind == "svg":
        payload = content.encode("utf-8")
        try:
            if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
                raise ValueError("Unsupported SVG document.")
            root = ElementTree.fromstring(payload)
            if root.tag != "{http://www.w3.org/2000/svg}svg":
                raise ValueError("Invalid SVG image.")
        except ElementTree.ParseError as exc:
            raise ValueError("Invalid SVG image.") from exc
    else:
        try:
            payload = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid PNG image.") from exc
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid PNG image.")
    if len(payload) > 32 * 1024 * 1024:
        raise ValueError("Chart image exceeds 32 MiB.")
    return payload


class DesktopAPI:
    def __init__(self):
        self._window = None

    def request(self, action, data):
        """Dispatch operations from the desktop page over the native JS bridge."""
        try:
            if action == "status":
                with LOCK:
                    result = {k: v for k, v in STATE.items() if k != "wafer"}
                    wafer = STATE["wafer"]
                    result["data"] = None if wafer is None else {
                        "label": wafer.label, "chips": len(wafer.chips), "phases": len(wafer.phases),
                        "wt_numbers": wafer.wt_numbers,
                        "patterns": list(wafer.config.patterns), "mode": wafer.config.mode,
                        "tail_bits": wafer.config.json()["tail_bits"],
                        "monitor_scopes": wafer.monitor_scopes,
                        "source_mode": wafer.source_mode, "manifest": wafer.manifest}
                return result
            if action == "settings":
                with LOCK:
                    return {"settings": get_settings(), "modes": MODES}
            if action == "view":
                with LOCK:
                    wafer = STATE["wafer"]
                    if wafer is None:
                        raise ValueError("Run analysis first.")
                    return view(wafer, data)
            if action == "save-chart":
                return self._save_chart(data)
            if action == "pick":
                return self._pick(data["kind"])
            if action == "demo":
                return {"paths": [str(DEMO / f"SIM128_WT{i}.asc") for i in range(1, 4)],
                        "config": {"mode": data.get("mode", "FBC0"),
                                   "rows": csv_config(DEMO / "Config_TNO.csv")}}
            if action == "save-settings":
                key = data["profile"]
                if key not in ("full", "batch"):
                    raise ValueError("Invalid configuration type.")
                config = Config.create(data["rows"], data["mode"], full=key == "full", tail_bits=data.get("tail_bits"))
                with LOCK:
                    save_settings(key, config)
                return config.json()
            if action not in ("analyze", "batch", "export", "reopen", "pattern-export"):
                raise ValueError("Unknown operation.")
            with LOCK:
                if STATE["working"]:
                    raise ValueError("The previous job is still running.")
                if action in ("export", "pattern-export"):
                    data["wafer"] = STATE["wafer"]
                    if data["wafer"] is None:
                        raise ValueError("Run analysis first.")
                STATE.update(working=True, message="Preparing data", error="", output=[], warnings=[])
            Thread(target=run_job, args=(action, data), daemon=True).start()
            return {"started": True}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"bridge_error": str(exc)}

    def _save_chart(self, data):
        from webview import FileDialog

        payload = chart_image_bytes(data)
        kind = data["format"]
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(data.get("filename") or "Chart"))[:160]
        filename = str(Path(filename).with_suffix("." + kind))
        chosen = self._window.create_file_dialog(FileDialog.SAVE, save_filename=filename,
                                                  file_types=(f"{kind.upper()} image (*.{kind})",))
        if not chosen:
            return {"cancelled": True}
        path = Path(chosen if isinstance(chosen, str) else chosen[0]).with_suffix("." + kind)
        draft = None
        try:
            with NamedTemporaryFile(dir=path.parent, prefix=".sram-chart-", delete=False) as stream:
                draft = Path(stream.name)
                stream.write(payload)
            draft.replace(path)
        finally:
            if draft is not None:
                draft.unlink(missing_ok=True)
        return {"path": str(path), "cancelled": False}

    def _pick(self, kind):
        from webview import FileDialog

        if kind == "folder":
            paths = self._window.create_file_dialog(FileDialog.FOLDER)
        elif kind == "asc":
            paths = self._window.create_file_dialog(FileDialog.OPEN, allow_multiple=True,
                                                    file_types=("ASC Raw Data (*.asc)",))
        elif kind in ("settings", "report"):
            types = ("Excel / CSV (*.xlsx;*.xlsm;*.csv)",) if kind == "settings" else ("Excel (*.xlsx;*.xlsm)",)
            paths = self._window.create_file_dialog(FileDialog.OPEN, file_types=types)
        else:
            raise ValueError("Unsupported file picker type.")
        paths = list(paths or ())
        return {"paths": paths, "config": settings_import(Path(paths[0])) if kind == "settings" and paths else None}


def desktop_html():
    assets = HERE / "web"
    page = (assets / "index.html").read_text(encoding="utf-8")
    style = (assets / "style.css").read_text(encoding="utf-8")
    script = (assets / "app.js").read_text(encoding="utf-8")
    return page.replace("<!-- APP_STYLE -->", f"<style>{style}</style>").replace(
        "<!-- APP_SCRIPT -->", f"<script>{script}</script>")


def main():
    import webview

    api = DesktopAPI()
    api._window = webview.create_window("SRAM Wafer Studio", html=desktop_html(), js_api=api,
                                        width=1440, height=900, min_size=(760, 600), maximized=True)
    webview.start(gui="edgechromium", http_server=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if sys.stderr is not None:
            raise
        from ctypes import windll

        windll.user32.MessageBoxW(0, f"Unable to start SRAM Wafer Studio. Check that Microsoft Edge WebView2 Runtime is installed.\n\n{error}",
                                  "SRAM Wafer Studio", 0x10)
        raise SystemExit(1)
