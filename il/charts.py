"""Server-rendered SVG line charts: no JavaScript, readable without CSS, themable with it."""
import math
from html import escape


def year_frac(d):
    """'2012' -> 2012.0, '2012-07' -> 2012.5, '2012-07-01' -> 2012.496."""
    parts = str(d).split("-")
    y = int(parts[0])
    if len(parts) == 1:
        return float(y)
    m = int(parts[1])
    day = int(parts[2]) if len(parts) > 2 else 1
    return y + (m - 1) / 12.0 + (day - 1) / 365.0


def fmt_value(v, unit=""):
    a = abs(v)
    if a >= 1e9:
        s = "%.3g B" % (v / 1e9)
    elif a >= 1e6:
        s = "%.3g M" % (v / 1e6)
    elif a >= 10000:
        s = "{:,.0f}".format(v)
    elif a >= 100:
        s = "%.0f" % v
    elif a >= 1:
        s = ("%.2f" % v).rstrip("0").rstrip(".")
    else:
        s = ("%.3f" % v).rstrip("0").rstrip(".")
    if unit.startswith("$"):
        return "$" + s + unit[1:]
    return s + (" " + unit if unit else "")


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fmt_date(d):
    """'2019-12-01' -> 'Dec 2019', '2019-12' -> 'Dec 2019', '2019' -> '2019'."""
    parts = str(d).split("-")
    if len(parts) >= 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return "%s %s" % (MONTHS[int(parts[1]) - 1], parts[0])
    return str(d)


def tick_label(v, unit):
    """Short axis label: the number, with a leading $ for money units; the unit itself is in the caption."""
    a = abs(v)
    if a >= 1e9:
        s = "%.3gB" % (v / 1e9)
    elif a >= 1e6:
        s = "%.3gM" % (v / 1e6)
    elif a >= 1e4:
        s = "%.3gk" % (v / 1e3)
    elif a >= 100:
        s = "%.0f" % v
    elif a >= 1:
        s = ("%.2f" % v).rstrip("0").rstrip(".")
    else:
        s = ("%.3f" % v).rstrip("0").rstrip(".")
    if unit.startswith("$"):
        return "$" + s
    if unit == "%":
        return s + "%"
    return s


def _nice_ticks(lo, hi, n=4):
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=mag * 10)
    start = math.floor(lo / step) * step
    ticks = []
    t = start
    while t <= hi + step * 0.001:
        if t >= lo - step * 0.001:
            ticks.append(round(t, 10))
        t += step
    return ticks


def line_chart(points, label, unit="", log=False, marks=(), threshold=None, width=640, height=250):
    """points: [(date_str, value)] sorted or not. Returns an <svg> string, or '' with <2 points."""
    pts = sorted(((year_frac(d), float(v), d) for d, v in points if v is not None), key=lambda p: p[0])
    if log:
        pts = [p for p in pts if p[1] > 0]
    if len(pts) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 50, 18, 16, 34
    x0, x1 = pts[0][0], pts[-1][0]
    mark_x = [year_frac(m["date"]) for m in marks]
    x0 = min([x0] + mark_x)
    x1 = max([x1] + mark_x)
    if x1 == x0:
        x1 = x0 + 1
    vals = [p[1] for p in pts]
    if threshold is not None:
        vals.append(float(threshold["value"]))
    tr = (lambda v: math.log10(v)) if log else (lambda v: v)
    lo, hi = min(tr(v) for v in vals), max(tr(v) for v in vals)
    if not log:
        lo = min(lo, 0) if lo >= 0 and lo < hi * 0.35 else lo
    if hi == lo:
        hi = lo + 1
    span = hi - lo
    lo -= span * 0.04
    hi += span * 0.08
    W, H = width - pad_l - pad_r, height - pad_t - pad_b

    def X(x):
        return pad_l + (x - x0) / (x1 - x0) * W

    def Y(v):
        return pad_t + (1 - (tr(v) - lo) / (hi - lo)) * H

    out = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s" xmlns="http://www.w3.org/2000/svg">'
           % (width, height, escape(label, quote=True)), "<title>%s</title>" % escape(label)]
    # y grid
    if log:
        ticks = [10 ** e for e in range(int(math.floor(lo)), int(math.ceil(hi)) + 1)]
        ticks = [t for t in ticks if lo <= math.log10(t) <= hi]
    else:
        ticks = [t for t in _nice_ticks(lo, hi) if lo <= t <= hi]
    for t in ticks:
        y = Y(t)
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (pad_l, width - pad_r, y, y))
        out.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>'
                   % (pad_l - 6, y + 4, escape(tick_label(t, unit))))
    # x ticks: about 5 year labels
    years = list(range(int(math.ceil(x0)), int(math.floor(x1)) + 1))
    step = max(1, int(math.ceil(len(years) / 6.0)))
    for yv in years[::step]:
        x = X(yv)
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%d</text>' % (x, height - 10, yv))
    # threshold
    if threshold is not None:
        y = Y(float(threshold["value"]))
        out.append('<line class="threshold" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (pad_l, width - pad_r, y, y))
        out.append('<text class="thr-label" x="%d" y="%.1f">%s</text>'
                   % (pad_l + 4, y - 5, escape(threshold.get("label", "threshold"))))
    # marks
    for i, m in enumerate(marks):
        x = X(year_frac(m["date"]))
        out.append('<line class="mark" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (x, x, pad_t, height - pad_b))
        anchor = "start" if x < pad_l + W * 0.7 else "end"
        dx = 4 if anchor == "start" else -4
        out.append('<text class="mark-label" x="%.1f" y="%d" text-anchor="%s">%s</text>'
                   % (x + dx, pad_t + 12 + 13 * (i % 3), anchor, escape(m["label"])))
    # line
    path = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", X(x), Y(v)) for i, (x, v, _) in enumerate(pts))
    out.append('<path class="line" d="%s"/>' % path)
    if len(pts) <= 40:
        for x, v, d in pts:
            out.append('<circle class="pt" cx="%.1f" cy="%.1f" r="2.5"><title>%s: %s</title></circle>'
                       % (X(x), Y(v), escape(str(d)), escape(fmt_value(v, unit))))
    lx, lv, ld = pts[-1]
    out.append('<circle class="last" cx="%.1f" cy="%.1f" r="4.5"/>' % (X(lx), Y(lv)))
    anchor = "end" if X(lx) > pad_l + W * 0.6 else "start"
    out.append('<text class="last-label" x="%.1f" y="%.1f" text-anchor="%s">%s</text>'
               % (X(lx) + (-8 if anchor == "end" else 8), Y(lv) - 9, anchor, escape(fmt_value(lv, unit))))
    out.append("</svg>")
    return "".join(out)
