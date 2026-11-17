
"""Streaming ASC reader and SRAM analysis shared by the UI and exports."""
from __future__ import annotations

from array import array
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import cached_property
from itertools import combinations
from math import isfinite
from pathlib import Path
import csv
import re
from typing import Callable

BLKS = 256
ALL = (1 << BLKS) - 1
MODES = tuple(f"FBC{i}" for i in range(11)) + ("FBC90%",)
GROUPS = ("Read Fail", "Write Fail", "Write&Read Fail", "No monitor item Fail")
MATCH_LABELS = ("Read only", "Write only", "Write & Read", "No monitor hit")
TAG = re.compile(r"\b(TNO|X|Y)\s*=\s*([+-]?\d+)(?=\s|[,;]|$)", re.I)
META = re.compile(r"\b(LOT|WNO|STEP|Program)[ \t]*=[ \t]*", re.I)
FBC = re.compile(r"\bFBC\s+BY\s+BLK\s*=\s*", re.I)
SPLIT = re.compile(r"[\s,;]+")
CAT = re.compile(r"\bCATLST\s*:\s*([01]+)(?=\s|$)", re.I)
TOKENS = re.compile(r"\btno\s*=\s*[+-]?\d+|\[[^\]]*\]", re.I)
ADDRESS_FIELDS = re.compile(r"\s*[+-]?\d+(?:\s*,\s*[+-]?\d+){7}\s*,?\s*")
Chip = tuple[int, int]
Address = tuple[int, int, int, int]
Progress = Callable[[str], None]


def bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def voltage_text(voltage):
    if voltage is None:
        return "—"
    value = f"{voltage:.6f}".rstrip("0")
    return value + "0" * max(0, 2 - len(value.split(".")[-1]))


@dataclass(frozen=True)
class Test:
    group: str
    tno: int
    name: str
    voltage: float | None
    cat: int | None = None
    stop: str = ""

    @property
    def label(self):
        if self.voltage is None:
            return self.name
        return f"{self.name}_{voltage_text(self.voltage)}v"


@dataclass
class Config:
    tests: tuple[Test, ...]
    mode: str

    @classmethod
    def create(cls, rows, mode="FBC0", *, full=True):
        if mode not in MODES:
            raise ValueError("請選擇 FBC0～FBC10 或 FBC90%。")
        tests = []
        used = set()
        for i, row in enumerate(rows, 2):
            raw = row.get("tno")
            if raw is None or str(raw).strip() == "":
                if any(str(row.get(key) if row.get(key) is not None else "").strip()
                       for key in ("name", "voltage", "cat", "stop")):
                    raise ValueError(f"設定第 {i} 列有資料但缺少 TNO。")
                continue
            try:
                tno = int(raw)
                if not 100 <= tno <= 999 or float(raw) != tno:
                    raise ValueError()
                name = str(row.get("name") or "").strip()
                group = str(row.get("group") or "").strip().capitalize()
                if group not in ("Monitor", "Function") or not name:
                    raise ValueError()
                voltage = row.get("voltage")
                voltage = None if voltage in ("", None) else float(voltage)
                if voltage is not None and (not isfinite(voltage) or voltage < 0):
                    raise ValueError()
                cat = str(row.get("cat") or "").strip().upper().removeprefix("C")
                cat = int(cat) if cat else None
                if cat is not None and cat < 1:
                    raise ValueError()
                stop = str(row.get("stop") or "").strip()
                if group == "Monitor" and stop:
                    raise ValueError()
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"設定第 {i} 列格式錯誤，請確認 TNO、Func.、Voltage、Fail Cat 和 Stop Sign。") from exc
            if tno in used:
                raise ValueError(f"TNO {tno} 重複。")
            used.add(tno)
            tests.append(Test(group, tno, name, voltage, cat, stop if full else ""))
        if not tests:
            raise ValueError("設定至少需要一筆 TNO。")
        result = cls(tuple(sorted(tests, key=lambda t: t.group != "Monitor")), mode)
        result.patterns
        if full and not result.patterns:
            raise ValueError("Function 至少需要一個 Pattern 終點（Stop Sign）。")
        return result

    @cached_property
    def index(self):
        return {t.tno: t for t in self.tests}

    @cached_property
    def functions(self):
        return tuple(t for t in self.tests if t.group == "Function")

    @cached_property
    def monitor_sides(self):
        sides = {}
        for t in self.tests:
            normalized = re.sub(r"[\s_-]+", "", t.name.lower())
            if t.group == "Monitor":
                if normalized.startswith("wlowpbl"):
                    sides[t.tno] = "W"
                if normalized.startswith("rlowpbl"):
                    sides[t.tno] = "R"
        return sides

    @cached_property
    def intervals(self):
        scope, found, names = [], {}, set()
        for t in self.functions:
            scope.append(t)
            if t.stop:
                name = t.stop
                if name.casefold() in names:
                    raise ValueError(f"Stop Sign {name} 重複。")
                names.add(name.casefold())
                found[name] = tuple(scope)
                scope.clear()
        return found

    @cached_property
    def patterns(self):
        return {name: scope for name, scope in self.intervals.items() if name.lower() != "hard fail"}

    @cached_property
    def hard(self):
        return tuple(t for name, scope in self.intervals.items() if name.lower() == "hard fail" for t in scope)

    def voltages_for(self, tnos):
        return list(dict.fromkeys(self.index[tno].voltage for tno in tnos))

    def json(self):
        return {"mode": self.mode, "rows": [asdict(t) for t in self.tests]}


def csv_config(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = []
        for row in csv.DictReader(stream):
            row = {str(key).strip().lower(): value for key, value in row.items()}
            rows.append({"group": row.get("group"), "tno": row.get("tno"),
                         "name": row.get("func.", row.get("name")),
                         "voltage": row.get("test voltage", row.get("voltage")),
                         "cat": row.get("fail cat.", row.get("cat")),
                         "stop": row.get("stop sign", row.get("stop"))})
    return rows


def text_stream(path):
    with path.open("rb") as handle:
        sample = handle.read(32768)
    if sample.startswith((b"\xFF\xFE", b"\xFE\xFF")):
        encoding = "utf-16"
    elif sample[1:64:2].count(0) >= 12:
        encoding = "utf-16-le"
    elif sample[:64:2].count(0) >= 12:
        encoding = "utf-16-be"
    elif sample.startswith(b"\xEF\xBB\xBF"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    return path.open(encoding=encoding, errors="replace", buffering=256 * 1024)


@dataclass(frozen=True)
class Identity:
    path: Path
    lot: str
    wafer: int
    step: int
    version: str
    source_wt: int | None

    @property
    def key(self):
        return self.lot, self.wafer

    @property
    def label(self):
        return f"{self.lot[:6]}#{self.wafer:02}"


def identity(path: Path):
    if path.suffix.lower() != ".asc" or not path.is_file():
        raise ValueError(f"找不到 ASC 檔案 {path.name}。")
    fields = {}
    third = ""
    with text_stream(path) as stream:
        for n, line in enumerate(stream, 1):
            if n == 3:
                third = line
            for match, end in zip((hits := list(META.finditer(line))),
                                  [m.start() for m in hits[1:]] + [len(line)]):
                name = match[1].upper()
                val = line[match.end():end].strip()
                if name != "PROGRAM":
                    val = re.split(r"[\s,;]+", val.strip("\"'"))[0]
                fields.setdefault(name, val)
            if (len(fields) == 4 and n >= 3) or n >= 128:
                break
    lot = fields.get("LOT", "")
    wafer = fields.get("WNO", "").lstrip("#")
    step = re.fullmatch(r"\D*(\d+)\D*", fields.get("STEP", ""))
    if not lot or not wafer.isdigit() or not step:
        raise ValueError(f"{path.name} 缺少有效 LOT、WNO 或 STEP。")
    program = fields.get("PROGRAM", third)
    version_pos = program.upper().find("VER_")
    version = program[version_pos + 4:version_pos + 6]
    version = version.upper() if version_pos >= 0 and re.fullmatch(r"[A-Za-z]{2}", version) else "Unknown"
    labels = re.findall(r"(?:^|[^a-z0-9])WT([123])(?=$|[^a-z0-9])", path.stem, re.I)
    if len(labels) > 1:
        raise ValueError(f"{path.name} 的 WT 標記不明確。")
    return Identity(path, lot, int(wafer), int(step[1]), version,
                    int(labels[0]) if labels else None)


@dataclass
class ChipData:
    cat: int | None = None
    fbc: dict[int, array] = field(default_factory=dict)
    masks: dict[int, int] = field(default_factory=dict)
    addresses: dict[int, dict[Address, set[int]]] = field(default_factory=dict)

    @property
    def evidence(self):
        return bool(self.addresses) or any(self.masks.values())


@dataclass
class Phase:
    source: Identity
    chips: dict[Chip, ChipData] = field(default_factory=dict)
    seen: set[int] = field(default_factory=set)
    issues: list[str] = field(default_factory=list)
    invalid_addresses: int = 0
    duplicates: int = 0
    fbc_error: bool = False

    def diagnostic(self, message):
        self.fbc_error = True
        if len(self.issues) < 20:
            self.issues.append(message)


def read_asc(source, config, *, addresses=True, fbc=True, report=lambda _: None):
    phase = Phase(source)
    selected = config.index
    pending = None
    record = []
    header = None
    carry = ""
    fbc_total = 0

    def finish():
        nonlocal pending, record, fbc_total
        if pending is None:
            return
        chip, tno, start = pending
        if len(record) != BLKS:
            phase.diagnostic(f"第 {start} 行 TNO {tno} X{chip[0]} Y{chip[1]} FBC 欄數為 {len(record)}，應為 256。")
        else:
            die = phase.chips[chip]
            if tno in die.fbc:
                phase.duplicates += 1
            else:
                die.fbc[tno] = array("Q", record)
                die.masks[tno] = sum(1 << b for b, count in enumerate(record) if count)
                fbc_total += 1
        pending, record = None, []

    with text_stream(source.path) as stream:
        for n, line in enumerate(stream, 1):
            if n % 20000 == 0:
                report(f"{source.path.name} · {n:,} 行 · {fbc_total:,} 筆 FBC")
            match = FBC.search(line) if fbc and "=" in line else None
            is_cat = "catlst" in line.lower() if "=" in line else False
            tags = {}
            if "=" in line:
                tags = {m[1].upper(): int(m[2]) for m in TAG.finditer(line[:match.start()] if match else line)}
            chip = None
            if "X" in tags and "Y" in tags and all(-2**31 <= tags[k] < 2**31 for k in ("X", "Y")):
                chip = tags["X"], tags["Y"]
                die = phase.chips.setdefault(chip, ChipData())
                if is_cat and tags.get("TNO") == 1000:
                    cat = CAT.search(line)
                    if cat is None:
                        phase.diagnostic(f"第 {n} 行 CATLST 格式錯誤。")
                    else:
                        category = cat[1].find("1") + 1
                        if category and die.cat and die.cat != category:
                            phase.diagnostic(f"第 {n} 行 X{chip[0]} Y{chip[1]} CATLST 衝突。")
                        elif category:
                            die.cat = category
            if match:
                finish()
                if tags.get("TNO") is None:
                    phase.diagnostic(f"第 {n} 行的 FBC 標頭缺少 TNO。")
                elif tags["TNO"] in selected:
                    if chip is None:
                        phase.diagnostic(f"第 {n} 行 TNO {tags['TNO']} 的 FBC 缺少有效 X/Y。")
                    else:
                        pending = chip, tags["TNO"], n
                        payload = line[match.end():].strip()
            elif pending is not None:
                payload = line.strip()
                if payload and (len(record) == BLKS and payload[0] not in "0123456789,+-" or
                                len(record) < BLKS and payload[0] not in "0123456789,+-;"):
                    finish()
            if pending is not None and payload:
                tokens = [s for s in SPLIT.split(payload) if s]
                if any(not re.fullmatch(r"[0-9]{1,16}", s) or int(s) > 9_007_199_254_740_990 for s in tokens):
                    phase.diagnostic(f"第 {n} 行 FBC 必須是非負整數。")
                    pending, record = None, []
                else:
                    record.extend(map(int, tokens))
                    if len(record) > BLKS:
                        finish()
            if not addresses:
                if "TNO" in tags:
                    phase.seen.add(tags["TNO"])
                continue
            if ("[" not in line and "=" not in line and not carry):
                continue
            text = carry + line
            carry, end = "", 0
            for token in TOKENS.finditer(text):
                value = token[0]
                end = token.end()
                if value[0] != "[":
                    header = int(value.split("=")[1])
                    phase.seen.add(header)
                elif header in selected:
                    payload_address = value[1:-1]
                    if not ADDRESS_FIELDS.fullmatch(payload_address):
                        phase.invalid_addresses += 1
                        continue
                    fields = tuple(int(s) for s in payload_address.strip().rstrip(",").split(","))
                    _, tno, x, y, blk, wl, bl, io = fields
                    if (tno != header or not 0 <= blk < BLKS or not 0 <= wl <= 1023 or
                            not 0 <= bl <= 15 or not 0 <= io <= 15 or
                            not all(-2**31 <= v < 2**31 for v in (x, y))):
                        phase.invalid_addresses += 1
                        continue
                    die = phase.chips.setdefault((x, y), ChipData())
                    die.addresses.setdefault(blk, {}).setdefault((blk, wl, bl, io), set()).add(tno)
            start = text.find("[", end)
            if start >= 0:
                tail = text[start:]
                if len(tail) <= 16384:
                    carry = tail
                elif header in selected:
                    phase.invalid_addresses += 1
        finish()
    if carry and header in selected:
        phase.invalid_addresses += 1
    return phase


@dataclass(frozen=True)
class Crossing:
    tno: int | None
    voltage: float | None
    func: str | None
    fbc: int | None
    status: str


def vmin(scope, values, mode):
    available = [v for v in values if v is not None]
    peak = max(available, default=0)
    if mode == "FBC90%":
        if len(available) != len(scope):
            return Crossing(None, None, None, None, "No Data")
        threshold = max(1, (9 * peak + 9) // 10)
    else:
        threshold = max(1, int(mode[3:]))
    group = previous = None
    missing = False
    for test, value in zip(scope, values):
        if test.voltage is None:
            group = previous = None
        elif group is None:
            group = test.voltage
        elif test.voltage != group:
            previous, group = group, test.voltage
        if value is None:
            missing = True
        elif value >= threshold:
            voltage = previous if mode == "FBC0" else test.voltage
            status = "No Data" if missing else ("No Vmin" if voltage is None else "Fail")
            return Crossing(test.tno, None if missing else voltage, test.name, value, status)
    return Crossing(None, None, None, None, "No Data" if missing else ("Below" if peak else "Pass"))


def tail_cutoff(values):
    values = sorted(v for v in values if v > 0)
    if len(values) < 4:
        return None

    def quartile(n):
        i, fraction = divmod((len(values) - 1) * n, 4)
        return values[i] + fraction * (values[min(i + 1, len(values) - 1)] - values[i]) / 4

    q1, q3 = quartile(1), quartile(3)
    return q3 + 1.5 * (q3 - q1)


def observed_category(write, read):
    if write and read:
        return GROUPS[2]
    if write:
        return GROUPS[1]
    return GROUPS[0] if read else GROUPS[3]


def match_counts_by_voltage(scope, matches):
    """Count each captured Function address once per voltage in its exclusive category."""
    counts = {test.voltage: [0] * len(GROUPS) for test in scope if test.voltage is not None}
    for row in matches:
        category = GROUPS.index(row["category"])
        for voltage in row["function_voltages"]:
            counts.setdefault(voltage, [0] * len(GROUPS))[category] += 1
    return [{"voltage": voltage, "counts": values} for voltage, values in counts.items()]


def fbc_voltage_comparison(sweep, selected_pattern):
    """Preserve each Scan/March TNO as an independent station in Config order."""
    pattern_order = list(dict.fromkeys(row["pattern"] for row in sweep))
    pair = [name for name in pattern_order if name.casefold() in ("scan", "march")]
    combined = len(pair) == 2 and selected_pattern in pair
    patterns = pair if combined else [selected_pattern]
    palettes = {
        "scan": ("#164a73", "#356a97", "#5284af", "#6f9bc2", "#37607a"),
        "march": ("#9c3827", "#ad5726", "#c16c38", "#d7814d", "#8a502c", "#af7654"),
    }
    fallback = ("#204f78", "#b86b30", "#477958", "#8a577b", "#657481", "#9a8737", "#40798b")
    series, lookup, groups = [], {}, []
    color_indexes = defaultdict(int)
    incomplete = False
    for row in sweep:
        if row["pattern"] not in patterns:
            continue
        if row["v"] is None or row["fbc"] is None:
            incomplete = True
            continue
        pattern, func = row["pattern"], row["func"]
        key = (pattern, func)
        if key not in lookup:
            lookup[key] = len(series)
            palette = palettes.get(pattern.casefold(), fallback)
            index = color_indexes[pattern]
            color_indexes[pattern] += 1
            label = f"{pattern}: {func}" if combined else func
            series.append({"label": label, "color": palette[index % len(palette)],
                           "pattern": pattern, "style": index})
        groups.append({"voltage": row["v"], "tno": row["tno"],
                       "stations": [row | {"series": lookup[key]}]})
    title = "Scan & March FBC by Test Voltage and Function" if combined else "FBC by Test Voltage and Function"
    return {"title": title, "combined": combined, "patterns": patterns, "series": series,
            "groups": groups, "incomplete": incomplete}


def phase_numbers(sources):
    """Resolve labels in STEP order when a filename lacks an explicit WT."""
    labels = tuple(source.source_wt for source in sources)
    claimed = [label for label in labels if label is not None]
    if len(claimed) != len(set(claimed)):
        raise ValueError("同一 Lot／Wafer 的 ASC 檔名 WT 標記不可重複。")
    if not claimed:
        return tuple(range(1, len(labels) + 1))
    if len(claimed) == len(labels):
        return labels
    candidates = [numbers for numbers in combinations((1, 2, 3), len(labels))
                  if all(label is None or label == number for label, number in zip(labels, numbers))]
    if len(candidates) != 1:
        raise ValueError("無法從 STEP 確定所有 WT，請在 ASC 檔名標記 WT1、WT2 或 WT3。")
    return candidates[0]


@dataclass
class Wafer:
    config: Config
    phases: tuple[Phase, ...]
    full: bool = True
    source_mode: str = "full"

    @property
    def label(self):
        return self.phases[0].source.label

    @cached_property
    def chips(self):
        return sorted(set().union(*(p.chips for p in self.phases)))

    @cached_property
    def wt_numbers(self):
        return phase_numbers([phase.source for phase in self.phases])

    @cached_property
    def manifest(self):
        requested = self.config.index.keys()
        return [{"wt": wt, "path": str(p.source.path), "lot": p.source.lot, "version": p.source.version,
                 "step": p.source.step, "source_wt": p.source.source_wt, "chips": len(p.chips),
                 "fbc": sum(len(d.fbc) for d in p.chips.values()),
                 "address": sum(len(a) for d in p.chips.values() for a in d.addresses.values()),
                 "invalid": p.invalid_addresses, "duplicates": p.duplicates, "issues": p.issues,
                 "missing": sorted(requested - p.seen)} for wt, p in zip(self.wt_numbers, self.phases)]

    def die(self, wt, chip):
        return self.phases[wt].chips.get(chip)

    def cat(self, wt, chip, repair=False):
        die = self.die(wt, chip)
        if die is None or not die.cat or not repair or die.cat <= 2:
            return die.cat if die else None
        for phase in range(wt + 1):
            earlier = self.die(phase, chip)
            if earlier:
                for t in self.config.functions:
                    if earlier.masks.get(t.tno):
                        return t.cat
        return None

    def eligibility(self, wt, chip):
        """Return coverage and positive masks with v13.1's hard/prior-WT rules."""
        hard, past, hard_complete, past_complete = 0, 0, True, True
        for i, phase in enumerate(self.phases[:wt + 1]):
            die = phase.chips.get(chip)
            masks = die.masks if die else {}
            for t in self.config.hard:
                hit = masks.get(t.tno)
                hard |= hit or 0
                hard_complete &= hit is not None and not phase.fbc_error
            if i < wt:
                for t in self.config.functions:
                    hit = masks.get(t.tno)
                    past |= hit or 0
                    past_complete &= hit is not None and not phase.fbc_error
        return hard, past & ~hard, hard_complete and past_complete

    @cached_property
    def fail_maps(self):
        result = {}
        for wt, phase in enumerate(self.phases):
            for chip in self.chips:
                die = phase.chips.get(chip)
                hard, past, complete = self.eligibility(wt, chip)
                prior, present = 0, complete
                for name, scope in self.config.patterns.items():
                    endpoint = die.masks.get(scope[-1].tno) if die else None
                    if any(p.fbc_error for p in self.phases[:wt + 1]):
                        value = "Data Error"
                    elif endpoint is None or not present:
                        value = "No Data"
                    else:
                        value = endpoint & ~(prior | hard | past) & ALL
                    result[wt, name, chip] = value
                    present &= endpoint is not None
                    prior |= endpoint or 0
        return result

    def address_info(self, wt, chip, blk, scope):
        die = self.die(wt, chip)
        if not die:
            return
        scope_tnos = {t.tno for t in scope}
        sides = self.config.monitor_sides
        for addr, hits in sorted(die.addresses.get(blk, {}).items()):
            func = sorted(scope_tnos & hits, key=self.order.__getitem__)
            if not func:
                continue
            w = sorted(t for t in hits if sides.get(t) == "W")
            r = sorted(t for t in hits if sides.get(t) == "R")
            yield {"address": addr, "function": func, "write": w, "read": r,
                   "category": observed_category(w, r)}

    def pattern_matches(self, wt, chip, blk, scope):
        for row in self.address_info(wt, chip, blk, scope):
            yield row | {"function_voltages": self.config.voltages_for(row["function"])}

    @cached_property
    def order(self):
        return {t.tno: i for i, t in enumerate(self.config.tests)}

    def audit_one(self, wt, pattern, chip, blk):
        scope = self.config.patterns[pattern]
        die = self.die(wt, chip)
        endpoint = scope[-1]
        count = die.fbc[endpoint.tno][blk]
        info = tuple(self.address_info(wt, chip, blk, scope))
        recorded = sum(endpoint.tno in row["function"] for row in info)
        endpoint_status = ("No Address" if recorded == 0 else "Partial Address" if recorded < count
                           else "Address Count > FBC" if recorded > count else "Complete")
        w, r, wr, none = (sum(row["category"] == group for row in info)
                          for group in (GROUPS[1], GROUPS[0], GROUPS[2], GROUPS[3]))
        return {"wt": self.wt_numbers[wt], "pattern": pattern, "tno": endpoint.tno, "name": endpoint.name,
                "voltage": endpoint.voltage, "x": chip[0], "y": chip[1], "blk": blk, "fbc": count,
                "recorded": recorded, "gap": max(count - recorded, 0), "total": len(info),
                "finding": "Complete" if info else "No Address", "endpoint": endpoint_status,
                "basis": "Endpoint Address present" if recorded else "Earlier TNO only" if info else "No Address in Pattern",
                "w": w, "r": r, "wr": wr, "none": none}

    def audit(self):
        for (wt, pattern, chip), mask in self.fail_maps.items():
            if isinstance(mask, int):
                for blk in bits(mask):
                    yield self.audit_one(wt, pattern, chip, blk)

    @cached_property
    def map_stats(self):
        totals = defaultdict(lambda: [0, 0, 0, 0, 0])
        for row in self.audit():
            bucket = totals[self.wt_numbers.index(row["wt"]), row["pattern"], (row["x"], row["y"])]
            for i, key in enumerate(("r", "w", "wr", "none")):
                bucket[i] += row[key]
            bucket[4] += row["finding"] == "No Address"
        return dict(totals)

    def crossings(self, wt, chip, *, blk=None, mode=None):
        """Yield eligibility and Vmin for each Pattern and requested BLK."""
        blocks = range(BLKS) if blk is None else (blk,)
        mode = mode or self.config.mode
        phase = self.phases[wt]
        die = phase.chips.get(chip, ChipData())
        hard, past, complete = self.eligibility(wt, chip)
        prior, prior_valid = 0, complete
        for name, scope in self.config.patterns.items():
            vectors = [die.fbc.get(t.tno) for t in scope]
            endpoint = die.masks.get(scope[-1].tno)
            sweep_complete = all(vector is not None for vector in vectors)
            for b in blocks:
                mask = 1 << b
                if hard & mask:
                    state = "Hard Fail"
                elif past & mask:
                    state = "Prior WT"
                elif prior & mask:
                    state = "Prior Pattern"
                elif not prior_valid or endpoint is None or phase.fbc_error:
                    state = "No Data"
                else:
                    state = ""
                if state:
                    yield name, b, Crossing(None, None, None, None, state), 0, state != "No Data"
                    continue
                values = [vector[b] if vector is not None else None for vector in vectors]
                peak = max((v for v in values if v is not None), default=0)
                yield name, b, vmin(scope, values, mode), peak, sweep_complete
            prior_valid &= endpoint is not None
            prior |= endpoint or 0

    def chip_vmin(self, wt, chip):
        hard, past, _ = self.eligibility(wt, chip)
        peaks, unknown, best = [0] * BLKS, set(), {}
        for name, b, crossing, peak, complete in self.crossings(wt, chip):
            if crossing.status in ("Hard Fail", "Prior WT", "Prior Pattern"):
                continue
            if not complete:
                unknown.add(b)
            peaks[b] = max(peaks[b], peak)
            old = best.get(b)
            if crossing.voltage is not None and (old is None or old[1].voltage is None or crossing.voltage > old[1].voltage):
                best[b] = name, crossing
            elif crossing.status == "No Vmin" and old is None:
                best[b] = name, crossing
        pool = [b for b in range(BLKS) if not ((hard | past) >> b & 1)]
        cutoff = tail_cutoff(peaks[b] for b in pool if b not in unknown)
        tail = [b for b in pool if cutoff is not None and b not in unknown and peaks[b] > cutoff]
        tail_set = set(tail)
        kept = [b for b in pool if b not in tail_set]
        valid = [b for b in kept if b in best and best[b][1].voltage is not None]
        winner = max(valid, key=lambda b: (best[b][1].voltage, -b), default=None)
        incomplete = len(unknown.intersection(kept))
        status = ("Vmin" if winner is not None else "No BLK" if not kept else "No Data" if incomplete
                  else "No Vmin" if any(b in best for b in kept) else "Below" if any(peaks[b] for b in kept)
                  else "Pass")
        pattern, result = best[winner] if winner is not None else (None, None)
        return {"status": status, "voltage": result.voltage if result else None, "blk": winner,
                "tno": result.tno if result else None, "func": result.func if result else None,
                "pattern": pattern, "cutoff": cutoff, "tail": tail, "hard": list(bits(hard)),
                "prior": past.bit_count(), "remaining": len(kept), "incomplete": incomplete}

    def pattern_chip_vmin(self, wt, chip, pattern):
        """Per-pattern worst eligible BLK Vmin, using the existing chip Tail filter."""
        aggregate = self.chip_vmin(wt, chip)
        tail = set(aggregate["tail"])
        candidates = [(blk, crossing) for name, blk, crossing, _, _ in self.crossings(wt, chip, mode="FBC90%")
                      if name == pattern and blk not in tail and crossing.voltage is not None]
        winner = max(candidates, key=lambda item: (item[1].voltage, -item[0]), default=None)
        if winner is None:
            return {"status": "No Vmin", "voltage": None, "value": None, "blk": None,
                    "tno": None, "func": None, "pattern": pattern,
                    "tail": aggregate["tail"], "hard": aggregate["hard"],
                    "cutoff": aggregate["cutoff"], "remaining": aggregate["remaining"],
                    "incomplete": aggregate["incomplete"]}
        blk, crossing = winner
        return {"status": "Vmin", "voltage": crossing.voltage, "value": crossing.voltage,
                "blk": blk, "tno": crossing.tno, "func": crossing.func, "pattern": pattern,
                "tail": aggregate["tail"], "hard": aggregate["hard"],
                "cutoff": aggregate["cutoff"], "remaining": aggregate["remaining"],
                "incomplete": aggregate["incomplete"]}

    def merged_fbc90(self, wt, chip, blk):
        """One 90% crossing over Scan then March in Config order (shared peak)."""
        names = [name for name in self.config.patterns if name.casefold() in ("scan", "march")]
        if len(names) != 2:
            return Crossing(None, None, None, None, "No Data")
        hard, past, complete = self.eligibility(wt, chip)
        if hard >> blk & 1:
            return Crossing(None, None, None, None, "Hard Fail")
        if past >> blk & 1:
            return Crossing(None, None, None, None, "Prior WT")
        phase = self.phases[wt]
        die = phase.chips.get(chip, ChipData())
        if not complete or phase.fbc_error or any(die.masks.get(self.config.patterns[name][-1].tno) is None for name in names):
            return Crossing(None, None, None, None, "No Data")
        scope = [test for name in names for test in self.config.patterns[name]]
        values = [die.fbc[test.tno][blk] if test.tno in die.fbc else None for test in scope]
        return vmin(scope, values, "FBC90%")

    def merged_chip_vmin(self, wt, chip):
        aggregate = self.chip_vmin(wt, chip)
        tail = set(aggregate["tail"])
        hard, past, _ = self.eligibility(wt, chip)
        candidates = [(blk, result) for blk in range(BLKS)
                      if blk not in tail and not ((hard | past) >> blk & 1)
                      for result in [self.merged_fbc90(wt, chip, blk)]
                      if result.voltage is not None]
        winner = max(candidates, key=lambda item: (item[1].voltage, -item[0]), default=None)
        result = {"status": "Vmin" if winner else "No Vmin",
                  "voltage": winner[1].voltage if winner else None,
                  "blk": winner[0] if winner else None,
                  "tno": winner[1].tno if winner else None,
                  "func": winner[1].func if winner else None,
                  "pattern": "Merge 90%", "tail": aggregate["tail"],
                  "hard": aggregate["hard"], "cutoff": aggregate["cutoff"],
                  "remaining": aggregate["remaining"], "incomplete": aggregate["incomplete"]}
        result["value"] = result["voltage"]
        return result

    @cached_property
    def all_vmin(self):
        return {(wt, chip): self.chip_vmin(wt, chip)
                for wt in range(len(self.phases)) for chip in self.chips}

    def map(self, wt, pattern, kind):
        rows = []
        for chip in self.chips:
            row = {"x": chip[0], "y": chip[1]}
            die = self.die(wt, chip)
            base_cat = self.cat(0, chip) if self.wt_numbers[0] == 1 else None
            if kind in ("cat", "repair"):
                cat = self.cat(wt, chip, kind == "repair")
                row |= {"value": cat, "status": f"C{cat}" if cat else "No Data"}
            elif kind in ("vmin", "vmin_pattern", "vmin_merge"):
                result = (self.merged_chip_vmin(wt, chip) if kind == "vmin_merge"
                          else self.pattern_chip_vmin(wt, chip, pattern) if kind == "vmin_pattern"
                          else self.all_vmin[wt, chip])
                row |= result | {"value": result["voltage"]}
            else:
                mask = self.fail_maps[wt, pattern, chip]
                count = mask.bit_count() if isinstance(mask, int) else None
                status = mask if isinstance(mask, str) else "Fail" if count else "Pass"
                stats = self.map_stats.get((wt, pattern, chip), [0] * 5)
                current_cat = self.cat(wt, chip)
                gray = base_cat == 20 or current_cat in {10, 11, 14, 15, 16, 17, 20}
                endpoint = die.masks.get(self.config.patterns[pattern][-1].tno) if die else None
                blue = (kind in ("loss", "wr") and base_cat in (1, 2, 3, 4)
                        and current_cat not in (12, 13) and endpoint == 0 and not count and not any(stats))
                row |= {"value": count, "status": status, "wr": stats[:4], "loss": stats[-1],
                        "gray": gray, "blue": blue}
            rows.append(row)
        return rows

    def grid(self, chip):
        chosen, states = {}, defaultdict(dict)
        worst = {}
        tracked = {name for name in self.config.patterns if name.casefold() in ("scan", "march")}
        hard = set(bits(self.eligibility(len(self.phases) - 1, chip)[0]))
        for wt, number in enumerate(self.wt_numbers):
            incomplete = set()
            for pattern, blk, crossing, peak, _ in self.crossings(wt, chip):
                if pattern in tracked and crossing.voltage is not None:
                    key = number, pattern
                    previous = worst.get(key)
                    if previous is None or crossing.voltage > previous[0]:
                        worst[key] = crossing.voltage, [blk]
                    elif crossing.voltage == previous[0]:
                        previous[1].append(blk)
                state = states[blk].setdefault(wt, {"status": "No Data", "w": 0, "r": 0})
                if crossing.status in ("Fail", "No Vmin", "Below") or peak > 0:
                    state["status"] = "Fail"
                    if blk not in chosen and crossing.tno is not None:
                        chosen[blk] = asdict(crossing) | {"wt": number, "pattern": pattern}
                elif crossing.status == "Pass" and state["status"] != "Fail":
                    state["status"] = "Pass"
                if crossing.status == "No Data":
                    incomplete.add(blk)
            die = self.die(wt, chip)
            hard_at_wt = 0
            if die and not self.phases[wt].fbc_error:
                for test in self.config.hard:
                    hard_at_wt |= die.masks.get(test.tno, 0)
            for b in range(BLKS):
                addresses = {}
                for name, scope in self.config.patterns.items():
                    mask = self.fail_maps[wt, name, chip]
                    if isinstance(mask, int) and (mask >> b & 1):
                        for row in self.address_info(wt, chip, b, scope):
                            addresses[row["address"]] = row
                state = states[b].get(wt)
                if state:
                    if hard_at_wt >> b & 1:
                        state["status"] = "Fail"
                    elif b in incomplete and state["status"] == "Pass":
                        state["status"] = "No Data"
                    state["w"] = sum(bool(row["write"]) for row in addresses.values())
                    state["r"] = sum(bool(row["read"]) for row in addresses.values())
        worst_by_block = defaultdict(list)
        for (number, pattern), (voltage, blocks) in worst.items():
            for blk in blocks:
                worst_by_block[blk].append({"wt": number, "pattern": pattern, "voltage": voltage})
        return [{"blk": b, "trigger": chosen.get(b), "hard": b in hard, "worst_vmin": worst_by_block[b],
                 "states": [{"wt": number, **states[b].get(i, {"status": "No Data", "w": 0, "r": 0})}
                            for i, number in enumerate(self.wt_numbers)]} for b in range(BLKS)]

    def detail(self, wt, chip, blk):
        die = self.die(wt, chip)
        scans = []
        diagnostics = [asdict(crossing) | {"pattern": name, "peak": peak}
                       for name, _, crossing, peak, _ in self.crossings(wt, chip, blk=blk)]
        fbc90 = {name: asdict(crossing) | {"peak": peak}
                 for name, _, crossing, peak, _ in self.crossings(wt, chip, blk=blk, mode="FBC90%")}
        state = {row["pattern"]: row["status"] for row in diagnostics}
        for pattern, scope in self.config.patterns.items():
            judge = fbc90[pattern]
            valid = judge["status"] in ("Pass", "Fail", "No Vmin")
            cumulative = 0
            for t in scope:
                values = die.fbc.get(t.tno) if die else None
                fbc = values[blk] if values is not None else None
                cumulative = max(cumulative, fbc or 0)
                ratio = (cumulative / judge["peak"] if judge["peak"] else 0.0) if valid else None
                scans.append({"pattern": pattern, "tno": t.tno, "func": t.name, "v": t.voltage,
                              "fbc": fbc, "accumulated": ratio, "state": state[pattern]})
        hard_fail_tests = []
        for number, phase in zip(self.wt_numbers, self.phases):
            hard_die = phase.chips.get(chip)
            if hard_die is None:
                continue
            for test in self.config.hard:
                values = hard_die.fbc.get(test.tno)
                if values is not None and values[blk] > 0:
                    hard_fail_tests.append({"wt": number, "tno": test.tno, "func": test.name,
                                            "voltage": test.voltage, "fbc": values[blk], "cat": test.cat})
        merged = self.merged_fbc90(wt, chip, blk) if len([n for n in self.config.patterns if n.casefold() in ("scan", "march")]) == 2 else None
        return {"sweep": scans, "crossings": diagnostics, "fbc90": fbc90,
                "merged_fbc90": asdict(merged) if merged else None, "hard_fail_tests": hard_fail_tests,
                "coverage": [self.audit_one(wt, name, chip, blk) for name in self.config.patterns
                             if isinstance((mask := self.fail_maps[wt, name, chip]), int) and mask >> blk & 1]}

    def address_rows(self, chip=None):
        for x, y in [chip] if chip is not None else self.chips:
            dies = [self.die(wt, (x, y)) for wt in range(len(self.phases))]
            blocks = set().union(*(d.addresses.keys() for d in dies if d))
            category = self.cat(0, (x, y)) if self.wt_numbers[0] == 1 else None
            for b in sorted(blocks):
                groups = [d.addresses.get(b, {}) if d else {} for d in dies]
                for addr in sorted(set().union(*groups)):
                    yield (x, y, *addr, category, tuple(g.get(addr, set()) for g in groups))

    def fbc_rows(self, chip=None):
        for x, y in [chip] if chip is not None else self.chips:
            dies = [self.die(wt, (x, y)) for wt in range(len(self.phases))]
            for b in range(BLKS):
                yield (x, y, b, *(
                    d.fbc[t.tno][b] if d and t.tno in d.fbc else None
                    for d in dies for t in self.config.tests))


def load_wafer(sources, config, *, full=True, source_mode="full", report=lambda _: None):
    ordered = sorted(sources, key=lambda item: item.step)
    if not 1 <= len(ordered) <= 3 or len({x.step for x in ordered}) != len(ordered):
        raise ValueError("同一 Lot／Wafer 需 1～3 份 ASC，且 STEP 不可重複。")
    if len({x.key for x in ordered}) != 1:
        raise ValueError("完整分析需選擇同一 Lot、同一 Wafer 的 1～3 份 ASC。")
    phase_data = []
    for wt, source in sorted(zip(phase_numbers(ordered), ordered), key=lambda phase: phase[0]):
        report(f"讀取 WT{wt} · {source.path.name}")
        phase_data.append(read_asc(source, config, addresses=source_mode != "fbc",
                                   fbc=source_mode != "address", report=report))
    wafer = Wafer(config, tuple(phase_data), full, source_mode)
    if not wafer.chips:
        raise ValueError("ASC 內找不到 Chip X/Y。")
    return wafer
