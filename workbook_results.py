
"""Read previously generated VBA analysis workbooks without running macros."""
from __future__ import annotations

from array import array
from pathlib import Path
import re

from openpyxl import load_workbook

from engine import BLKS, ChipData, Config, Identity, Phase, Wafer
from workbook_settings import workbook_config


def phase_number(value):
    found = re.fullmatch(r"WT([123])", str(value or ""), re.IGNORECASE)
    if not found:
        raise ValueError(f"Invalid WT label {value}.")
    return int(found[1]) - 1


def checked_integer(value, low, high, name):
    try:
        number = int(value)
        if float(value) == number and low <= number <= high:
            return number
    except (ValueError, TypeError, OverflowError):
        pass
    raise ValueError(f"Invalid {name} field in the existing Excel.")


def source_index(book):
    rows = list(book["Import Index"].iter_rows(min_row=2, max_row=7, min_col=8, max_col=15, values_only=True))
    if any("pending" in str(row[0]).lower() for row in rows):
        raise ValueError("Address or FBC import in the existing Excel file is incomplete.")
    if rows[0][0] != "Address" or rows[3][0] != "FBC":
        return {}
    for a, f in zip(rows[:3], rows[3:]):
        if a[1:6] != f[1:6]:
            raise ValueError(f"Address and FBC LOT/WNO/STEP/version do not match for {a[1]}.")
    return {phase_number(row[1]): row for row in rows[3:] if row[0] == "FBC"}


def address_index(book, config, headers):
    result = {}
    if "Import Index" in book.sheetnames:
        for wt, tno, col in book["Import Index"].iter_rows(min_row=2, max_col=3, values_only=True):
            if wt is None or tno is None or col is None:
                continue
            phase = phase_number(wt)
            number, column = int(tno), int(col) - 1
            if number not in config.index:
                continue
            if column >= len(headers) or column < 6 or not str(headers[column]).split("\n")[0].upper() == f"WT{phase+1}":
                raise ValueError("Fail Address headers do not match the TNO index.")
            if column in result or (phase, number) in result.values():
                raise ValueError("Duplicate TNO indices in Fail Address.")
            result[column] = phase, number
    if result:
        return result
    labels = {}
    for test in config.tests:
        labels.setdefault(test.label, []).append(test.tno)
    for column, label in enumerate(headers):
        match = re.fullmatch(r"WT([123])\s+(.+)", str(label or ""), re.IGNORECASE)
        if not match:
            continue
        name = match[2].strip()
        hits = [int(name)] if name.isdigit() else labels.get(name, [])
        if len(hits) > 1:
            raise ValueError(f"Existing Excel column {name} maps to multiple TNOs.")
        if hits and hits[0] in config.index:
            result[column] = int(match[1]) - 1, hits[0]
    return result


def read_existing(path, report=lambda _: None):
    settings = workbook_config(path)
    config = Config.create(settings["rows"], settings["mode"])
    warnings, phases = [], {}
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if not {"Fail Address", "FBC by BLK"}.issubset(book.sheetnames):
            raise ValueError("Verification requires an original VBA .xlsm result containing Config, Fail Address and FBC by BLK.")
        indexes = source_index(book) if "Import Index" in book.sheetnames else {}
        if not indexes:
            warnings.append("Source identity is incomplete. Confirm that Fail Address and FBC use the same ASC sources.")

        def get_phase(wt):
            if wt not in phases:
                row = indexes.get(wt)
                if row:
                    version = re.search(r"Ver_?([a-zA-Z]{2})", str(row[5]))
                    ident = Identity(path, str(row[2]), int(row[3]), wt + 1,
                                     version[1].upper() if version else "Unknown", wt + 1)
                else:
                    fallback = re.match(r"([^#]+)#(\d+)", path.stem)
                    ident = Identity(path, fallback[1] if fallback else path.stem,
                                     int(fallback[2]) if fallback else 0, wt + 1, "Unknown", wt + 1)
                phases[wt] = Phase(ident)
            return phases[wt]

        report("Reading FBC by BLK from existing Excel")
        sheet = book["FBC by BLK"]
        for data in sheet.iter_rows(min_row=2, max_col=260, values_only=True):
            if data[1] is None:
                continue
            tno = int(data[1])
            if tno not in config.index:
                continue
            wt = phase_number(data[0])
            x, y = (checked_integer(data[i], -2**31, 2**31 - 1, "X/Y") for i in (2, 3))
            phase = get_phase(wt)
            die = phase.chips.setdefault((x, y), ChipData())
            if tno in die.fbc:
                raise ValueError(f"Duplicate FBC for WT{wt+1} X{x} Y{y} TNO {tno}.")
            values = array("Q", (checked_integer(v, 0, 9_007_199_254_740_990, "FBC") for v in data[4:4+BLKS]))
            die.fbc[tno] = values
            die.masks[tno] = sum(1 << b for b, v in enumerate(values) if v)
            phase.seen.add(tno)
        if not phases:
            raise ValueError("No FBC records available for verification in the existing Excel.")

        report("Reading Fail Address from existing Excel")
        source = book["Fail Address"]
        values = source.values
        headers = next(values, ())
        columns = address_index(book, config, headers)
        if not columns:
            raise ValueError("Fail Address has no recognizable WT/TNO columns.")
        category_col = 6 if str(headers[6]).strip().lower() in ("cat.", "cat") else None
        for row in values:
            if row[0] is None or row[1] is None:
                continue
            limits = [(-2**31, 2**31-1)] * 2 + [(0,255),(0,1023),(0,15),(0,15)]
            names = ("X", "Y", "BLK", "WL", "BL", "IO")
            coordinates = [checked_integer(v, *domain, name) for v, domain, name in zip(row, limits, names)]
            x, y, *address = coordinates
            for column, (wt, tno) in columns.items():
                if column < len(row) and str(row[column]) in ("1", "1.0", "True"):
                    phase = get_phase(wt)
                    die = phase.chips.setdefault((x, y), ChipData())
                    die.addresses.setdefault(address[0], {}).setdefault(tuple(address), set()).add(tno)
                    phase.seen.add(tno)
            if category_col is not None and row[category_col] is not None:
                category = int(str(row[category_col]).strip().upper().removeprefix("C"))
                get_phase(0).chips.setdefault((x, y), ChipData()).cat = category or None
        if sorted(phases) != list(range(max(phases) + 1)):
            raise ValueError("An intermediate WT phase is missing from the existing Excel index.")
        return Wafer(config, tuple(phases[i] for i in sorted(phases))), warnings
    finally:
        book.close()
