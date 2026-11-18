"""Read the existing Excel Config layout."""

from dataclasses import asdict
from engine import MODES, TailBitSettings


def workbook_config(path):
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book["Config"]
        settings = list(sheet.iter_rows(min_row=1, max_row=901, max_col=10, values_only=True))
        stop = next((index for index in (7, 6) if str(settings[0][index]).strip().lower() == "stop sign"), None)
        has_cat = str(settings[0][6]).strip().lower() in ("fail cat.", "fail cat")
        rows = []
        for group, offset in (("Monitor", 0), ("Function", 3)):
            for row in settings[1:]:
                if row[offset] in (None, ""):
                    continue
                rows.append({"group": group, "tno": row[offset], "name": row[offset + 1],
                             "voltage": row[offset + 2], "cat": row[6] if group == "Function" and has_cat else None,
                             "stop": row[stop] if group == "Function" and stop is not None else ""})
        tail_bits = {}
        if sheet.cell(1, 12).value == "Tail FBC0 setting":
            for key, value in sheet.iter_rows(min_row=2, max_row=7, min_col=12, max_col=13, values_only=True):
                if key is not None:
                    tail_bits[key] = value
        return {"rows": rows, "mode": settings[0][9] if settings[0][9] in MODES else "FBC0",
                "tail_bits": asdict(TailBitSettings.create(tail_bits))}
    finally:
        book.close()
