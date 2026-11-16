
"""Excel and PowerPoint outputs from the same report model used by the UI."""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from engine import MODES


MAPS = {"fail": "Fail BLK", "wr": "W&R", "loss": "Fail BLK / Loss", "cat": "Cat Wafer Map",
        "repair": "BL=0 Failure Analysis", "vmin": "Chip Vmin Map"}
CAT_COLORS = {1: "#c6efce", 2: "#c6efce", 3: "#bdd7ee", 4: "#bdd7ee", 9: "#ff9999",
              10: "#bfbfbf", 11: "#bfbfbf", 12: "#dbaddb", 13: "#dbaddb", 14: "#ffd966",
              15: "#d9d2e9", 16: "#d9d2e9", 17: "#d9d2e9", 18: "#ffe699", 19: "#9bc2e6",
              20: "#bfbfbf", **dict.fromkeys(range(5, 9), "#f8cbad")}
AUDIT_COLUMNS = {"wt": "WT", "pattern": "Pattern", "tno": "Stop TNO", "x": "X", "y": "Y", "blk": "BLK",
                 "fbc": "FBC", "recorded": "Endpoint Address Count", "gap": "Endpoint Missing Count",
                 "finding": "Finding", "total": "Pattern Address Count", "basis": "Coverage Basis",
                 "endpoint": "Endpoint Finding", "w": "Write only", "r": "Read only", "wr": "Write & Read",
                 "none": "No Monitor"}
VMIN_COLUMNS = {"status": "Status", "voltage": "Vmin (V)", "blk": "BLK", "tno": "TNO", "func": "Func.",
                "pattern": "Pattern", "cutoff": "Tail cutoff", "tail": "Tail BLKs", "hard": "Hard Fail BLKs",
                "prior": "Prior WT excluded", "remaining": "Remaining BLKs", "incomplete": "Incomplete BLKs"}


def test_headers(wafer, comparison=False):
    if comparison:
        return [f"WT{wt} | {t.label} [{t.tno}]" for group in ("Monitor", "Function")
                for wt in range(1, len(wafer.phases) + 1) for t in wafer.config.tests if t.group == group]
    return [f"WT{wt} | {t.label} [{t.tno}]" for wt in range(1, len(wafer.phases) + 1)
            for t in wafer.config.tests]


def compare_order(wafer):
    count = len(wafer.config.tests)
    return [3 + wt * count + i for group in ("Monitor", "Function")
            for wt in range(len(wafer.phases)) for i, t in enumerate(wafer.config.tests) if t.group == group]


def batch_name(wafer):
    claimed = {}
    unlabeled = []
    for phase in wafer.phases:
        raw = phase.source
        if raw.source_wt is None:
            unlabeled.append(raw.version)
        elif raw.source_wt in claimed:
            raise ValueError(f"{wafer.label} 有重複的 ASC 檔名 WT 標記。")
        else:
            claimed[raw.source_wt] = raw.version
    for version in unlabeled:
        claimed[next(wt for wt in (1, 2, 3) if wt not in claimed)] = version
    if len(set(claimed.values())) == 1:
        suffix = "-".join(f"WT{i}" for i in sorted(claimed)) + f"_Ver{next(iter(claimed.values()))}"
    else:
        suffix = "_".join(f"WT{i}_Ver{claimed[i]}" for i in sorted(claimed))
    return f"{wafer.label}_{suffix}_{date.today():%Y%m%d}"


def output_path(folder, stem, extension):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(". ")
    candidate = folder / f"{stem}.{extension}"
    number = 1
    while candidate.exists():
        candidate = folder / f"{stem}_{number:03}.{extension}"
        number += 1
    return candidate


def cell_style(data, kind):
    val = data["value"]
    if kind in ("cat", "repair"):
        return [str(val) if val else "—"], [CAT_COLORS.get(val, "#f1f5f9")]
    if kind == "vmin":
        return [format(val, ".3f").rstrip("0").rstrip(".") if val is not None else data["status"]], [
            "#f8cbad" if val is not None else "#dbeafe" if data["status"] == "Pass" else "#e2e8f0"]
    if data.get("blue"):
        return [""], ["#00b0f0"]
    if data.get("gray"):
        return [""], ["#808080"]
    if kind == "wr":
        return [str(n) if n else "" for n in data["wr"]], [
            c if n else "#ffffff" for n, c in zip(data["wr"], ("#ffffff", "#ffd966", "#ff6600", "#ffffff"))]
    if kind == "loss":
        return [str(n) if n else "" for n in (val, data["loss"])], [
            "#ffffff", "#ff433c" if data["loss"] else "#ffffff"]
    color = "#bf8f00" if val is not None and val >= 50 else "#ffd966" if val and val >= 20 else (
        "#ffe699" if val and val >= 10 else "#fff2cc" if val else "#ffffff")
    return [str(val) if val else ""], [color]


def raster_map(wafer, wt, pattern, kind):
    from PIL import Image, ImageDraw, ImageFont

    data = wafer.map(wt, pattern, kind)
    x0, x1 = min(r["x"] for r in data), max(r["x"] for r in data)
    y0, y1 = min(r["y"] for r in data), max(r["y"] for r in data)
    if max(x1 - x0, y1 - y0) > 99:
        raise ValueError("Wafer Map 座標範圍超過 100。")
    size, axis, top = 72, 42, 78
    width, height = axis + (x1 - x0 + 1) * size + 3, top + (y1 - y0 + 1) * size + 3
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("arial.ttf", 22)
    minor = ImageFont.truetype("arial.ttf", 15)
    slope = [t.voltage for t in wafer.config.patterns.get(pattern, ()) if t.voltage is not None]
    label = f"WT{wt + 1} {wafer.label}"
    if kind == "fail" and slope:
        label += f" {max(slope):.3g}v~{min(slope):.3g}v"
        if any("retention" in t.name.lower() for t in wafer.config.patterns[pattern]):
            label += ",DR"
    title = f"{label} {pattern or ''} {MAPS[kind]}".replace("  ", " ")
    draw.rectangle((0, 0, width, 43), fill="#e4edf6")
    while draw.textlength(title, font=font) > width - 8 and font.size > 6:
        font = ImageFont.truetype("arial.ttf", font.size - 1)
    draw.text((width / 2, 21), title, font=font, fill="#16304a", anchor="mm")
    for x in range(x0, x1 + 1):
        draw.text((axis + (x - x0 + .5) * size, 59), str(x), font=minor, fill="#667788", anchor="mm")
    for y in range(y0, y1 + 1):
        draw.text((axis / 2, top + (y - y0 + .5) * size), str(y), font=minor, fill="#667788", anchor="mm")
    for row in data:
        texts, colors = cell_style(row, kind)
        left, upper = axis + (row["x"] - x0) * size, top + (row["y"] - y0) * size
        cols, rows = (2, 2) if len(texts) == 4 else (2, 1) if len(texts) == 2 else (1, 1)
        cw, rh = size / cols, size / rows
        for i, (value, color) in enumerate(zip(texts, colors)):
            x, y = left + i % cols * cw, upper + i // cols * rh
            draw.rectangle((x, y, x + cw, y + rh), fill=color, outline="#b6c2ce")
            local_font = minor
            if draw.textlength(value, font=minor) > cw - 4:
                local_font = ImageFont.truetype("arial.ttf", 10)
            draw.text((x + cw / 2, y + rh / 2), value, font=local_font,
                      fill="white" if color == "#ff433c" else "#929292" if len(texts) == 4 and i == 3 else "#122034",
                      anchor="mm")
        draw.rectangle((left, upper, left + size, upper + size), outline="#42546a", width=2)
    return image


def image_bytes(image):
    data = BytesIO()
    image.save(data, "PNG")
    data.seek(0)
    return data


def write_ppt(wafer, path):
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Cm

    panels = [(wt, name) for wt in range(len(wafer.phases)) for name in wafer.config.patterns]
    if not panels:
        raise ValueError("PPT 匯出需要 Pattern。")
    count = [raster_map(wafer, wt, name, "fail") for wt, name in panels]
    quadrants = [raster_map(wafer, wt, name, "wr") for wt, name in panels]
    loss = [raster_map(wafer, wt, name, "loss") for wt, name in panels]
    width, height = count[0].size
    small = (width * 2 // 5, height * 2 // 5)
    combined = Image.new("RGB", (width * len(panels), height * 2 + small[1]), "white")
    for i, (a, b, c) in enumerate(zip(count, quadrants, loss)):
        x = width * i
        combined.paste(a, (x, 0))
        combined.paste(b, (x, height))
        combined.paste(c.resize(small, Image.Resampling.LANCZOS), (x + width - small[0], height * 2))
    deck = Presentation()
    deck.slide_width = Cm(37.4)
    picture_height = 37 * combined.height / combined.width
    deck.slide_height = Cm(max(5, picture_height + 0.4))
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_picture(image_bytes(combined), Cm(.2), Cm(.2), width=Cm(37))
    deck.save(path)


def write_excel(wafer, path, report_mode="full", *, chip=None):
    import xlsxwriter

    with xlsxwriter.Workbook(path, {"constant_memory": True, "strings_to_formulas": False,
                                    "strings_to_urls": False}) as book:
        head = book.add_format({"bg_color": "#17324d", "font_color": "#ffffff", "bold": True,
                                "align": "center", "valign": "vcenter", "text_wrap": True})

        phase_colors = ("#dbeafe", "#ffedd5", "#dcfce7")
        style = {"font_name": "Calibri", "font_size": 11, "font_color": "#17324d",
                 "align": "center", "valign": "vcenter"}
        phase_headers = [book.add_format(style | {"bg_color": color, "bold": True, "border": 1,
                                                      "border_color": "#aabccf"}) for color in phase_colors]
        phase_tall = [book.add_format(style | {"bg_color": color, "bold": True, "border": 1,
                                                   "border_color": "#aabccf", "rotation": 90,
                                                   "text_wrap": True}) for color in phase_colors]
        phase_flags = [book.add_format({"bg_color": color}) for color in phase_colors]
        mid = book.add_format(style)
        zero_hidden = book.add_format(style | {"num_format": "0;-0;;@"})
        grid = book.add_format(style | {"border": 1, "border_color": "#d3dee8"})
        title = book.add_format(style | {"bg_color": "#17324d", "font_color": "#ffffff",
                                              "font_size": 13, "bold": True})
        info = book.add_format(style | {"align": "left", "text_wrap": True})
        axis = book.add_format(style | {"font_name": "Arial", "font_size": 9, "font_color": "#697a8c"})
        link = book.add_format(style | {"bg_color": "#e6eef6", "font_color": "#174f76",
                                             "underline": 1, "bold": True, "text_wrap": True})
        cat_fmt = book.add_format(style | {"num_format": '"C"0', "border": 1, "border_color": "#d3dee8"})
        voltage = book.add_format(style | {"num_format": "0.00#", "border": 1, "border_color": "#d3dee8"})
        boundary = ("left", "right", "top", "bottom")
        fill_formats = {}

        def worksheet(name):
            ws = book.add_worksheet(name)
            ws.hide_gridlines(2)
            ws.set_default_row(17)
            return ws

        def new_table(name, cols, header_row=0):
            ws = worksheet(name)
            ws.freeze_panes(header_row + 1, 0)
            ws.set_column(0, len(cols) - 1, 17, mid)
            ws.set_row(header_row, 32)
            ws.write_row(header_row, 0, cols, head)
            return ws

        def write_rows(ws, rows, first=1, return_rows=False):
            row_numbers = {}
            last = first - 1
            for last, row in enumerate(rows, first):
                if last >= 1_048_576:
                    raise ValueError(f"{ws.name} 超過 Excel 的列數上限。")
                ws.write_row(last, 0, row)
                if return_rows:
                    row_numbers[tuple(row[:6])] = last + 1
            return last, row_numbers

        def table(name, cols, values):
            ws = new_table(name, cols)
            last, _ = write_rows(ws, values)
            ws.autofilter(0, 0, last, len(cols) - 1)

        def band(ws, row, c0, c1, value, fmt):
            if c0 == c1:
                ws.write(row, c0, value, fmt)
            else:
                ws.merge_range(row, c0, row, c1, value, fmt)

        def config_sheet():
            ws = worksheet("Config")
            ws.freeze_panes(1, 0)
            ws.set_tab_color("#52748e")
            ws.set_row(0, 27)
            ws.set_column("A:A", 16, grid)
            ws.set_column("B:B", 21, grid)
            ws.set_column("C:C", 15, voltage)
            ws.set_column("D:D", 16, grid)
            ws.set_column("E:E", 23, grid)
            ws.set_column("F:F", 15, voltage)
            ws.set_column("G:G", 12, cat_fmt)
            ws.set_column("H:H", 15, grid)
            ws.set_column("I:J", 13, mid)
            ws.write_row(0, 0, ("TNO (Monitor)", "Func.", "Test Voltage", "TNO (Function)",
                                "Func.", "Test Voltage", "Fail Cat.", "Stop Sign", "Vmin Mode"), head)
            ws.write_string(0, 9, wafer.config.mode, phase_headers[0])
            groups = [[t for t in wafer.config.tests if t.group == g] for g in ("Monitor", "Function")]
            for row in range(max(map(len, groups))):
                if row < len(groups[0]):
                    test = groups[0][row]
                    ws.write_row(row + 1, 0, (test.tno, test.name, test.voltage))
                if row < len(groups[1]):
                    test = groups[1][row]
                    ws.write_row(row + 1, 3, (test.tno, test.name, test.voltage, test.cat, test.stop or None))
            ws.data_validation("J1", {"validate": "list", "source": list(MODES)})

        def address_sheet():
            ws = worksheet("Fail Address")
            ntests = len(wafer.config.tests)
            width = 7 + ntests * len(wafer.phases)
            ws.freeze_panes(1, 7)
            ws.set_column(0, 6, 8, grid)
            ws.set_column(7, width - 1, 6, grid)
            ws.set_row(0, 134)
            ws.write_row(0, 0, ("X", "Y", "BLK", "WL", "BL", "IO", "Cat."), head)
            headers = test_headers(wafer)
            for wt in range(len(wafer.phases)):
                first = 7 + wt * ntests
                for i, test in enumerate(wafer.config.tests):
                    label = f"WT{wt + 1}\n{test.label}" if report_mode == "full" else headers[wt * ntests + i]
                    ws.write(0, first + i, label, phase_tall[wt])
                    ws.write_comment(0, first + i, f"WT{wt + 1} | {test.group} | TNO={test.tno}",
                                     {"author": "SRAM Wafer Studio"})
            last, row_numbers = write_rows(ws, (
                (*row[:7], *(1 if test.tno in flags else None
                            for flags in row[7] for test in wafer.config.tests))
                for row in wafer.address_rows()), return_rows=report_mode == "full")
            ws.autofilter(0, 0, last, width - 1)
            if last:
                for wt in range(len(wafer.phases)):
                    first = 7 + wt * ntests
                    ws.conditional_format(1, first, last, first + ntests - 1, {
                        "type": "cell", "criteria": "==", "value": 1, "format": phase_flags[wt]})
            return row_numbers

        def comparison_sheet():
            ws = worksheet("Fail BLK" if report_mode == "batch" else "BLK_FBC_Comparison")
            order = compare_order(wafer)
            rows = ((*r[:3], *(r[i] for i in order)) for r in wafer.fbc_rows())
            if report_mode != "full":
                cols = ["X", "Y", "BLK", *test_headers(wafer, True)]
                ws.set_row(0, 144)
                ws.set_column(0, 2, 8, grid)
                ws.set_column(3, len(cols) - 1, 7, zero_hidden)
                ws.freeze_panes(1, 3)
                for i, label in enumerate(cols):
                    ws.write(0, i, label, head if i < 3 else phase_tall[0])
                last, _ = write_rows(ws, rows)
                ws.autofilter(0, 0, last, len(cols) - 1)
                return
            ws.set_row(0, 23)
            ws.set_row(1, 140)
            ws.set_column(0, 2, 9, grid)
            ws.set_column(3, len(order) + 2, 7, zero_hidden)
            ws.freeze_panes(2, 3)
            band(ws, 0, 0, 2, "Chip / BLK", head)
            col = 3
            for group in ("Monitor", "Function"):
                tests = [t for t in wafer.config.tests if t.group == group]
                if not tests:
                    continue
                for wt in range(len(wafer.phases)):
                    band(ws, 0, col, col + len(tests) - 1, f"WT{wt + 1} / {group}", phase_headers[wt])
                    col += len(tests)
            ws.write_row(1, 0, ("X", "Y", "BLK"), head)
            col = 3
            for group in ("Monitor", "Function"):
                tests = [t for t in wafer.config.tests if t.group == group]
                for wt in range(len(wafer.phases)):
                    for test in tests:
                        ws.write(1, col, test.label, phase_tall[wt])
                        ws.write_comment(1, col, f"WT{wt + 1} | {group} | TNO={test.tno}",
                                         {"author": "SRAM Wafer Studio"})
                        col += 1
            last, _ = write_rows(ws, rows, first=2)
            ws.autofilter(1, 0, last, len(order) + 2)

        def map_cell_format(color, font, kind, edges):
            key = (color, font, kind, edges)
            if key not in fill_formats:
                fmt = style | {"font_name": "Arial", "font_size": 10, "bold": True, "bg_color": color,
                               "font_color": font, "border_color": "#596878",
                               "num_format": '0.00#"v"' if kind == "vmin" else "0"}
                fmt.update(dict(zip(boundary, edges)))
                fill_formats[key] = book.add_format(fmt)
            return fill_formats[key]

        def map_panel(ws, top, wt, kind, pattern=None, step=1):
            data = wafer.map(wt, pattern, kind)
            locations = {(row["x"], row["y"]): row for row in data}
            x0, x1 = min(x for x, y in locations), max(x for x, y in locations)
            y0, y1 = min(y for x, y in locations), max(y for x, y in locations)
            if max(x1 - x0, y1 - y0) > 99:
                raise ValueError("Wafer Map 座標範圍超過 100。")
            columns = 2 if kind in ("wr", "loss") else 1
            rows = 2 if kind == "wr" else 1
            span = step * columns
            end = (x1 - x0 + 1) * span
            suffix = f"  {pattern}" if pattern else ""
            band(ws, top, 0, max(end, 6), f"WT{wt + 1}  {wafer.label}{suffix}  {MAPS[kind]}", phase_headers[wt])
            ws.set_row(top, 23)
            ws.write(top + 1, 0, "Y/X", axis)
            for x in range(x0, x1 + 1):
                col = 1 + (x - x0) * span
                band(ws, top + 1, col, col + span - 1, x, axis)
            for y in range(y0, y1 + 1):
                for sub in range(rows):
                    dest = top + 2 + (y - y0) * rows + sub
                    ws.set_row(dest, 15 if rows == 2 else 21)
                    if sub == 0:
                        ws.write(dest, 0, y, axis)
                    for x in range(x0, x1 + 1):
                        point = locations.get((x, y))
                        if point is None:
                            continue
                        col = 1 + (x - x0) * span
                        labels, fills = cell_style(point, kind)
                        if len(labels) == 1 and columns == 2:
                            labels, fills = labels * (columns * rows), fills * (columns * rows)
                        whole = point.get("gray") or point.get("blue")
                        for offset in range(columns):
                            index = sub * columns + offset
                            color = fills[index]
                            font = "#ffffff" if color == "#ff433c" else (
                                "#a6a6a6" if kind == "wr" and index == 3 else "#122034")
                            inner = 0 if whole else 4
                            edges = (1 if offset == 0 else inner, 1 if offset == columns - 1 else inner,
                                     1 if sub == 0 else inner, 1 if sub == rows - 1 else inner)
                            fmt = map_cell_format(color, font, kind, edges)
                            text = labels[index]
                            if kind == "vmin" and point["value"] is not None:
                                value = point["value"]
                            elif text.isdigit():
                                value = int(text)
                            else:
                                value = text if text and text != "—" else None
                            c = col + offset * step
                            if value is None and step == 1:
                                ws.write_blank(dest, c, None, fmt)
                            else:
                                band(ws, dest, c, c + step - 1, "" if value is None else value, fmt)
            return top + 4 + (y1 - y0 + 1) * rows

        def map_sheet(name, kind, *, repair=False):
            ws = worksheet(name)
            ws.set_tab_color("#287980")
            ws.set_landscape()
            ws.fit_to_pages(1, 0)
            ws.set_column(0, 0, 5)
            ws.set_column(1, 100, 10 if kind == "vmin" else 6)
            if report_mode == "full":
                band(ws, 0, 0, 9, name, title)
                ws.set_row(0, 26)
            if kind == "vmin":
                band(ws, 1, 0, 12, f"{wafer.config.mode} · Highest eligible BLK Vmin · Tail cutoff Q3 + 1.5 × IQR", info)
            top = 3 if report_mode == "full" else 0
            for layer in (kind, "repair") if repair else (kind,):
                for wt in range(len(wafer.phases)):
                    top = map_panel(ws, top, wt, layer)

        def unified_maps():
            ws = worksheet("Wafer Maps")
            ws.set_tab_color("#287980")
            ws.set_zoom(80)
            ws.set_column(0, 0, 5)
            ws.set_column(1, 200, 4.5)
            band(ws, 0, 0, 23, "Wafer Maps", title)
            ws.set_row(0, 26)
            sequence = [(wt, pattern) for wt in range(len(wafer.phases)) for pattern in wafer.config.patterns]
            nav_rows = (len(sequence) + 5) // 6
            ws.freeze_panes(2 + 3 * nav_rows, 0)
            top = 4 + 3 * nav_rows
            panels = []
            height = max(y for x, y in wafer.chips) - min(y for x, y in wafer.chips) + 1
            for layer in ("fail", "wr", "loss"):
                for wt, pattern in sequence:
                    panels.append((top, wt, pattern, layer))
                    top += 4 + height * (2 if layer == "wr" else 1)
            for i, (dest, wt, pattern, layer) in enumerate(panels):
                group, position = divmod(i, len(sequence))
                row, col = 2 + group * nav_rows + position // 6, position % 6 * 4
                band(ws, row, col, col + 3, "", link)
                ws.set_row(row, 32)
                ws.write_url(row, col, f"internal:'Wafer Maps'!A{dest + 1}", link,
                             string=f"WT{wt + 1} {pattern} {MAPS[layer]}")
            for dest, wt, pattern, layer in panels:
                map_panel(ws, dest, wt, layer, pattern, 2 if layer == "fail" else 1)
                ws.write_url(dest + height * (2 if layer == "wr" else 1) + 2, 0,
                             "internal:'Wafer Maps'!A1", string="返回", cell_format=link)

        def block_distribution():
            default_chip = next((xy for (_, _, xy), mask in wafer.fail_maps.items()
                                 if isinstance(mask, int) and mask), wafer.chips[0])
            selected = chip if chip in wafer.chips else default_chip
            ws = worksheet("BLK Pattern Distribution")
            ws.set_zoom(70)
            ws.set_column(0, 95, 3.15)
            ws.freeze_panes(4, 0)
            x, y = selected
            band(ws, 0, 0, 95, f"256 BLK Distribution  |  X{x} Y{y}  |  {wafer.config.mode}", title)
            ws.set_row(0, 26)
            band(ws, 1, 0, 95, "/".join(wafer.config.patterns), mid)
            entries = wafer.grid(selected)
            for col in range(0, 96, 6):
                for wt in range(len(wafer.phases)):
                    band(ws, 2, col + wt * 2, col + wt * 2 + 1, f"WT{wt + 1}", phase_headers[wt])
            for col in range(0, 96, 6):
                for wt in range(len(wafer.phases)):
                    ws.write_row(3, col + wt * 2, ("W", "R"), axis)
            colors = {name: ("#ffe0aa", "#c8d9ef", "#cde8ca", "#f0ccee", "#dddbf5")[i % 5]
                      for i, name in enumerate(wafer.config.patterns)}
            clean_blocks = {r["blk"] for r in entries if all(p["status"] == "Pass" for p in r["states"])}
            for row in range(16):
                start = 4 + row * 3
                ws.set_row(start, 21)
                for col in range(16):
                    record = entries[row + 16 * col]
                    trigger = record["trigger"]
                    hard = record["hard"]
                    clean = record["blk"] in clean_blocks
                    color = "#ff9999" if hard else "#00b0f0" if clean else colors.get(
                        trigger["pattern"] if trigger else None, "#edf4fa")
                    label = ""
                    if trigger:
                        if wafer.config.mode == "FBC90%":
                            label = trigger["func"] or ""
                        elif trigger["voltage"] is not None:
                            label = f'{trigger["voltage"]:.3f}'.rstrip('0').rstrip('.') + "v"
                    fmt = map_cell_format(color, "#17324d", "", (1, 1, 1, 0))
                    band(ws, start, col * 6, col * 6 + 5, label, fmt)
                    note = f'BLK {record["blk"]}'
                    if trigger:
                        note += f'\nWT{trigger["wt"]} {trigger["pattern"]} · TNO {trigger["tno"]}'
                    ws.write_comment(start, col * 6, note, {"author": "SRAM Wafer Studio"})
                ws.set_row(start + 1, 9)
                for col in range(16):
                    record = entries[row + 16 * col]
                    for wt in range(3):
                        phase = record["states"][wt] if wt < len(record["states"]) else {}
                        color = "#ff9999" if record["hard"] else "#00b0f0" if record["blk"] in clean_blocks else {
                            "Pass": "#00b0f0", "Fail": "#f35b53"}.get(phase.get("status"), "#e2e8f0")
                        band(ws, start + 1, col * 6 + wt * 2, col * 6 + wt * 2 + 1, "",
                             map_cell_format(color, "#17324d", "", (1, 1, 0, 0)))
                ws.set_row(start + 2, 15)
                for col in range(16):
                    record = entries[row + 16 * col]
                    for wt in range(3):
                        phase = record["states"][wt] if wt < len(record["states"]) else {}
                        for offset, side in enumerate(("w", "r")):
                            n = phase.get(side, 0)
                            color = "#ff9999" if record["hard"] else "#00b0f0" if record["blk"] in clean_blocks else (
                                "#ffd966" if side == "w" and n else "#ffffff")
                            ws.write(start + 2, col * 6 + wt * 2 + offset, n or None,
                                     map_cell_format(color, "#17324d", "", (offset == 0, offset == 1, 0, 1)))
            for i, (name, color) in enumerate(colors.items()):
                band(ws, 53 + i, 0, 14, name, map_cell_format(color, "#17324d", "", (1, 1, 1, 1)))

        if report_mode == "full":
            config_sheet()
        if report_mode in ("batch", "cat"):
            map_sheet("Cat Wafer Map", "cat", repair=True)
        if report_mode in ("batch", "full", "address"):
            addresses = address_sheet()
        if report_mode in ("batch", "full", "fbc"):
            comparison_sheet()
        if report_mode == "full":
            table("Fail Analysis", ["WT", "Pattern", "X", "Y", "Fail BLK Count", "Status", "Read", "Write",
                                    "Read & Write", "No Monitor", "Loss BLK"], (
                (wt + 1, name, *chip, mask.bit_count() if isinstance(mask, int) else None,
                 ("Fail" if mask else "Pass") if isinstance(mask, int) else mask,
                 *wafer.map_stats.get((wt, name, chip), [0] * 5))
                for (wt, name, chip), mask in wafer.fail_maps.items()))
            missing_order = ("wt", "tno", "name", "voltage", "pattern", "x", "y", "blk",
                             "fbc", "recorded", "gap", "finding", "total", "basis", "endpoint")
            audit_labels = AUDIT_COLUMNS | {"tno": "TNO", "name": "Func.", "voltage": "Test Voltage"}
            ws = worksheet("Missing BLK Address")
            ws.freeze_panes(4, 0)
            ws.set_column("A:H", 13, mid)
            ws.set_column("I:O", 20, mid)
            ws.set_column("N:O", 26, mid)
            band(ws, 0, 0, 14, "Map BLK Address Coverage", title)
            ws.set_row(0, 26)
            band(ws, 1, 0, 14, "Pattern coverage and endpoint Address counts", info)
            ws.set_row(3, 31)
            ws.write_row(3, 0, [audit_labels[k] for k in missing_order], head)
            last, _ = write_rows(ws, ((f"WT{row[k]}" if k == "wt" else row[k] for k in missing_order)
                                      for row in wafer.audit()), first=4)
            ws.autofilter(3, 0, last, 14)
            cols = ["WT", "Pattern", "X", "Y", "BLK", "WL", "BL", "IO", "Function TNOs", "Write TNOs",
                    "Read TNOs", "Classification", "Source Row"]
            ws = new_table("Monitor Fail Analysis", cols)
            end = 0
            for entry in wafer.audit():
                wt, name = entry["wt"], entry["pattern"]
                chip = entry["x"], entry["y"]
                for row in wafer.address_info(wt - 1, chip, entry["blk"], wafer.config.patterns[name]):
                    end += 1
                    if end >= 1_048_576:
                        raise ValueError("Monitor Fail Analysis 超過 Excel 的列數上限。")
                    addr = row["address"]
                    ws.write_row(end, 0, (wt, name, *chip, *addr, *(
                        ",".join(map(str, row[key])) for key in ("function", "write", "read")), row["category"]))
                    source = addresses.get((*chip, *addr))
                    if source and end <= 65530:
                        ws.write_url(end, 12, f"internal:'Fail Address'!A{source}", string=str(source))
                    elif source:
                        ws.write_number(end, 12, source)
            ws.autofilter(0, 0, end, len(cols) - 1)
            table("Chip Vmin", ["WT", "X", "Y", *VMIN_COLUMNS.values()],
                  ((wt + 1, *chip, *((",".join(map(str, result[k])) if isinstance(result[k], list) else result[k])
                                    for k in VMIN_COLUMNS)) for (wt, chip), result in wafer.all_vmin.items()))
            unified_maps()
            map_sheet("Cat Wafer Map", "cat", repair=True)
            map_sheet("Chip Vmin Map", "vmin")
            block_distribution()
        if report_mode != "batch":
            cols = ["WT", "Path", "Full Lot", "Version", "STEP", "Files' WT", "Chips", "FBC rows", "Addresses",
                    "Invalid addresses", "Duplicate FBC", "Missing TNO", "Diagnostics"]
            keys = ("wt", "path", "lot", "version", "step", "source_wt", "chips", "fbc", "address", "invalid", "duplicates")
            table("Import Info", cols, ((*[r[k] for k in keys], ", ".join(map(str, r["missing"])), " | ".join(r["issues"]))
                                        for r in wafer.manifest))


def save_report(wafer, folder, kind, stem=None, *, chip=None):
    folder.mkdir(parents=True, exist_ok=True)
    extension = "pptx" if kind == "ppt" else "xlsx"
    path = output_path(folder, stem or f"{wafer.label}_WT1" + (
        f"-WT{len(wafer.phases)}" if len(wafer.phases) > 1 else "") + f"_{kind}", extension)
    with NamedTemporaryFile(dir=folder, prefix=".sram-", suffix=f".{extension}", delete=False) as temp:
        part = Path(temp.name)
    try:
        if kind == "ppt":
            write_ppt(wafer, part)
        else:
            write_excel(wafer, part, kind, chip=chip)
        part.rename(path)
    finally:
        part.unlink(missing_ok=True)
    return path
