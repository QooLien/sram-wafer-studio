
"""Local-only launcher and HTTP interface for SRAM Wafer Studio."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import islice
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock, Thread
from urllib.parse import parse_qs, urlparse
import argparse
import json
import os
import subprocess
import sys
import webbrowser

from engine import Config, MODES, csv_config, identity, load_wafer
from workbook_settings import workbook_config
from workbook_results import read_existing
from exports import AUDIT_COLUMNS, MAPS, VMIN_COLUMNS, batch_name, compare_order, save_report, test_headers

HERE = Path(__file__).resolve().parent
DEMO = HERE / "examples" / "sim128"
SETTINGS = HERE / "defaults.json"
PROFILES = HERE / "settings.local.json"
TOKEN = token_urlsafe(24)
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


def choose_files(kind):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "asc":
            return list(filedialog.askopenfilenames(parent=root, title="選取 ASC Raw Data",
                                                   filetypes=[("ASC Raw Data", "*.asc")]))
        if kind in ("settings", "report"):
            title = "匯入測試設定" if kind == "settings" else "開啟既有分析結果"
            pattern = "*.xlsx *.xlsm *.csv" if kind == "settings" else "*.xlsx *.xlsm"
            path = filedialog.askopenfilename(parent=root, title=title, filetypes=[("Excel／CSV", pattern)])
            return [path] if path else []
        path = filedialog.askdirectory(parent=root, title="選擇匯出資料夾", mustexist=True)
        return [path] if path else []
    finally:
        root.destroy()


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
    def get(key, default=""):
        return query.get(key, [default])[0]

    wt = int(get("wt", "1")) - 1
    if not 0 <= wt < len(wafer.phases):
        raise ValueError("WT 超出範圍。")
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
        for name, scope in wafer.config.patterns.items():
            for row in wafer.address_info(wt, chip, blk, scope):
                detail["addresses"].append(row | {"pattern": name})
        return detail
    if kind == "audit":
        headers = list(AUDIT_COLUMNS.values())
        source = ([row[k] for k in AUDIT_COLUMNS] for row in wafer.audit()
                  if row["wt"] == wt + 1 and (not pattern or row["pattern"] == pattern)
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


class App(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def authorized_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.authorized_host():
            return self.respond({"error": "Local access only"}, 403)
        route = urlparse(self.path)
        try:
            files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                     "/style.css": ("style.css", "text/css")}
            if route.path in files:
                name, mime = files[route.path]
                payload = (HERE / "web" / name).read_bytes().replace(b"__TOKEN__", TOKEN.encode()) if name == "index.html" else (
                    HERE / "web" / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", f"{mime}; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.headers.get("X-SRAM-Token") != TOKEN:
                return self.respond({"error": "Invalid session"}, 403)
            if route.path == "/api/status":
                with LOCK:
                    result = {k: v for k, v in STATE.items() if k != "wafer"}
                    wafer = STATE["wafer"]
                result["data"] = None if wafer is None else {
                    "label": wafer.label, "chips": len(wafer.chips), "phases": len(wafer.phases),
                    "patterns": list(wafer.config.patterns), "mode": wafer.config.mode,
                    "source_mode": wafer.source_mode, "manifest": wafer.manifest}
                return self.respond(result)
            if route.path == "/api/settings":
                return self.respond({"settings": get_settings(), "modes": MODES})
            if route.path == "/api/view":
                with LOCK:
                    wafer = STATE["wafer"]
                if wafer is None:
                    raise ValueError("請先執行分析。")
                return self.respond(view(wafer, parse_qs(route.query, keep_blank_values=True)))
            return self.respond({"error": "頁面不存在"}, 404)
        except (OSError, ValueError, KeyError) as exc:
            self.respond({"error": str(exc)}, 400)

    def do_POST(self):
        if (not self.authorized_host() or self.headers.get("X-SRAM-Token") != TOKEN
                or self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}")):
            return self.respond({"error": "Invalid session"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("設定內容格式或大小不符。")
            data = json.loads(self.rfile.read(length))
            path = urlparse(self.path).path
            if path == "/api/pick":
                kind = data["kind"]
                if kind not in ("asc", "settings", "report", "folder"):
                    raise ValueError("不支援的檔案選擇方式。")
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--pick", kind],
                                        check=True, capture_output=True, encoding="utf-8",
                                        env=os.environ | {"PYTHONIOENCODING": "utf-8"})
                paths = json.loads(result.stdout)
                return self.respond({"paths": paths, "config": settings_import(Path(paths[0]))
                                    if kind == "settings" and paths else None})
            if path == "/api/demo":
                return self.respond({"paths": [str(DEMO / f"SIM128_WT{i}.asc") for i in range(1, 4)],
                                     "config": {"mode": data.get("mode", "FBC0"),
                                                "rows": csv_config(DEMO / "Config_TNO.csv")}})
            if path == "/api/save-settings":
                key = data["profile"]
                if key not in ("full", "batch"):
                    raise ValueError("設定類型無效。")
                config = Config.create(data["rows"], data["mode"], full=key == "full")
                save_settings(key, config)
                return self.respond(config.json())
            jobs = {"/api/analyze": "analyze", "/api/batch": "batch", "/api/export": "export", "/api/reopen": "reopen"}
            if path not in jobs:
                return self.respond({"error": "找不到此操作"}, 404)
            with LOCK:
                if STATE["working"]:
                    return self.respond({"error": "前一項作業仍在執行。"}, 409)
                if path == "/api/export":
                    data["wafer"] = STATE["wafer"]
                    if data["wafer"] is None:
                        raise ValueError("請先執行分析。")
                STATE.update(working=True, message="準備資料", error="", output=[], warnings=[])
            Thread(target=run_job, args=(jobs[path], data), daemon=True).start()
            self.respond({"started": True}, 202)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            self.respond({"error": str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--pick", choices=["asc", "settings", "report", "folder"])
    args = parser.parse_args()
    if args.pick:
        print(json.dumps(choose_files(args.pick)))
        return
    get_settings()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), App)
    except OSError:
        if args.no_browser:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), App)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"SRAM Wafer Studio  {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        with server:
            server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
