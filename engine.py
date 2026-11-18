
"""Streaming ASC reader and SRAM analysis shared by the UI and exports."""
from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import cached_property
from itertools import combinations
from math import isfinite
from pathlib import Path
import csv
import re
from statistics import StatisticsError, correlation
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
            raise ValueError("Select FBC0 through FBC10 or FBC90%.")
        tests = []
        used = set()
        for i, row in enumerate(rows, 2):
            raw = row.get("tno")
            if raw is None or str(raw).strip() == "":
                if any(str(row.get(key) if row.get(key) is not None else "").strip()
                       for key in ("name", "voltage", "cat", "stop")):
                    raise ValueError(f"Configuration row {i} has data but no TNO.")
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
                raise ValueError(f"Invalid configuration row {i}. Check TNO, Function, Voltage, Fail Cat and Stop Sign.") from exc
            if tno in used:
                raise ValueError(f"Duplicate TNO {tno}.")
            used.add(tno)
            tests.append(Test(group, tno, name, voltage, cat, stop if full else ""))
        if not tests:
            raise ValueError("Configuration requires at least one TNO.")
        result = cls(tuple(sorted(tests, key=lambda t: t.group != "Monitor")), mode)
        result.patterns
        if full and not result.patterns:
            raise ValueError("Function requires at least one Pattern endpoint (Stop Sign).")
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
                    raise ValueError(f"Duplicate Stop Sign {name}.")
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

    @cached_property
    def hard_voltage(self):
        return max((test.voltage for test in self.hard if test.voltage is not None), default=None)

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
        raise ValueError(f"ASC file not found: {path.name}。")
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
        raise ValueError(f"{path.name} is missing a valid LOT, WNO or STEP.")
    program = fields.get("PROGRAM", third)
    version_pos = program.upper().find("VER_")
    version = program[version_pos + 4:version_pos + 6]
    version = version.upper() if version_pos >= 0 and re.fullmatch(r"[A-Za-z]{2}", version) else "Unknown"
    labels = re.findall(r"(?:^|[^a-z0-9])WT([123])(?=$|[^a-z0-9])", path.stem, re.I)
    if len(labels) > 1:
        raise ValueError(f"{path.name} has ambiguous WT labels.")
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
            phase.diagnostic(f"Line {start}: TNO {tno} X{chip[0]} Y{chip[1]} has {len(record)} FBC columns; expected 256.")
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
                report(f"{source.path.name} · {n:,} lines · {fbc_total:,} FBC records")
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
                        phase.diagnostic(f"Line {n}: invalid CATLST format.")
                    else:
                        category = cat[1].find("1") + 1
                        if category and die.cat and die.cat != category:
                            phase.diagnostic(f"Line {n}: conflicting CATLST for X{chip[0]} Y{chip[1]}.")
                        elif category:
                            die.cat = category
            if match:
                finish()
                if tags.get("TNO") is None:
                    phase.diagnostic(f"Line {n}: FBC header has no TNO.")
                elif tags["TNO"] in selected:
                    if chip is None:
                        phase.diagnostic(f"Line {n}: FBC for TNO {tags['TNO']} has no valid X/Y.")
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
                    phase.diagnostic(f"Line {n}: FBC must be a nonnegative integer.")
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
    relation: str = ""
    test_voltage: float | None = None
    voltage_tno: int | None = None
    voltage_rule: str = ""


def flow_voltage_references(scope):
    """Map terminal recovery items to the last Go/No-Go minimum in their Stop Sign flow."""
    references = {}
    start = 0
    for end, test in enumerate(scope):
        if not test.stop and end != len(scope) - 1:
            continue
        segment = scope[start:end + 1]
        if segment and all(item.voltage is not None for item in segment):
            minimum = min(item.voltage for item in segment)
            reference = max(i for i in range(start, end + 1) if scope[i].voltage == minimum)
            for index in range(reference + 1, end + 1):
                references[index] = reference
        start = end + 1
    return references


def vmin(scope, values, mode, *, hard_voltage=None):
    available = [v for v in values if v is not None]
    peak = max(available, default=0)
    if mode == "FBC90%":
        if len(available) != len(scope):
            return Crossing(None, None, None, None, "No Data")
        threshold = max(1, (9 * peak + 9) // 10)
    else:
        threshold = max(1, int(mode[3:]))
    references = flow_voltage_references(scope)
    highest = max((test.voltage for i, test in enumerate(scope)
                   if i not in references and test.voltage is not None), default=None)
    voltage_complete = all(test.voltage is not None for test in scope)
    group = previous = None
    missing = False
    for index, (test, value) in enumerate(zip(scope, values)):
        if test.voltage is None:
            group = previous = None
        elif group is None:
            group = test.voltage
        elif test.voltage != group:
            previous, group = group, test.voltage
        if value is None:
            missing = True
        elif value >= threshold:
            if not missing and index in references:
                reference = scope[references[index]]
                return Crossing(test.tno, reference.voltage, test.name, value, "Fail", "", test.voltage,
                                reference.tno, "terminal-recovery")
            if not missing and voltage_complete and hard_voltage is not None and test.voltage == highest:
                return Crossing(test.tno, hard_voltage, test.name, value, "Fail", ">=", test.voltage)
            voltage = previous if mode == "FBC0" else test.voltage
            status = "No Data" if missing else ("No Vmin" if voltage is None else "Fail")
            return Crossing(test.tno, None if missing else voltage, test.name, value, status)
    return Crossing(None, None, None, None, "No Data" if missing else ("Below" if peak else "Pass"))


def voltage_distribution(readings, voltage_ladders):
    """Box statistics for exact FBC90% Vmin and high-side Tail candidates."""
    exact = {blk: crossing.voltage for blk, (_, crossing) in readings.items()
             if crossing.voltage is not None and not crossing.relation}
    values = sorted(exact.values())
    stats = {"count": len(values), "minimum_samples": 4, "minimum_steps": 2}
    if not values:
        return stats, {}, []

    def quartile(n):
        i, fraction = divmod((len(values) - 1) * n, 4)
        return round(values[i] + fraction * (values[min(i + 1, len(values) - 1)] - values[i]) / 4, 12)

    q1, median, q3 = (quartile(n) for n in (1, 2, 3))
    stats.update(q1=q1, median=median, q3=q3, low=values[0], high=values[-1])
    if len(values) < stats["minimum_samples"]:
        return stats, {}, []
    iqr = q3 - q1
    lower, upper = round(q1 - 1.5 * iqr, 12), round(q3 + 1.5 * iqr, 12)
    ladders = {name: sorted({v for v in voltages if v is not None})
               for name, voltages in voltage_ladders.items()}
    outliers = {}
    for blk, voltage in exact.items():
        if voltage > upper:
            ladder = ladders.get(readings[blk][0], ladders.get(None, ()))
            outliers[blk] = bisect_right(ladder, voltage) - bisect_right(ladder, median)
    tail = [blk for blk, steps in sorted(outliers.items()) if steps >= stats["minimum_steps"]]
    stats.update(lower_fence=lower, upper_fence=upper,
                 low=next(v for v in values if v >= lower),
                 high=next(v for v in reversed(values) if v <= upper))
    return stats, outliers, tail


def select_vmin(readings, tail=()):
    excluded = set(tail)
    candidates = (blk for blk, (_, crossing) in readings.items()
                  if blk not in excluded and crossing.voltage is not None)
    blk = max(candidates, key=lambda b: (readings[b][1].voltage, readings[b][1].relation == ">=", -b),
              default=None)
    pattern, crossing = readings[blk] if blk is not None else (None, None)
    return {"blk": blk, "pattern": pattern, "voltage": crossing.voltage if crossing else None,
            "tno": crossing.tno if crossing else None, "func": crossing.func if crossing else None,
            "relation": crossing.relation if crossing else "",
            "test_voltage": crossing.test_voltage if crossing else None,
            "voltage_tno": crossing.voltage_tno if crossing else None,
            "voltage_rule": crossing.voltage_rule if crossing else ""}


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
        raise ValueError("ASC filename WT labels must be unique within a Lot/Wafer.")
    if not claimed:
        return tuple(range(1, len(labels) + 1))
    if len(claimed) == len(labels):
        return labels
    candidates = [numbers for numbers in combinations((1, 2, 3), len(labels))
                  if all(label is None or label == number for label, number in zip(labels, numbers))]
    if len(candidates) != 1:
        raise ValueError("Cannot resolve WT from STEP. Label ASC filenames with WT1, WT2 or WT3.")
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
                yield name, b, vmin(scope, values, mode, hard_voltage=self.config.hard_voltage), peak, sweep_complete
            prior_valid &= endpoint is not None
            prior |= endpoint or 0

    def chip_vmin(self, wt, chip):
        return self._chip_vmin_data(wt, chip)[0]

    def _chip_crossings(self, wt, chip, mode):
        peaks, unknown, best = [0] * BLKS, set(), {}
        for name, blk, crossing, peak, complete in self.crossings(wt, chip, mode=mode):
            if crossing.status in ("Hard Fail", "Prior WT", "Prior Pattern"):
                continue
            if not complete:
                unknown.add(blk)
            peaks[blk] = max(peaks[blk], peak)
            previous = best.get(blk)
            old = previous[1] if previous else None
            if crossing.voltage is not None and (old is None or old.voltage is None or
                    (crossing.voltage, crossing.relation == ">=") > (old.voltage, old.relation == ">=")):
                best[blk] = name, crossing
            elif crossing.status == "No Vmin" and old is None:
                best[blk] = name, crossing
        return best, peaks, unknown

    def _chip_vmin_data(self, wt, chip):
        hard, past, _ = self.eligibility(wt, chip)
        readings, peaks, unknown = self._chip_crossings(wt, chip, self.config.mode)
        fbc90, _, fbc90_unknown = ((readings, peaks, unknown) if self.config.mode == "FBC90%"
                                  else self._chip_crossings(wt, chip, "FBC90%"))
        # An incomplete Pattern cannot establish a chip-wide maximum for this BLK.
        fbc90 = {blk: hit for blk, hit in fbc90.items() if blk not in fbc90_unknown}
        ladders = {name: tuple(test.voltage for test in tests)
                   for name, tests in self.config.patterns.items()}
        stats, outliers, tail = voltage_distribution(fbc90, ladders)
        pool = [blk for blk in range(BLKS) if not ((hard | past) >> blk & 1)]
        kept = set(pool).difference(tail)
        selected = select_vmin(readings, tail)
        incomplete = len(unknown.intersection(kept))
        status = ("Vmin" if selected["blk"] is not None else "No BLK" if not kept
                  else "No Data" if incomplete else "No Vmin" if any(b in readings for b in kept)
                  else "Below" if any(peaks[b] for b in kept) else "Pass")
        summary = selected | {"status": status, "cutoff": stats.get("upper_fence"),
                              "tail": tail, "hard": list(bits(hard)), "prior": past.bit_count(),
                              "remaining": len(kept), "incomplete": incomplete,
                              "before_tail": select_vmin(readings)}
        return summary, readings, peaks, unknown, past, fbc90, stats, outliers

    @cached_property
    def monitor_tnos(self):
        return {side: {tno for tno, group in self.config.monitor_sides.items() if group == side}
                for side in ("W", "R")}

    @property
    def monitor_scopes(self):
        names = {name.casefold(): name for name in self.config.patterns}
        scopes = {f"pattern:{names[key]}": label for key, label in (("scan", "Scan"), ("march", "March"))
                  if key in names}
        if len(scopes) == 2:
            scopes["merge"] = "Scan & March"
        return scopes

    def monitor_patterns(self, scope):
        if scope == "chip":
            return tuple(self.config.patterns)
        if scope == "merge":
            return tuple(name for name in self.config.patterns if name.casefold() in ("scan", "march"))
        return (scope.removeprefix("pattern:"),)

    def block_monitor_matches(self, wt, chip, patterns):
        """Count distinct captured Function addresses in eligible BLKs, by monitor category."""
        die = self.die(wt, chip)
        if die is None:
            return {}, None, None, None
        function_tnos = defaultdict(set)
        complete = True
        for name in patterns:
            mask = self.fail_maps[wt, name, chip]
            if not isinstance(mask, int):
                complete = False
                continue
            tnos = {test.tno for test in self.config.patterns[name]}
            complete &= tnos.issubset(die.fbc)
            for blk in bits(mask):
                function_tnos[blk].update(tnos)

        write_tnos, read_tnos = (self.monitor_tnos[side] for side in ("W", "R"))
        write_count = read_count = 0
        counts_by_block = {}
        for blk, addresses in die.addresses.items():
            function = function_tnos.get(blk, ())
            counts = [0] * len(MATCH_LABELS)
            for hits in addresses.values():
                write = not hits.isdisjoint(write_tnos)
                read = not hits.isdisjoint(read_tnos)
                write_count += write
                read_count += read
                if not hits.isdisjoint(function):
                    counts[GROUPS.index(observed_category(write, read))] += 1
            if any(counts):
                counts_by_block[blk] = counts

        def observed(tnos, count):
            return count if count or not tnos.isdisjoint(die.fbc) else None

        return (counts_by_block, len(function_tnos) if complete else None,
                observed(write_tnos, write_count), observed(read_tnos, read_count))

    def monitor_correlation(self, wt, scope, *, chips=None):
        if self.source_mode != "full":
            raise ValueError("Import complete FBC and Fail Address data.")
        patterns = self.monitor_patterns(scope)
        selected = set(self.chips) if chips is None else set(chips)
        if not selected.issubset(self.chips):
            raise ValueError("The selected Chip is not in the current wafer.")
        rows = []
        for chip in self.chips:
            if chip not in selected:
                continue
            counts_by_block, fail_blks, write, read = self.block_monitor_matches(wt, chip, patterns)
            counts = [sum(block[i] for block in counts_by_block.values()) for i in range(len(MATCH_LABELS))]
            total = sum(counts)
            rows.append({"x": chip[0], "y": chip[1], "write": write, "read": read,
                         "fail_blks": fail_blks, "address_blks": len(counts_by_block),
                         "function": total, "counts": counts, "complete": fail_blks is not None})
        totals = [sum(row["counts"][i] for row in rows) for i in range(len(MATCH_LABELS))]
        relationships = {}
        for side in ("write", "read"):
            points = [(row[side], row["function"]) for row in rows if row["complete"] and row[side] is not None]
            try:
                coefficient = correlation(*zip(*points)) if len(points) >= 2 else None
            except StatisticsError:
                coefficient = None
            relationships[side] = {"r": coefficient, "chips": len(points)}
        return {"wt": self.wt_numbers[wt], "patterns": patterns, "labels": MATCH_LABELS,
                "rows": rows, "counts": totals, "relationships": relationships}

    def vmin_distribution(self, wt, chip, scope="chip", *, with_matches=False):
        """Expose the exact FBC90% readings and the actual map Judge for the selected scope."""
        mode = self.config.mode if scope == "chip" else "FBC90%"
        if scope == "chip":
            summary, readings, peaks, unknown, past, fbc90, stats, outliers = self._chip_vmin_data(wt, chip)
        else:
            summary, readings, peaks, stats, outliers = self._pattern_vmin_data(wt, chip, scope)
            fbc90 = readings
            unknown, past = set(), 0
        hard = set(summary["hard"])
        tails = set(summary["tail"])
        entries = []
        for blk in range(BLKS):
            reading = readings.get(blk)
            if reading is None:
                status = ("Hard Fail" if blk in hard else "Prior WT" if past >> blk & 1
                          else "No Data" if blk in unknown else "Below" if peaks[blk] else "Pass")
                reading = None, Crossing(None, None, None, None, status)
            pattern, crossing = reading
            voltage90 = fbc90.get(blk)
            entries.append(asdict(crossing) | {
                "blk": blk, "pattern": pattern, "peak_fbc": peaks[blk],
                "tail": blk in tails, "judge": blk == summary["blk"],
                "fbc90_voltage": voltage90[1].voltage if voltage90 else None,
                "fbc90_relation": voltage90[1].relation if voltage90 else "",
                "steps_above_median": outliers.get(blk),
                "below_fence": bool(voltage90 and voltage90[1].voltage is not None
                                    and not voltage90[1].relation and "lower_fence" in stats
                                    and voltage90[1].voltage < stats["lower_fence"]),
            })
        if with_matches and self.source_mode == "full":
            matches, _, _, _ = self.block_monitor_matches(wt, chip, self.monitor_patterns(scope))
            for entry in entries:
                entry["matches"] = matches.get(entry["blk"], [0] * len(MATCH_LABELS))
        return {"summary": summary, "mode": mode, "entries": entries, "box": stats}

    def pattern_fbc_summary(self, wt, chip, pattern):
        """Classify a Chip from all raw 256-BLK FBC vectors, never captured addresses."""
        scope = self.config.patterns.get(pattern)
        die = self.die(wt, chip)
        if not scope or die is None or self.phases[wt].fbc_error:
            return {"status": "No Data", "fail_blks": 0, "complete": False}
        vectors = [die.fbc.get(test.tno) for test in scope]
        complete = all(vector is not None and len(vector) == BLKS for vector in vectors)
        fail = 0
        for vector in vectors:
            if vector is not None and len(vector) == BLKS:
                fail |= sum(1 << blk for blk, count in enumerate(vector) if count > 0)
        return {"status": "Fail" if fail else "Pass" if complete else "No Data",
                "fail_blks": fail.bit_count(), "complete": complete}

    def pattern_vmin_eligibility(self, wt, chip, pattern):
        """Scan-fail Chips and Scan-pass/March-fail Chips form separate Vmin cohorts."""
        key = pattern.casefold()
        if key not in ("scan", "march"):
            return "", ""
        scan = next((name for name in self.config.patterns if name.casefold() == "scan"), None)
        if key == "march":
            scan_state = self.pattern_fbc_summary(wt, chip, scan)
            if scan_state["status"] == "Fail":
                return "Not Applicable", "Scan has Fail BLKs; March Vmin requires Scan Pass."
            if scan_state["status"] != "Pass":
                return "No Data", "Complete Scan FBC is required to confirm Scan Pass."
        current = self.pattern_fbc_summary(wt, chip, pattern)
        if current["status"] == "Pass":
            return "Pass", pattern + " FBC is complete and all 256 BLKs pass at every Config TNO."
        if not current["complete"]:
            return "No Data", pattern + " FBC is missing or invalid; Vmin is unavailable."
        return "", ""

    def pattern_chip_vmin(self, wt, chip, pattern):
        return self._pattern_vmin_data(wt, chip, "pattern:" + pattern)[0]

    def _pattern_vmin_data(self, wt, chip, scope):
        hard, past, _ = self.eligibility(wt, chip)
        peaks = [0] * BLKS
        names = self.monitor_patterns(scope)
        voltages = (test.voltage for name in names for test in self.config.patterns[name])
        if scope == "merge":
            pattern, gate_status, reason = "Merge 90%", "", ""
            by_tno = {test.tno: name for name in names for test in self.config.patterns[name]}
            readings = {}
            for blk, crossing, peak in self._merged_fbc90_rows(wt, chip, range(BLKS)):
                readings[blk] = by_tno.get(crossing.tno), crossing
                peaks[blk] = peak
        else:
            pattern = names[0]
            gate_status, reason = self.pattern_vmin_eligibility(wt, chip, pattern)
            readings = {}
            for name, blk, crossing, peak, _ in self.crossings(wt, chip, mode="FBC90%"):
                if name == pattern:
                    readings[blk] = name, crossing
                    peaks[blk] = peak

        stats, outliers, tail = voltage_distribution(readings, {None: voltages})
        selected = select_vmin({} if gate_status else readings, tail)
        before_tail = select_vmin({} if gate_status else readings)
        kept = [crossing for blk, (_, crossing) in readings.items() if blk not in tail
                and crossing.status not in ("Hard Fail", "Prior WT", "Prior Pattern")]
        incomplete = sum(c.status == "No Data" for c in kept)
        if scope == "merge":
            status = "Vmin" if selected["blk"] is not None else "No Vmin"
        else:
            status = (gate_status or ("Vmin" if selected["blk"] is not None else "No BLK" if not kept
                      else "No Data" if incomplete else "No Vmin"))
            if not reason and selected["blk"] is None:
                reason = "No eligible BLK with a valid Vmin after exclusions."
        summary = selected | {"value": selected["voltage"], "status": status, "reason": reason,
                              "pattern": pattern, "cutoff": stats.get("upper_fence"), "tail": tail,
                              "hard": list(bits(hard)), "prior": past.bit_count(),
                              "remaining": len(kept), "incomplete": incomplete, "before_tail": before_tail}
        return summary, readings, peaks, stats, outliers

    def merged_fbc90(self, wt, chip, blk):
        return next(self._merged_fbc90_rows(wt, chip, (blk,)))[1]

    def _merged_fbc90_rows(self, wt, chip, blocks):
        """One 90% crossing over Scan and March in Config order (shared peak)."""
        names = self.monitor_patterns("merge")
        hard, past, complete = self.eligibility(wt, chip)
        phase = self.phases[wt]
        die = phase.chips.get(chip, ChipData())
        scope = [test for name in names for test in self.config.patterns[name]]
        vectors = [die.fbc.get(test.tno) for test in scope]
        available = (len(names) == 2 and complete and not phase.fbc_error
                     and all(vector is not None for vector in vectors))
        for blk in blocks:
            state = ("No Data" if len(names) != 2 else "Hard Fail" if hard >> blk & 1
                     else "Prior WT" if past >> blk & 1 else "" if available else "No Data")
            if state:
                yield blk, Crossing(None, None, None, None, state), 0
            else:
                values = [vector[blk] for vector in vectors]
                yield blk, vmin(scope, values, "FBC90%", hard_voltage=self.config.hard_voltage), max(values)

    def merged_chip_vmin(self, wt, chip):
        return self._pattern_vmin_data(wt, chip, "merge")[0]

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
            allowed = {pattern: not self.pattern_vmin_eligibility(wt, chip, pattern)[0] for pattern in tracked}
            for pattern, blk, crossing, peak, _ in self.crossings(wt, chip):
                if pattern in tracked and allowed[pattern] and crossing.voltage is not None:
                    key = number, pattern
                    previous = worst.get(key)
                    if previous is None or (crossing.voltage, crossing.relation == ">=") > (previous[0], previous[1] == ">="):
                        worst[key] = crossing.voltage, crossing.relation, [blk]
                    elif (crossing.voltage, crossing.relation) == previous[:2]:
                        previous[2].append(blk)
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
        for (number, pattern), (voltage, relation, blocks) in worst.items():
            for blk in blocks:
                worst_by_block[blk].append({"wt": number, "pattern": pattern, "voltage": voltage, "relation": relation})
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
        raise ValueError("A Lot/Wafer requires 1–3 ASC files with unique STEP values.")
    if len({x.key for x in ordered}) != 1:
        raise ValueError("Full analysis requires 1–3 ASC files from the same Lot and Wafer.")
    phase_data = []
    for wt, source in sorted(zip(phase_numbers(ordered), ordered), key=lambda phase: phase[0]):
        report(f"Reading WT{wt} · {source.path.name}")
        phase_data.append(read_asc(source, config, addresses=source_mode != "fbc",
                                   fbc=source_mode != "address", report=report))
    wafer = Wafer(config, tuple(phase_data), full, source_mode)
    if not wafer.chips:
        raise ValueError("No Chip X/Y found in ASC.")
    return wafer
