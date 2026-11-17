"""Publication figures and an editable workbook for one WT/Chip/BLK/Pattern."""
from __future__ import annotations

from datetime import date
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

from engine import MATCH_LABELS, fbc_voltage_comparison, match_counts_by_voltage, voltage_text
from exports import output_path

CURVE = "#204f78"
THRESHOLD = "#9b422e"
INK = "#202630"
GRID = "#dde2e7"
HATCHES = ("", "//", "..", "xx", "\\\\", "++", "oo")

MATCH_COLORS = ("#35638a", "#ce8653", "#725b83", "#d7dce3")

def voltage_units(value):
    return "Unspecified" if value is None else f"{voltage_text(value)} V"


def judge_summary(judge):
    if judge["tno"] is not None:
        return f'First crossing at {voltage_units(judge["voltage"])}  |  {judge["func"]}  |  TNO {judge["tno"]}'
    if judge["status"] == "Pass":
        return "All pass  |  Peak FBC 0"
    return "FBC90% unavailable  |  " + judge["status"]


def write_figures(pdf, png, title, stations, judge, wr_matches, comparison):
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator, PercentFormatter

    runs = []
    for voltage, records in groupby(enumerate(stations), key=lambda indexed: indexed[1]["v"]):
        indexes = [index for index, _ in records]
        runs.append(((indexes[0] + indexes[-1]) / 2, voltage_units(voltage)))
    groups = comparison["groups"]
    series = comparison["series"]
    width = min(22, max(10, 0.76 * max(len(runs), len(groups), len(wr_matches)) + 2.5))
    with rc_context({
        "font.family": "serif", "font.serif": ["STIXGeneral", "Microsoft JhengHei", "DejaVu Serif"],
        "font.size": 14, "mathtext.fontset": "stix", "pdf.fonttype": 42, "text.parse_math": False,
        "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK, "text.color": INK,
    }):
        fig = Figure(figsize=(width, 12.3), layout="constrained", facecolor="white")
        FigureCanvasAgg(fig)
        fig.get_layout_engine().set(w_pad=0.17, h_pad=0.13, hspace=0.07)
        fig.suptitle(title, fontsize=21, weight="bold")
        curve, bars, match_plot = fig.subplots(3, 1)
        for axis in (curve, bars, match_plot):
            axis.spines[["top", "right"]].set_visible(False)
            axis.spines[["bottom", "left"]].set_color(INK)
            axis.set_axisbelow(True)
            axis.grid(axis="y", color=GRID, linewidth=0.7)
            axis.tick_params(labelsize=14, length=4, width=0.8)
            axis.set_xlabel("Test voltage (config order)", fontsize=16, labelpad=8)

        curve.set_title("(a)  FBC90% accumulation\n" + judge_summary(judge), loc="left", fontsize=17, pad=12)
        curve.set_ylabel("Cumulative FBC (%)", fontsize=16)
        curve.set_ylim(0, 1.06)
        curve.set_yticks((0, 0.25, 0.50, 0.75, 0.90, 1))
        curve.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
        curve.set_xticks([x for x, _ in runs], [label for _, label in runs],
                         rotation=35 if len(runs) > 15 else 0)
        curve.set_xlim(-0.55, max(0.55, len(stations) - 0.45))
        if stations[0]["accumulated"] is not None:
            y = [row["accumulated"] for row in stations]
            curve.plot(range(len(y)), y, color=CURVE, marker="o", markerfacecolor="white",
                       markersize=5, linewidth=1.9, zorder=3)
            if judge["tno"] is not None:
                hit = next(i for i, row in enumerate(stations) if row["tno"] == judge["tno"])
                curve.axhline(0.9, color=THRESHOLD, linestyle=(0, (5, 3)), linewidth=1.1)
                curve.plot(hit, y[hit], color=THRESHOLD, marker="D", markersize=7,
                           markeredgecolor="white", zorder=4)
        else:
            curve.text(0.5, 0.5, "No valid accumulation for this BLK", transform=curve.transAxes,
                       ha="center", va="center", color="#555e69", fontsize=15)

        chart_title = "(b)  " + comparison["title"]
        bars.set_title(chart_title, loc="left", fontsize=17, pad=12)
        bars.set_ylabel("Fail bit count (FBC)", fontsize=16)
        bars.set_xlabel("Voltage (V)", fontsize=16, labelpad=12)
        labels = [voltage_units(group["voltage"]) for group in groups]
        bars.set_xticks(range(len(labels)), labels, rotation=90)
        bars.set_xlim(-0.45, max(1, len(labels)) - 0.55)
        recorded = [row["fbc"] for group in groups for row in group["stations"]]
        bars.set_ylim(0, max(1, 1.16 * max(recorded, default=0)))
        bars.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        plotted = set()
        for index, group in enumerate(groups):
            rows = group["stations"]
            slot = 0.90 / max(1, len(rows))
            for i, row in enumerate(rows):
                item = series[row["series"]]
                series_label = item["label"]
                x = index + (i - (len(rows) - 1) / 2) * slot
                bar = bars.bar(x, row["fbc"], width=slot * 0.86, color=item["color"],
                               hatch=HATCHES[item["style"] % len(HATCHES)],
                               edgecolor=INK, linewidth=0.55, label=series_label if series_label not in plotted else None)
                if row["fbc"] and len(recorded) <= 18:
                    bars.bar_label(bar, labels=[f'{row["fbc"]:,}'], padding=3, fontsize=12)
                if row["fbc"] == 0:
                    bars.plot(x, 0, marker="_", markersize=6, color=item["color"], clip_on=False)
                plotted.add(series_label)
        if plotted:
            bars.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncols=min(len(plotted), 4),
                        frameon=False, fontsize=12, borderaxespad=0)
            bars.set_title(chart_title, loc="left", fontsize=17, pad=14 + 15 * ((len(plotted) + 3) // 4))
        else:
            bars.text(0.5, 0.5, "No test voltage with measured FBC", transform=bars.transAxes,
                      ha="center", va="center", color="#555e69", fontsize=15)
        match_plot.set_title("(c)  W/R match by test voltage", loc="left", fontsize=17, pad=29)
        match_plot.set_ylabel("Captured address count", fontsize=16)
        match_plot.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        match_plot.set_xlim(-0.55, max(1, len(wr_matches)) - 0.45)
        match_plot.set_xticks(range(len(wr_matches)), [voltage_units(row["voltage"]) for row in wr_matches],
                             rotation=35 if len(wr_matches) > 15 else 0)
        matched_totals = [sum(row["counts"]) for row in wr_matches]
        match_plot.set_ylim(0, max(1, 1.16 * max(matched_totals, default=0)))
        if any(matched_totals):
            bottom = [0] * len(wr_matches)
            for index, (label, color, hatch) in enumerate(zip(MATCH_LABELS, MATCH_COLORS, HATCHES)):
                values = [row["counts"][index] for row in wr_matches]
                bars_at_voltage = match_plot.bar(range(len(wr_matches)), values, bottom=bottom, width=0.55,
                    color=color, hatch=hatch, edgecolor=INK, linewidth=0.55, label=label)
                bottom = [base + height for base, height in zip(bottom, values)]
            if len(wr_matches) <= 18:
                match_plot.bar_label(bars_at_voltage, labels=[f"{total:,}" if total else "" for total in matched_totals],
                                     padding=3, fontsize=12)
            match_plot.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncols=len(MATCH_LABELS),
                              frameon=False, fontsize=12, borderaxespad=0)
        else:
            match_plot.text(0.5, 0.5, "No Function fail addresses were captured", transform=match_plot.transAxes,
                            ha="center", va="center", color="#555e69", fontsize=15)
        match_plot.set_xlabel("Test voltage (config order)\nUnique captured Function fail addresses per voltage.",
                              fontsize=14, labelpad=8)
        fig.savefig(pdf, metadata={"Title": title})
        fig.savefig(png, dpi=300)


def write_workbook(path, title, stations, judge, matches, wr_matches, comparison):
    from xlsxwriter import Workbook

    with Workbook(path, {"strings_to_formulas": False, "strings_to_urls": False}) as book:
        figures = book.add_worksheet("Figures")
        sweep = book.add_worksheet("Sweep Data")
        addresses = book.add_worksheet("Fail Address Match")
        header = book.add_format({"font_name": "Cambria", "font_size": 12, "bold": True,
                                  "bg_color": CURVE, "font_color": "white", "valign": "vcenter"})
        title_fmt = book.add_format({"font_name": "Cambria", "font_size": 19, "bold": True,
                                     "font_color": INK, "valign": "vcenter"})
        basic = book.add_format({"font_name": "Cambria", "font_size": 12, "font_color": INK})
        pct = book.add_format({"font_name": "Cambria", "font_size": 12, "num_format": "0.0%"})
        volts = book.add_format({"font_name": "Cambria", "font_size": 12, "num_format": "0.00####"})
        for ws in (figures, sweep, addresses):
            ws.hide_gridlines(2)
            ws.set_default_row(19)

        sweep.set_column("A:A", 12, basic)
        sweep.set_column("B:B", 20, basic)
        sweep.set_column("C:D", 13, basic)
        sweep.set_column("E:E", 22, basic)
        sweep.set_column("F:F", 14, volts)
        sweep.set_column("G:G", 12, basic)
        sweep.set_column("H:I", 15, pct)
        sweep.set_column("J:J", 16, pct)
        sweep.set_row(0, 24)
        sweep.write_row(0, 0, ("Sequence", "Voltage / TNO", "TNO", "FBC90% hit", "Function", "Voltage (V)",
                               "FBC", "Accumulated", "Threshold", "First crossing"), header)
        for idx, row in enumerate(stations, 1):
            hit = row["tno"] == judge["tno"]
            ratio = row["accumulated"]
            sweep.write_row(idx, 0, (idx, f'{voltage_units(row["v"])} / {row["tno"]}', row["tno"],
                                     "Yes" if hit else None, row["func"], row["v"], row["fbc"], ratio,
                                     0.9 if judge["tno"] is not None else None, ratio if hit else None))
        sweep.freeze_panes(1, 2)
        sweep.autofilter(0, 0, len(stations), 9)
        comparison_groups = comparison["groups"]
        comparison_series = comparison["series"]
        if comparison_series:
            sweep.set_column("L:L", 16, volts)
            sweep.set_column(12, 11 + len(comparison_series), 24, basic)
            sweep.write_row(0, 11, ("Voltage / TNO", *(item["label"] for item in comparison_series)), header)
            for row_index, group in enumerate(comparison_groups, 1):
                sweep.write_string(row_index, 11, f'{voltage_text(group["voltage"])} V / {group["tno"]}')
                for station in group["stations"]:
                    sweep.write_number(row_index, 12 + station["series"], station["fbc"])

        addresses.set_column("A:D", 10, basic)
        addresses.set_column("E:I", 24, basic)
        addresses.set_row(0, 24)
        addresses.write_row(0, 0, ("BLK", "WL", "BL", "IO", "Function Voltage (V)", "Function TNO",
                                    "Write TNO", "Read TNO", "Classification"), header)
        last_address = 0
        for last_address, match in enumerate(matches, 1):
            addresses.write_row(last_address, 0, (*match["address"], ", ".join(map(voltage_text, match["function_voltages"])),
                *(", ".join(map(str, match[key])) for key in ("function", "write", "read")), match["category"]))
        addresses.freeze_panes(1, 4)
        addresses.autofilter(0, 0, last_address, 8)
        addresses.set_column("K:K", 16, volts)
        addresses.set_column("L:P", 21, basic)
        addresses.write_row(0, 10, ("Voltage (V)", *MATCH_LABELS, "Total Captured"), header)
        for idx, row in enumerate(wr_matches, 1):
            voltage = row["voltage"] if row["voltage"] is not None else "Unspecified"
            addresses.write_row(idx, 10, (voltage, *row["counts"], sum(row["counts"])))

        figures.set_column("A:Q", 12, basic)
        figures.set_row(0, 36)
        figures.merge_range("A1:Q1", title, title_fmt)
        figures.merge_range("A2:Q2", judge_summary(judge), basic)
        figures.merge_range("A3:Q3", "Accumulation uses the maximum FBC observed through each station, divided by the sweep peak.", basic)
        figures.merge_range("A4:Q4", "W/R counts each captured Function fail address once per voltage.", basic)
        font = {"name": "Cambria", "size": 13, "color": INK}
        axis_title = font | {"size": 15, "bold": True}
        last = len(stations)
        categories = ["Sweep Data", 1, 1, last, 1]

        def base_chart(kind, caption, units, maximum=None, fmt=None, *,
                       x_title="Test voltage / TNO (config order)", count=None, subtype="stacked"):
            chart = book.add_chart({"type": kind, **({"subtype": subtype} if kind == "column" else {})})
            chart.set_title({"name": caption, "name_font": font | {"size": 19, "bold": True}})
            chart.set_size({"width": max(1000, min((count if count is not None else last) * 47 + 145, 2800)), "height": 460})
            chart.set_x_axis({"name": x_title, "name_font": axis_title,
                              "num_font": font | {"rotation": -45}, "line": {"color": INK}})
            chart.set_y_axis({"name": units, "name_font": axis_title, "num_font": font, "min": 0,
                              "major_gridlines": {"visible": True, "line": {"color": GRID}},
                              **({"max": maximum, "num_format": fmt} if maximum else {})})
            chart.set_legend({"position": "top", "font": font})
            chart.show_blanks_as("gap")
            return chart

        chart_row = 5
        if any(row["accumulated"] is not None for row in stations):
            chart = base_chart("line", "(a) FBC90% accumulation", "Cumulative FBC (%)", 1, "0%")
            chart.add_series({"name": "Accumulated FBC", "categories": categories,
                              "values": ["Sweep Data", 1, 7, last, 7], "line": {"color": CURVE, "width": 2},
                              "marker": {"type": "circle", "size": 5, "fill": {"color": "#ffffff"},
                                         "border": {"color": CURVE}}})
            if judge["tno"] is not None:
                chart.add_series({"name": "90% threshold", "categories": categories,
                                  "values": ["Sweep Data", 1, 8, last, 8],
                                  "line": {"color": THRESHOLD, "dash_type": "dash"}})
                chart.add_series({"name": "First crossing", "categories": categories,
                                  "values": ["Sweep Data", 1, 9, last, 9], "line": {"none": True},
                                  "marker": {"type": "diamond", "size": 8, "fill": {"color": THRESHOLD},
                                             "border": {"color": THRESHOLD}}})
            figures.insert_chart(chart_row, 0, chart)
            chart_row += 24

        if comparison_series:
            voltage_order = "Config order"
            chart = base_chart("column", "(b) " + comparison["title"], "Fail bit count (FBC)",
                               x_title=f"Test voltage / TNO · {voltage_order}",
                               count=len(comparison_groups), subtype="clustered")
            for index, item in enumerate(comparison_series):
                chart.add_series({"name": item["label"],
                                  "categories": ["Sweep Data", 1, 11, len(comparison_groups), 11],
                                  "values": ["Sweep Data", 1, 12 + index, len(comparison_groups), 12 + index],
                                  "fill": {"color": item["color"]},
                                  "border": {"color": INK, "width": 0.5}})
            figures.insert_chart(chart_row, 0, chart)
            chart_row += 24
        else:
            figures.write(chart_row, 0, "No test voltage with measured FBC.", basic)
            chart_row += 2

        if wr_matches:
            chart = base_chart("column", "(c) W/R match by test voltage", "Captured address count",
                               x_title="Test voltage (V) · Config order", count=len(wr_matches))
            for index, (label, color) in enumerate(zip(MATCH_LABELS, MATCH_COLORS)):
                chart.add_series({"name": label,
                                  "categories": ["Fail Address Match", 1, 10, len(wr_matches), 10],
                                  "values": ["Fail Address Match", 1, 11 + index, len(wr_matches), 11 + index],
                                  "fill": {"color": color}, "border": {"color": INK, "width": 0.5}})
            figures.insert_chart(chart_row, 0, chart)
        else:
            figures.write(chart_row, 0, "No Function fail addresses were captured.", basic)


def save_pattern_report(wafer, folder, wt, chip, blk, pattern, kind):
    if kind not in ("charts", "excel"):
        raise ValueError("不支援的 Pattern 匯出格式。")
    x, y = chip
    scope = f"{wafer.label}  |  WT{wafer.wt_numbers[wt]}  |  X{x} Y{y}  |  BLK {blk}"
    title = f"{pattern}  |  {scope}"
    stem = f"{wafer.label}_WT{wafer.wt_numbers[wt]}_X{x}Y{y}_BLK{blk}_{pattern}"
    info = wafer.detail(wt, chip, blk)
    stations = [row for row in info["sweep"] if row["pattern"] == pattern]
    judge = info["fbc90"][pattern]
    comparison = fbc_voltage_comparison(info["sweep"], pattern)
    pattern_scope = wafer.config.patterns[pattern]
    matches = list(wafer.pattern_matches(wt, chip, blk, pattern_scope))
    wr_matches = match_counts_by_voltage(pattern_scope, matches)
    folder = Path(folder) / f"Analysis_{date.today():%Y%m%d}"
    folder.mkdir(parents=True, exist_ok=True)
    extensions = ("pdf", "png") if kind == "charts" else ("xlsx",)
    with TemporaryDirectory(dir=folder, prefix=".sram-") as temp:
        staged = [Path(temp) / f"pattern.{ext}" for ext in extensions]
        if kind == "charts":
            write_figures(*staged, title, stations, judge, wr_matches, comparison)
        else:
            write_workbook(staged[0], title, stations, judge, matches, wr_matches, comparison)
        results = []
        try:
            for file, ext in zip(staged, extensions):
                target = output_path(folder, stem, ext)
                file.rename(target)
                results.append(target)
        except OSError:
            for path in results:
                path.unlink()
            raise
    return results
