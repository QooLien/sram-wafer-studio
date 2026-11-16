
"""Desktop window and local data operations for SRAM Wafer Studio."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import islice
from pathlib import Path
from threading import Lock, Thread
import json
import sys

from engine import Config, MATCH_LABELS, MODES, csv_config, identity, load_wafer, match_counts_by_voltage
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
            progress("重新核對 Excel 的 Address 與 FBC")
            wafer.map_stats
        elif action == "pattern-export":
            wafer = data["wafer"]
            folder = Path(data["folder"])
            wt = wafer.wt_numbers.index(int(data["wt"]))
            chip = tuple(map(int, data["chip"]))
            blk = int(data["blk"])
            pattern = data["pattern"]
            if wafer.source_mode == "address" or chip not in wafer.chips or not 0 <= blk < 256:
                raise ValueError("請選取具有 FBC 的 Chip 與 BLK。")
            if pattern not in wafer.config.patterns:
                raise ValueError("請選取可用的 Pattern。")
            progress(f"匯出 WT{wafer.wt_numbers[wt]} BLK {blk} · {pattern}")
            output.extend(map(str, save_pattern_report(wafer, folder, wt, chip, blk, pattern, data["kind"])))
        elif action == "export":
            wafer = data["wafer"]
            folder = Path(data["folder"]) if data.get("folder") else wafer.phases[0].source.path.parent
            kind = data.get("kind", "full")
            if kind not in {"full", "address", "fbc", "cat", "ppt"}:
                raise ValueError("不支援的匯出格式。")
            if (wafer.source_mode != "full" and kind not in (wafer.source_mode, "cat")
                    or kind == "ppt" and not wafer.full):
                raise ValueError("請先完成完整分析或對應資料的匯入。")
            progress(f"匯出 {kind.upper()} 報表")
            selected = data.get("chip")
            chip = tuple(map(int, selected)) if kind == "full" and selected else None
            if chip is not None and chip not in wafer.chips:
                raise ValueError("選取的 Chip 不在目前的 wafer。")
            output.append(str(save_report(wafer, folder, kind, chip=chip)))
        else:
            full = action == "analyze"
            config = Config.create(data["rows"], data.get("mode", "FBC0"), full=full)
            paths = list(dict.fromkeys(Path(p).resolve() for p in data["paths"]))
            if not paths:
                raise ValueError("請先選取 ASC 檔案。")
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
                raise ValueError("完整分析需選同一 Lot／Wafer，跨批請使用批次匯出。")
            for group in groups.values():
                try:
                    source_mode = data.get("source_mode", "full") if full else "full"
                    if source_mode not in ("full", "address", "fbc"):
                        raise ValueError("匯入模式無效。")
                    wafer = load_wafer(group, config, full=full, source_mode=source_mode, report=progress)
                    for row in wafer.manifest:
                        if row["missing"]:
                            warnings.append(f"{Path(row['path']).name} 缺少 TNO " + ", ".join(map(str, row["missing"])))
                        warnings.extend(f"{Path(row['path']).name} · {issue}" for issue in row["issues"])
                    if not full:
                        if any(phase.fbc_error for phase in wafer.phases):
                            raise ValueError("FBC 格式有誤，請檢查個別檔案診斷。")
                        folder = group[0].path.parent / f"Address_{date.today():%Y%m%d}"
                        progress(f"匯出 {wafer.label}")
                        output.append(str(save_report(wafer, folder, "batch", batch_name(wafer))))
                    elif source_mode == "full":
                        progress("計算 Wafer Map、Address 核對和 Chip Vmin")
                        wafer.map_stats
                        wafer.all_vmin
                    elif source_mode == "fbc":
                        progress("計算 FBC Wafer Map 與 Chip Vmin")
                        wafer.all_vmin
                except (OSError, ValueError) as exc:
                    if full:
                        raise
                    warnings.append(f"{group[0].label} · {exc}")
                    wafer = None
            if not full and not output:
                raise ValueError("本批次沒有成功匯出的 wafer。")
        with LOCK:
            STATE.update(working=False, message="作業完成", output=output, warnings=warnings, error="")
            if action in ("analyze", "reopen"):
                STATE["wafer"] = wafer
    except Exception as exc:
        with LOCK:
            STATE.update(working=False, error=str(exc), output=output, warnings=warnings, message="作業停止")
        if not isinstance(exc, (OSError, ValueError)):
            import traceback
            traceback.print_exc()


def settings_import(path):
    return {"rows": csv_config(path), "mode": "FBC0"} if path.suffix.lower() == ".csv" else workbook_config(path)


def view(wafer, query):
    get = query.get
    number = int(get("wt", wafer.wt_numbers[0]))
    if number not in wafer.wt_numbers:
        raise ValueError(f"尚未匯入 WT{number} 的資料。")
    wt = wafer.wt_numbers.index(number)
    kind = get("view", "map")
    pattern = get("pattern", next(iter(wafer.config.patterns), ""))
    if kind == "map":
        layer = get("layer", "fail")
        if layer not in MAPS or (layer in ("fail", "wr", "loss") and pattern not in wafer.config.patterns):
            raise ValueError("Map 類型或 Pattern 無效。")
        return wafer.map(wt, pattern, layer)
    chip = None
    if "x" in query and "y" in query:
        chip = int(get("x")), int(get("y"))
        if chip not in wafer.chips:
            raise ValueError("Chip 座標不存在。")
    if kind == "grid" and chip is not None:
        return wafer.grid(chip)
    if kind == "detail" and chip is not None:
        blk = int(get("blk"))
        if not 0 <= blk < 256:
            raise ValueError("BLK 必須在 0～255。")
        detail = wafer.detail(wt, chip, blk)
        detail["addresses"] = []
        detail["wr_matches"] = {"labels": MATCH_LABELS, "patterns": {}}
        for name, scope in wafer.config.patterns.items():
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
        source = ((*xy, *(result[k] for k in VMIN_COLUMNS)) for (p, xy), result in wafer.all_vmin.items()
                  if p == wt and (chip is None or chip == xy))
    else:
        raise ValueError("檢視不存在。")
    page = max(0, int(get("page", "0")))
    highlighted = None
    if kind == "address" and get("target") and chip is not None:
        target = tuple(int(n) for n in get("target").split(","))
        source_row = next((i for i, row in enumerate(wafer.address_rows(chip)) if row[2:6] == target), None)
        if source_row is None:
            raise ValueError("找不到對應的 Fail Address 列。")
        page, highlighted = divmod(source_row, 100)
    rows = list(islice(source, page * 100, page * 100 + 101))
    return {"headers": headers, "rows": rows[:100], "more": len(rows) > 100,
            "page": page, "highlighted": highlighted}


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
                        "source_mode": wafer.source_mode, "manifest": wafer.manifest}
                return result
            if action == "settings":
                with LOCK:
                    return {"settings": get_settings(), "modes": MODES}
            if action == "view":
                with LOCK:
                    wafer = STATE["wafer"]
                    if wafer is None:
                        raise ValueError("請先執行分析。")
                    return view(wafer, data)
            if action == "pick":
                return self._pick(data["kind"])
            if action == "demo":
                return {"paths": [str(DEMO / f"SIM128_WT{i}.asc") for i in range(1, 4)],
                        "config": {"mode": data.get("mode", "FBC0"),
                                   "rows": csv_config(DEMO / "Config_TNO.csv")}}
            if action == "save-settings":
                key = data["profile"]
                if key not in ("full", "batch"):
                    raise ValueError("設定類型無效。")
                config = Config.create(data["rows"], data["mode"], full=key == "full")
                with LOCK:
                    save_settings(key, config)
                return config.json()
            if action not in ("analyze", "batch", "export", "reopen", "pattern-export"):
                raise ValueError("找不到此操作。")
            with LOCK:
                if STATE["working"]:
                    raise ValueError("前一項作業仍在執行。")
                if action in ("export", "pattern-export"):
                    data["wafer"] = STATE["wafer"]
                    if data["wafer"] is None:
                        raise ValueError("請先執行分析。")
                STATE.update(working=True, message="準備資料", error="", output=[], warnings=[])
            Thread(target=run_job, args=(action, data), daemon=True).start()
            return {"started": True}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"bridge_error": str(exc)}

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
            raise ValueError("不支援的檔案選擇方式。")
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

        windll.user32.MessageBoxW(0, f"無法啟動 SRAM Wafer Studio。請確認已安裝 Microsoft Edge WebView2 Runtime。\n\n{error}",
                                  "SRAM Wafer Studio", 0x10)
        raise SystemExit(1)
