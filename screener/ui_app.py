"""
ui_app.py - the page's drawing: the Dash layout, its callbacks and the Plotly
figures, built only from what ui.py returns. The one file that imports Dash
or Plotly (AGENTS.md: each third-party package behind one door), and it is
imported only when `python app.py ui` runs, so nothing else needs them.

Nothing here computes a figure. Every number drawn or printed is one ui.py
handed over; what this file adds is layout: which trace a number goes in,
its colour, its hover text, and which tick gets a label. That is what lets
the tests in tests/test_ui.py check a figure against the view number for
number, and what would let the drawing move to another library without
touching a number.

The page is a muted dark grey, not white (owner, 2026-11-20: "the white is
just too bright for me"), so the colours are the reference palette's
dark-mode steps (the dataviz guidance), chosen for a dark surface rather
than flipped from the light ones: text in light ink; the fitted surface on
one blue ramp, never a rainbow, running dark for low IV to light for high,
so low values recede into the page as they would into white; the measured
points in the dark-mode orange, the palette's second categorical slot, so a
measurement never reads as part of the fit; the smiles in light ink; points
the fit left out in grey, hollow. Blue and orange are the palette's
validated adjacent pair. (The palette validator itself needs Node, which is
not installed here, so it was not re-run.) Every colour is one constant
below, and the page's grey is BG.

The camera rides along explicitly: the one the user last turned to is set
on each new figure (`camera_from`), so stepping to another snapshot leaves
the view where it was.

The highlights linking the two windows are a round trip each: a hover or
click goes to `respond`, which looks up the focus ui.py prepared and sends
back a Patch, only the strip's shapes and the surface's first trace. The
layout is untouched, so the camera stays, and nothing else is resent (5 to
17 ms on the local server, 2026-11-20). The highlighted window is amber in
both views; see ACCENT for why that colour.
"""

import dash
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from plotly.subplots import make_subplots

from screener import ui

BG = "#262624"          # the page: a muted dark grey
WIN_BG = "#2b2b28"      # inside a window, and behind its chart
BAR_BG = "#34342f"      # a window's title bar, where it is dragged from
PANEL = "#2f2f2c"       # the 3D box's walls and the buttons, a step off the page
GRID = "#4a4944"        # grid lines on those walls
INK = "#f0efec"         # text: the palette's dark-mode primary
INK_2 = "#c3c2b7"       # quieter text: its dark-mode secondary
ORANGE = "#d95926"      # categorical slot 2, dark-mode step
BLUE = "#3987e5"        # categorical slot 1, dark-mode step: the variance swap's lines
# The highlighted window: outlined on the strip, and its two ends' smiles
# thickened on the surface, so one colour marks one window in both views.
# Categorical slot 4 (yellow), dark-mode step. Tried in the browser on
# 2026-11-20: light ink vanished among the light smiles, and slot 3 (aqua)
# sank into the blue surface at the same lightness; amber reads on blue
# from any angle. Blue and yellow are the pair colour-blind readers keep
# best apart; beside the orange points it is told apart by width (a line
# three times theirs) and its legend entry. Not run through the palette
# validator, which needs Node (not installed).
ACCENT = "#c98500"
GREY = "#8a8984"
# The palette's status colours, kept for states and never for a series:
# a negative window inside its error bar, and one beyond it (an arbitrage).
WARNING = "#fab219"
CRITICAL = "#d03b3b"
SMILE = "#e8e6df"       # the fitted smiles, light ink
# The palette's blue ramp, steps 650 to 100, for magnitude on a dark page:
# low IV dark, receding into the page, high IV light.
BLUES = ["#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]
SCALE = [[i / (len(BLUES) - 1), c] for i, c in enumerate(BLUES)]
# Lines of equal IV on the surface, this many vol points apart, and their
# projection onto the box's IV wall farthest from the eye: the floor when
# the surface is seen from above, the ceiling from below (checked in the
# browser, 2026-11-20). A display choice: it decides where lines are drawn,
# never what any point is worth.
CONTOUR_STEP = 0.02

NAMES = {
    "surface": "fit (surface.py): faces between expiries drawn, not measured",
    "smiles": "fitted smile, inside the strikes it was fitted on",
    "points": "IV solved by vol.py",
    "bands": "its band, bid to ask",
    "left_out": "solved, but left out of the fit",
    "spot": "SPY at the snapshot",
    "highlight": "highlighted: the two ends of the window",
}
# Short, since the strip's window is narrow and every legend line costs its
# charts height; the snapshot window spells each one out.
STRIP_NAMES = {
    "total": "total variance (variance swap)",
    "total_atm": "total variance (ATM levels: fallback)",
    "atm": "ATM total",
    "targets": "hover targets along the strip",
    "sessions": "each whole session",
    "dropped": "expiry left out (A-015)",
    "steps": "forward vol",
    "mids": "forward vol, error bar",
    "widened": "widened window",
    "negative": "negative variance",
}

FONT = "system-ui, -apple-system, Segoe UI, sans-serif"
PAGE = {"fontFamily": FONT, "color": INK, "background": BG,
        "padding": "12px 16px", "minHeight": "100vh", "boxSizing": "border-box"}
MUTED = {"color": INK_2, "fontSize": "13px", "lineHeight": "1.45"}


# ---------------------------------------------------------------------------
# The figure
# ---------------------------------------------------------------------------

def _pct(v):
    return "-" if v is None else f"{100 * v:.2f}%"


def _point_text(p):
    lines = [f"{p['expiry']} {p['strike']:g}{p['right']}",
             f"IV {_pct(p['iv'])}  (band {_pct(p['iv_bid'])} to {_pct(p['iv_ask'])})",
             f"delta {p['delta']:+.3f}" if p["delta"] is not None else "delta -",
             f"fit {_pct(p['fitted_iv'])}, residual {_pct(p['residual'])}"]
    lines.append("used by the fit" if p["readable"] else f"left out of the fit: {p['why_not']}")
    return "<br>".join(lines)


def _expiry_ticks(expiries):
    """An expiry date at each expiry's place on the session axis, skipping
    one that would sit on top of the last label."""
    vals, text, last = [], [], None
    for x in expiries:
        if last is None or x["sessions"] - last >= 1.5:
            vals.append(x["sessions"])
            text.append(x["expiry"][5:])
            last = x["sessions"]
    return vals, text


# The first view: from the front and a little to the right, strike running
# left to right and the nearest expiry in front.
CAMERA = dict(eye=dict(x=0.25, y=-2.0, z=0.6))


def camera_from(relayout):
    """The camera the user last turned or zoomed the surface to, from the
    graph's `relayoutData`, which Plotly reports after each interaction;
    None if there has been none. Handed back to every redraw, so a step to
    another snapshot keeps the view."""
    if relayout and isinstance(relayout.get("scene.camera"), dict):
        return relayout["scene.camera"]
    return None


def _spot_line(view, ranges):
    """SPY at the snapshot along the floor, from session 0 to the far end of
    the expiry axis, as (xs, ys, zs). The front window's highlight thickens
    it, since that window's near end is the snapshot, not a smile."""
    far = ranges["sessions"][1] if ranges else max((x["sessions"] for x in view["expiries"]),
                                                    default=1.0)
    floor = (ranges["iv"][0] if ranges else
             min((p["iv"] for p in view["points"] if p["readable"]), default=0.0))
    return [view["spot"], view["spot"]], [0.0, far], [floor, floor]


def surface_figure(view, ranges=None, contours=True, camera=None, keys=None):
    """The 3D view of one snapshot: the fitted surface, the smiles, the
    points with their bands, and SPY at the snapshot on the floor. `ranges`
    from ui.axis_ranges holds the axes fixed; None lets them fit this
    snapshot alone. `keys` (ui.chain_strip's `focus_by_expiry`) goes on each
    smile and point, so hovering one highlights its expiry (a surface cell is
    found by its row's place, see key_from).
    Returned as the plain figure dict Dash is sent (see the surface's hover
    labels at the end).

    The first trace is the highlight, empty until something is hovered: the
    smiles at the two ends of the highlighted window, thickened. In 3D a
    highlight cannot be a shaded band or an outline, only a redrawn trace
    (record, section 9), and being first gives it a fixed place for the
    hover callback to fill."""
    grid = view["grid"]
    keys = keys or {}
    fig = go.Figure()

    fig.add_trace(go.Scatter3d(x=[], y=[], z=[], mode="lines", name=NAMES["highlight"],
                               hoverinfo="skip", line=dict(color=ACCENT, width=12)))

    if grid["expiries"]:
        surface = dict(
            x=grid["strikes"], y=grid["sessions"], z=grid["iv"],
            hoverinfo="text", colorscale=SCALE, opacity=0.92, name=NAMES["surface"], showlegend=True,
            colorbar=dict(title=dict(text="IV, fit"), tickformat=".0%", len=0.6, thickness=14),
        )
        if ranges:
            surface.update(cmin=ranges["iv"][0], cmax=ranges["iv"][1])
        if contours:
            surface["contours"] = dict(z=dict(
                show=True, size=CONTOUR_STEP, color=INK_2, width=1,
                start=0.0, end=2.0, project=dict(z=True)))
        fig.add_trace(go.Surface(**surface))

    xs, ys, zs, tx, cd = [], [], [], [], []
    for s in view["smiles"]:
        xs += s["strikes"] + [None]
        ys += [s["sessions"]] * len(s["strikes"]) + [None]
        zs += s["iv"] + [None]
        tx += [f"{s['expiry']} fitted smile<br>strike {k:g}<br>IV {_pct(z)}"
               for k, z in zip(s["strikes"], s["iv"])] + [""]
        cd += [keys.get(s["expiry"])] * len(s["strikes"]) + [None]
    fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", name=NAMES["smiles"],
                               line=dict(color=SMILE, width=4), hovertext=tx, customdata=cd,
                               hovertemplate="%{hovertext}<extra></extra>"))

    used = [p for p in view["points"] if p["readable"]]
    out = [p for p in view["points"] if not p["readable"]]
    fig.add_trace(go.Scatter3d(
        x=[p["strike"] for p in used], y=[p["sessions"] for p in used],
        z=[p["iv"] for p in used], mode="markers", name=NAMES["points"],
        marker=dict(size=3, color=ORANGE), hovertext=[_point_text(p) for p in used],
        customdata=[keys.get(p["expiry"]) for p in used],
        hovertemplate="%{hovertext}<extra></extra>"))
    bx, by, bz = [], [], []
    for p in used:
        bx += [p["strike"], p["strike"], None]
        by += [p["sessions"], p["sessions"], None]
        bz += [p["iv_bid"], p["iv_ask"], None]
    fig.add_trace(go.Scatter3d(x=bx, y=by, z=bz, mode="lines", name=NAMES["bands"],
                               line=dict(color=ORANGE, width=2), hoverinfo="skip"))
    # Off until asked for: Plotly does not clip 3D points to a fixed axis
    # range, and quotes the fit left out (65% IV at the 90th percentile, up
    # to 130%, across the snapshots held on 2026-11-19) would hang outside
    # the box. One click on the legend shows them.
    fig.add_trace(go.Scatter3d(
        x=[p["strike"] for p in out], y=[p["sessions"] for p in out],
        z=[p["iv"] for p in out], mode="markers", name=NAMES["left_out"],
        visible="legendonly",
        marker=dict(size=3, color=GREY, symbol="circle-open"),
        customdata=[keys.get(p["expiry"]) for p in out],
        hovertext=[_point_text(p) for p in out], hovertemplate="%{hovertext}<extra></extra>"))

    sx, sy, sz = _spot_line(view, ranges)
    fig.add_trace(go.Scatter3d(
        x=sx, y=sy, z=sz, mode="lines",
        name=NAMES["spot"], line=dict(color=INK, width=3, dash="dash"),
        hovertext=[f"SPY {view['spot']:.2f} at the snapshot"] * 2,
        hovertemplate="%{hovertext}<extra></extra>"))

    tickvals, ticktext = _expiry_ticks(view["expiries"])
    axis = dict(backgroundcolor=PANEL, gridcolor=GRID, zerolinecolor=GRID,
                showspikes=True, spikecolor=INK_2)
    scene = dict(
        xaxis=dict(axis, title=dict(text="strike ($)")),
        yaxis=dict(axis, title=dict(text="expiry"), tickvals=tickvals, ticktext=ticktext),
        zaxis=dict(axis, title=dict(text="IV"), tickformat=".0%"),
        aspectmode="manual", aspectratio=dict(x=1.6, y=1.2, z=1.0),
        # The user's last camera if there is one, else the first view. Set
        # explicitly rather than left to uirevision alone: in the browser a
        # step reset the view (2026-11-19), so the camera rides along.
        camera=camera or CAMERA,
        uirevision="chain")
    if ranges:
        scene["xaxis"]["range"] = ranges["strike"]
        scene["yaxis"]["range"] = ranges["sessions"]
        scene["zaxis"]["range"] = ranges["iv"]
    fig.update_layout(
        scene=scene, uirevision="chain", paper_bgcolor=WIN_BG,
        font=dict(family=FONT, color=INK, size=12), margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0.0, font=dict(size=12)),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(family=FONT, color=INK)))
    out = fig.to_dict()
    if grid["expiries"]:
        # The surface's hover label, one per cell. plotly.js reads a grid of
        # text for a surface, but only through hoverinfo (a hovertemplate
        # shows "-" there, checked in the browser with plotly.js 4.1.1), and
        # plotly.py accepts a surface's text only as a flat list, turning each
        # row into one string. So the grid goes onto the plain figure Dash is
        # sent, past plotly.py's checks. (No highlight key goes on a cell:
        # plotly.js leaves a surface's customdata out of its hover event, so
        # key_from finds the row's expiry by its place on the axis instead.)
        surface = next(t for t in out["data"] if t["type"] == "surface")
        surface["text"] = [
            [f"{x} (fit)<br>strike {k:g}<br>IV {_pct(z)}" if z is not None else ""
             for k, z in zip(grid["strikes"], row)]
            for x, row in zip(grid["expiries"], grid["iv"])]
    return out


def refused_figure(view):
    fig = go.Figure()
    fig.add_annotation(text="This snapshot could not be read. The reasons are beside the chart.",
                       showarrow=False, font=dict(color=INK_2, size=14))
    fig.update_layout(paper_bgcolor=WIN_BG, plot_bgcolor=WIN_BG,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def _pts(v):
    """A vol difference or error, in vol points."""
    return "-" if v is None else f"{100 * v:+.2f} pts"


def _expiry_text(x):
    if x["origin"]:
        return "the snapshot<br>total variance 0: no time has passed yet"
    lines = [f"{x['expiry']}: {x['sessions']:.2f} sessions from the snapshot",
             f"total variance {x['total_var']:.3e} ± {x['total_var_error']:.1e}",
             f"level {_pct(x['level'])} ({'variance swap' if x['source'] == 'vs' else 'ATM'})"]
    if x["atm_total_var"] is not None:
        lines.append(f"ATM {_pct(x['atm'])}: ATM total {x['atm_total_var']:.3e} "
                     f"± {x['atm_total_var_error']:.1e}")
    return "<br>".join(lines)


def _window_text(w):
    start = "the snapshot" if w["from_expiry"] == ui.context.SPOT else w["from_expiry"]
    count = w["sessions_calendar"]
    lines = [f"{start} to {w['to_expiry']}: {count:g} session{'s' * (count != 1)}"
             + (f", {w['half_days']:g} closing at 1pm (clock {w['sessions']:.2f})"
                if w["half_days"] else f" (clock {w['sessions']:.2f})"),
             f"{w['days']:g} calendar days"]
    if w["forward_vol"] is not None:
        lines.append(f"forward vol {_pct(w['forward_vol'])} ± "
                     f"{100 * w['forward_vol_error']:.2f} pts")
    lines.append(f"forward variance {w['forward_var']:.4f} a year")
    if w["negative"]:
        lines.append("negative variance: a calendar arbitrage beyond its error bar"
                     if w["arbitrage"] else "negative variance, inside its error bar")
    if w["session_priced"]:
        lines.append(f"prices {w['session_priced']} on its own")
    if w["spans_dropped"]:
        lines.append(f"stands in for {w['spans_dropped']:g} expir"
                     f"{'y' if w['spans_dropped'] == 1 else 'ies'} left out (A-015): its "
                     f"interval is sound, its split inside unknown")
    if w["edge_margin"] is not None:
        lines.append(f"drop budget spent by its weaker foot: {w['edge_margin']:.2f} "
                     f"(1.00 is refusal)")
    lines.append(f"at {w['to_expiry']}: ATM {_pct(w['atm_to'])}, 25-delta skew put "
                 f"{_pts(w['put_skew_to'])}, call {_pts(w['call_skew_to'])}")
    return "<br>".join(lines)


def _from_snapshot(between):
    """term.py's "spot to 2026-11-13" in the page's words."""
    return between.replace(f"{ui.context.SPOT} to", "the snapshot to")


def _session_text(p):
    lines = [f"session {p['sessions']:g} from the snapshot",
             f"total variance {p['total_var']:.3e} ± {p['total_var_error']:.1e}"
             if p["total_var_error"] is not None else f"total variance {p['total_var']:.3e}",
             f"{p['between']}'s own stripped total" if p["at_expiry"] else
             f"read between {_from_snapshot(p['between'])}: the error is the two ends' only"]
    if p["widened"]:
        lines.append("inside a window standing in for expiries left out:<br>"
                     "how its variance splits across these sessions is unknown")
    return "<br>".join(lines)


def strip_figure(strip, ranges=None):
    """The integral above, the strip below, on one session axis. `ranges`
    from ui.axis_ranges holds the axes fixed; None fits this snapshot.

    Every point that can be hovered carries the key of its highlight
    (ui.chain_strip's `foci`) as customdata, so the hover callback looks the
    highlight up instead of reading a position off the chart. Along the
    lower panel, where only each window's middle has a marker, invisible
    targets sit at every whole session and expiry, at the height of the
    window holding them, so the strip can be hovered along its length."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.13,
                        subplot_titles=("The integral: total variance from the snapshot",
                                        "The strip: forward vol in each window"))
    ex = strip["expiries"]
    keys = strip.get("focus_by_expiry", {})
    fallback = strip.get("source") == "atm"
    hover = "%{hovertext}<extra></extra>"

    fig.add_trace(go.Scatter(
        x=[x["sessions"] for x in ex], y=[x["total_var"] for x in ex], mode="lines+markers",
        name=STRIP_NAMES["total_atm" if fallback else "total"],
        line=dict(color=BLUE, width=2), marker=dict(size=7, color=BLUE),
        error_y=dict(type="data", array=[x["total_var_error"] for x in ex], color=BLUE,
                     thickness=1.2, width=4),
        customdata=[None if x["origin"] else keys.get(x["expiry"]) for x in ex],
        hovertext=[_expiry_text(x) for x in ex], hovertemplate=hover), row=1, col=1)
    # On an ATM fallback the total IS the ATM total, so a second line would
    # only hide the first and invite reading a gap that is not there as the
    # wings' (AC-32).
    atm = [] if fallback else [x for x in ex if x["atm_total_var"] is not None]
    if atm:
        fig.add_trace(go.Scatter(
            x=[x["sessions"] for x in atm], y=[x["atm_total_var"] for x in atm],
            mode="lines+markers", name=STRIP_NAMES["atm"],
            line=dict(color=ORANGE, width=2, dash="dot"), marker=dict(size=6, color=ORANGE),
            error_y=dict(type="data", array=[x["atm_total_var_error"] for x in atm],
                         color=ORANGE, thickness=1.2, width=4),
            customdata=[keys.get(x["expiry"]) for x in atm],
            hovertext=[_expiry_text(x) for x in atm], hovertemplate=hover), row=1, col=1)
    # Hollow inside a window that stands in for expiries left out: there the
    # chain listed expiries that could have split the variance, and term.py
    # could not use them, so the straight line is all there is.
    pts = strip["integral"]
    fig.add_trace(go.Scatter(
        x=[p["sessions"] for p in pts], y=[p["total_var"] for p in pts], mode="markers",
        name=STRIP_NAMES["sessions"],
        marker=dict(size=5, color=INK_2,
                    symbol=["circle-open" if p["widened"] else "circle" for p in pts]),
        error_y=dict(type="data", array=[p["total_var_error"] for p in pts], color=INK_2,
                     thickness=1, width=2),
        customdata=[p["key"] for p in pts],
        hovertext=[_session_text(p) for p in pts], hovertemplate=hover), row=1, col=1)
    if strip["dropped"]:
        # On the floor of the integral: these expiries have no total in the
        # term structure, so the marker places them and says why, and is not
        # a value. 0 is the axis, not a reading.
        fig.add_trace(go.Scatter(
            x=[d["sessions"] for d in strip["dropped"]], y=[0.0] * len(strip["dropped"]),
            mode="markers", name=STRIP_NAMES["dropped"],
            marker=dict(size=11, color=GREY, symbol="line-ns-open", line=dict(width=2)),
            customdata=[keys.get(d["expiry"]) for d in strip["dropped"]],
            hovertext=[f"{d['expiry']}: left out of the term structure (A-015)<br>"
                       f"{d['strikes']:.0f} strikes; its integral still moving "
                       f"{100 * d['edge']:.3f} vol points at the edge" for d in strip["dropped"]],
            hovertemplate=hover), row=1, col=1)

    def steps(windows):
        xs, ys = [], []
        for w in windows:
            xs += [w["start"], w["end"], None]
            ys += [w["forward_vol"], w["forward_vol"], None]
        return xs, ys

    priced = [w for w in strip["windows"] if w["forward_vol"] is not None]
    sound = [w for w in priced if not w["spans_dropped"]]
    wide = [w for w in priced if w["spans_dropped"]]
    xs, ys = steps(sound)
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=STRIP_NAMES["steps"],
                             legendgroup="vol", line=dict(color=BLUE, width=3),
                             hoverinfo="skip"), row=2, col=1)
    if wide:
        xs, ys = steps(wide)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=STRIP_NAMES["widened"],
                                 line=dict(color=BLUE, width=3, dash="dash"),
                                 hoverinfo="skip"), row=2, col=1)
    # Each window's figures sit on a marker at its middle, with its error
    # bar. The middle places the marker; it is not a reading.
    fig.add_trace(go.Scatter(
        x=[(w["start"] + w["end"]) / 2 for w in priced], y=[w["forward_vol"] for w in priced],
        mode="markers", name=STRIP_NAMES["mids"], legendgroup="vol", showlegend=False,
        marker=dict(size=6, color=BLUE),
        error_y=dict(type="data", array=[w["forward_vol_error"] for w in priced],
                     color=BLUE, thickness=1.5, width=4),
        # A window's middle highlights the window: its far expiry's focus,
        # which is the window ending there.
        customdata=[keys.get(w["to_expiry"]) for w in priced],
        hovertext=[_window_text(w) for w in priced], hovertemplate=hover), row=2, col=1)
    bad = [w for w in strip["windows"] if w["negative"]]
    if bad:
        fig.add_trace(go.Scatter(
            x=[(w["start"] + w["end"]) / 2 for w in bad], y=[0.0] * len(bad),
            mode="markers", name=STRIP_NAMES["negative"],
            marker=dict(size=11, symbol="x",
                        color=[CRITICAL if w["arbitrage"] else WARNING for w in bad]),
            customdata=[keys.get(w["to_expiry"]) for w in bad],
            hovertext=[_window_text(w) for w in bad], hovertemplate=hover), row=2, col=1)
    # Hover targets along the strip, invisible and without a label of their
    # own (the readout above the chart is the label): each whole session and
    # expiry at the height of the window holding it, 0 for a window with no
    # vol. The height places the target; it is not a reading.
    aim = [f for f in strip.get("foci", []) if f["window"] is not None]
    if aim:
        wins = strip["windows"]
        fig.add_trace(go.Scatter(
            x=[f["sessions"] for f in aim],
            y=[wins[f["window"]]["forward_vol"] or 0.0 for f in aim], mode="markers",
            name=STRIP_NAMES["targets"], showlegend=False, hoverinfo="none",
            marker=dict(size=14, color=INK, opacity=0.0),
            customdata=[f["key"] for f in aim]), row=2, col=1)

    tickvals, ticktext = _expiry_ticks([x for x in ex if not x["origin"]])
    axis = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, showspikes=True,
                spikecolor=INK_2, spikethickness=1, spikedash="dot", spikemode="across")
    fig.update_xaxes(axis, tickvals=tickvals, ticktext=ticktext)
    fig.update_xaxes(title_text="expiry, at its sessions from the snapshot", row=2, col=1)
    fig.update_yaxes(axis)
    fig.update_yaxes(title_text="total variance", tickformat=".1e", row=1, col=1)
    fig.update_yaxes(title_text="forward vol", tickformat=".0%", row=2, col=1)
    if ranges:
        fig.update_xaxes(range=ranges["sessions"])
        fig.update_yaxes(range=ranges["total_var"], row=1, col=1)
        fig.update_yaxes(range=ranges["forward_vol"], row=2, col=1)
    fig.update_annotations(font=dict(color=INK_2, size=12))
    fig.update_layout(
        paper_bgcolor=WIN_BG, plot_bgcolor=PANEL, uirevision="strip",
        font=dict(family=FONT, color=INK, size=11), margin=dict(l=64, r=16, t=64, b=44),
        legend=dict(orientation="h", yanchor="bottom", y=1.05, x=0.0, font=dict(size=10)),
        hovermode="closest",
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(family=FONT, color=INK)))
    return fig.to_dict()


INTEGRAL_VS = ("Above, the integral: total variance from the snapshot to each expiry (blue, "
               "stripped from the variance swap rate), with its error bar; the ATM total "
               "beside it (orange, dotted), whose gap below the blue is the variance the "
               "wings add.")
INTEGRAL_ATM = ("Above, the integral: total variance from the snapshot to each expiry, from "
                "each expiry's ATM level. On this snapshot fewer than two expiries could "
                "carry a variance swap rate inside the edge budget, so term.py used ATM "
                "levels for all of them (one source per snapshot). The ATM total is that "
                "same line, so it is not drawn twice, and nothing here measures what the "
                "wings add. ATM levels are skew-blind and read lower than the variance swap, "
                "so a step to or from a snapshot stripped from variance swap rates changes "
                "the quantity, not only the market.")
ATM_TITLE = "term structure from ATM levels (fallback)"


def side_panel(view, strip=None):
    """Beside the chart: what the snapshot is, the collector's warnings, and
    what each thing drawn is."""
    if view.get("refused"):
        return [html.H4("Could not be read", style={"margin": "0 0 6px"}),
                html.Ul([html.Li(r) for r in view["refused"]], style=MUTED)]
    c = view["counts"]
    facts = [html.Div(f"Started {view['started']} ET"),
             html.Div(f"SPY {view['spot']:.2f} at the start"),
             html.Div(f"{c['expiries']} expiries read, {c['fitted']} with a fit"),
             html.Div(f"{c['points']} IVs solved, {c['used']} used by the fit")]
    fallback = bool(strip) and strip.get("source") == "atm"
    if strip and not strip.get("refused"):
        kept = sum(1 for x in strip["expiries"] if not x["origin"])
        facts.append(html.Div(f"{kept} expiries in the term structure, "
                              f"{len(strip['windows'])} windows between them"))
        facts.append(html.Div("Term structure stripped from: "
                              + ("ATM levels, term.py's fallback" if fallback
                                 else "variance swap rates")))
    if view["warnings"]:
        warn = html.Ul([html.Li(w) for w in view["warnings"]],
                       style={"margin": "4px 0 0", "paddingLeft": "18px"})
    else:
        warn = html.Div(view["warnings_note"], style=MUTED)
    left_out = []
    if strip and strip.get("dropped"):
        left_out = [
            html.H4("Left out of the term structure (A-015)", style={"margin": "16px 0 2px"}),
            html.Div("Their totals were not converged enough to strip, so the window "
                     "around each is wider. Their IVs are still on the surface.", style=MUTED),
            html.Ul([html.Li(f"{d['expiry']}: {d['strikes']:.0f} strikes, its integral "
                             f"still moving {100 * d['edge']:.3f} vol points at the edge")
                     for d in strip["dropped"]],
                    style={"margin": "4px 0 0", "paddingLeft": "18px", "fontSize": "13px"})]
    return [
        html.Div(facts, style={"fontSize": "14px", "lineHeight": "1.6"}),
        html.H4("Collector warnings (run.json)", style={"margin": "16px 0 2px"}),
        html.Div("The pipeline does not repeat these.", style=MUTED),
        warn,
        *left_out,
        html.H4("What the strip draws", style={"margin": "16px 0 2px"}),
        html.Div([
            html.P(INTEGRAL_ATM if fallback else INTEGRAL_VS),
            html.P("Small dots read the total at every whole session between expiries, on "
                   "term.py's straight line, with the error the two expiries either side "
                   "carry in. That error says nothing about how variance spreads between "
                   "them. A hollow dot sits inside a window standing in for expiries left "
                   "out, where the chain listed expiries that could have split it."),
            html.P("Hover a session on the strip, or an expiry on the surface, and both "
                   "windows show it: a line at that session, the time included in the total "
                   "shaded faintly, the window holding it outlined, and the smiles at that "
                   "window's two ends thickened on the surface. The line above the strip "
                   "reads it out. Click to hold it while you turn the surface; click again, "
                   "or let go, to release it."),
            html.P("Below, the strip it is made of: the forward vol each window between "
                   "adjacent expiries prices, as a step across its sessions, with its error "
                   "bar at the middle. The first window runs from the snapshot itself. A "
                   "dashed step stands in for expiries left out. An x marks negative "
                   "variance: yellow inside its error bar, red beyond it."),
            html.P("Hover any marker for its numbers. Sessions are the engine's clock, the "
                   "same as the surface's expiry axis."),
        ], style=MUTED),
        html.H4("What the surface draws", style={"margin": "16px 0 2px"}),
        html.Div([
            html.P("Orange points: the IVs vol.py solved, each with its band from bid to "
                   "ask. These are the measurements."),
            html.P("Light lines: surface.py's fitted smile per expiry, only between the "
                   "strikes it was fitted on."),
            html.P("Blue surface: the same fits on one strike grid. The faces between two "
                   "expiries are drawn by the renderer, not measured."),
            html.P("Grey rings, off at first: IVs solved but left out of the fit. Click "
                   "their legend entry to show them, and hover for the reason."),
            html.P("Expiries sit at their sessions from the snapshot on the engine's clock. "
                   "Click a legend entry to hide or show it."),
            html.P("A measurement of one snapshot, not a forecast."),
        ], style=MUTED),
    ]


def page_for(name, options, ranges, camera=None):
    """(surface figure, strip figure, snapshot window, title, highlight
    data) for one snapshot: what the callbacks return, kept here as a plain
    function so it can be tested."""
    view = ui.chain_surface(name)
    title = f"Snapshot {name}"
    if view.get("refused"):
        return refused_figure(view), refused_figure(view), side_panel(view), title, None
    strip = ui.chain_strip(name)
    if strip.get("source") == "atm":
        title += f" · {ATM_TITLE}"
    fixed = ranges if "fixed" in (options or []) else None
    fig = surface_figure(view, fixed, contours="contours" in (options or []), camera=camera,
                         keys=strip["focus_by_expiry"])
    data = focus_data(view, strip, fixed)
    data["surface_curve"] = next((i for i, t in enumerate(fig["data"]) if t["type"] == "surface"),
                                 None)
    return fig, strip_figure(strip, fixed), side_panel(view, strip), title, data


# ---------------------------------------------------------------------------
# The highlights
# ---------------------------------------------------------------------------

READOUT_IDLE = ("Hover a session on the strip, or an expiry on the surface, to highlight it "
                "in both windows. Click to hold it.")


def focus_data(view, strip, ranges):
    """What the hover callback needs, kept in the page between hovers so a
    highlight is a look-up and not a re-read of the snapshot: the view's
    foci and windows, and the coordinates of each smile and of the SPY line
    exactly as the surface figure drew them."""
    return {"foci": strip["foci"], "windows": strip["windows"], "source": strip["source"],
            "smiles": {s["expiry"]: [s["strikes"], [s["sessions"]] * len(s["strikes"]), s["iv"]]
                       for s in view["smiles"]},
            "spot_line": list(_spot_line(view, ranges))}


def _readout(data, f, w, held):
    """The highlight in words: where it is, the integral there and how it
    was read, the window holding it, and whether it is held."""
    if f["kind"] == "session":
        where = f"Session {f['sessions']:g} from the snapshot."
    else:
        where = f"{f['expiry']}, {f['sessions']:.2f} sessions from the snapshot."
    if f["reason"]:
        where = where[:-1] + f": {f['reason']}."
    lines = [where + (" Held: click it again, or let go." if held else " Click to hold.")]
    err = ("" if f["total_var_error"] is None else f" ± {f['total_var_error']:.1e}")
    if f["total_var"] is None:
        lines.append("No total here: its variance was never stripped.")
    elif f["at_expiry"]:
        source = ("variance swap rate" if data["source"] == "vs"
                  else "ATM level (term.py's fallback on this snapshot)")
        lines.append(f"Total variance {f['total_var']:.3e}{err}, stripped from its {source}.")
    else:
        lines.append(f"Total variance {f['total_var']:.3e}{err}, on term.py's straight line "
                     f"from {_from_snapshot(f['between'])}. The error is what those two ends carry in, not how "
                     f"variance spreads between them.")
    if w is None:
        lines.append("Past the last expiry the term structure kept: no window covers it.")
    else:
        start = ("the snapshot (the rest of its session included)"
                 if w["from_expiry"] == ui.context.SPOT else w["from_expiry"])
        n = w["sessions_calendar"]
        vol = (f"forward vol {_pct(w['forward_vol'])} ± {100 * w['forward_vol_error']:.2f} pts"
               if w["forward_vol"] is not None else "negative variance, so no forward vol")
        text = f"Window from {start} to {w['to_expiry']}, {n:g} session{'s' * (n != 1)}: {vol}."
        if w["left_out"]:
            k = len(w["left_out"])
            text += (f" It stands in for {k} expir{'y' if k == 1 else 'ies'} left out "
                     f"({', '.join(w['left_out'])}): how its variance splits across those "
                     f"sessions is unknown.")
        lines.append(text)
    return lines


def highlight(data, key, held=False):
    """One highlight, drawn from the view's focus `key`: the strip's shapes,
    the surface's highlight trace, and the readout's lines. Placing only: the
    session, the integral and the window are the view's.

    On the strip, as layout shapes: a faint full-height span from the
    snapshot to s labelled "time included in the total" - a selection aid,
    not an area under the vol steps, which would not be the integral
    (question 22) - only where there is a total; the window holding s
    outlined in the lower panel; a line at s through both panels, dotted for
    an expiry outside the term structure; and a ring on the integral at s.
    On the surface: the smiles at the window's two ends, or the SPY line for
    the snapshot's end, which the first trace redraws thickened."""
    f = data["foci"][key]
    w = data["windows"][f["window"]] if f["window"] is not None else None
    s = f["sessions"]
    shapes = []
    if f["total_var"] is not None:
        shapes.append(dict(type="rect", xref="x", yref="paper", x0=0.0, x1=s, y0=0.0, y1=1.0,
                           fillcolor=INK, opacity=0.06, line=dict(width=0), layer="below",
                           label=dict(text="time included in the total",
                                      textposition="bottom left",
                                      font=dict(size=10, color=INK_2))))
    if w is not None:
        shapes.append(dict(type="rect", xref="x2", yref="y2 domain", x0=w["start"], x1=w["end"],
                           y0=0.0, y1=1.0, line=dict(color=ACCENT, width=2.5),
                           fillcolor="rgba(0,0,0,0)", layer="above"))
    shapes.append(dict(type="line", xref="x", yref="paper", x0=s, x1=s, y0=0.0, y1=1.0,
                       line=dict(color=INK, width=1.5,
                                 dash="dot" if f["kind"] == "outside" else "solid")))
    if f["total_var"] is not None:
        shapes.append(dict(type="circle", xref="x", yref="y", xsizemode="pixel",
                           ysizemode="pixel", xanchor=s, yanchor=f["total_var"],
                           x0=-7, x1=7, y0=-7, y1=7, line=dict(color=INK, width=2)))
    xs, ys, zs = [], [], []
    if w is not None:
        for end in (w["from_expiry"], w["to_expiry"]):
            line = (data["spot_line"] if end == ui.context.SPOT else data["smiles"].get(end))
            if line:
                xs += list(line[0]) + [None]
                ys += list(line[1]) + [None]
                zs += list(line[2]) + [None]
    return {"shapes": shapes, "surface": {"x": xs, "y": ys, "z": zs},
            "readout": _readout(data, f, w, held)}


def next_focus(event, key, held):
    """(focus, held) after one event: "hover" or "click" on a point carrying
    the focus `key`, or "letgo". Hovering moves the highlight unless one is
    held; a click holds it; a second click on the held point, or "let go",
    releases it and leaves it showing until the next hover."""
    if event == "letgo":
        return held, None
    if event == "click":
        return (key, None) if key == held else (key, key)
    return (held, held) if held is not None else (key, None)


def key_from(event_data, foci=(), surface_curve=None):
    """The focus key of a hovered or clicked point, or None.

    Every point on the strip, and every smile and point on the surface,
    carries its key as customdata. A cell of the surface itself cannot:
    plotly.js 4.1.1 leaves a surface's customdata out of its hover event,
    and Dash passes on only the cell's x, y, z and its trace's number (seen
    in the browser, 2026-11-20). So a point on the surface's trace
    (`surface_curve`, from focus_data) is matched by its y: the row's place
    on the expiry axis, which is that expiry's sessions, the very number the
    view gave its focus. A look-up, not a reading: no number is computed."""
    points = (event_data or {}).get("points") or []
    if not points:
        return None
    p = points[0]
    key = p.get("customdata")
    if isinstance(key, list):
        key = key[0] if key else None
    if isinstance(key, int):
        return key
    if surface_curve is not None and p.get("curveNumber") == surface_curve:
        return next((f["key"] for f in foci
                     if f["expiry"] and f["sessions"] == p.get("y")), None)
    return None


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def _marks(names):
    every = max(1, len(names) // 6)
    return {i: {"label": n[5:10], "style": {"fontSize": "11px"}}
            for i, n in enumerate(names) if i % every == 0 or i == len(names) - 1}


LETGO_SHOWN = {"fontSize": "12px", "padding": "2px 8px", "cursor": "pointer",
               "background": PANEL, "color": INK, "border": f"1px solid {GRID}",
               "borderRadius": "4px", "flex": "0 0 auto"}
LETGO_HIDDEN = dict(LETGO_SHOWN, display="none")


def window(win_id, title, body, place, scroll=False):
    """A bordered window: dragged by its title bar (assets/windows.js),
    resized from its lower-right corner (CSS), brought to the front when
    clicked. `place` is where it opens; where it is moved to is not kept
    from one launch to the next."""
    return html.Div([html.Div(title, className="win-bar"),
                     html.Div(body, className="win-body scroll" if scroll else "win-body")],
                    id=win_id, className="win", style=place)


def _graph(graph_id):
    # responsive: the chart follows its window's size as the window is
    # resized, not only the browser's.
    return dcc.Loading(dcc.Graph(id=graph_id, responsive=True,
                                 style={"height": "100%", "width": "100%"},
                                 config={"displaylogo": False}),
                       delay_show=300, parent_style={"height": "100%"})


def layout(start=None):
    """Built on every page load, so a reload lists a snapshot added since."""
    names = ui.snapshots()
    head = [html.H2("SPY chain: the IV surface and the variance strip",
                    style={"margin": "0 0 2px"}),
            html.Div("vol.py's IVs, surface.py's fit and term.py's time axis, one snapshot "
                     "at a time. Measured, not a forecast. Drag a window by its title bar; "
                     "resize it from its lower-right corner.", style=MUTED)]
    if not names:
        return html.Div(head + [html.P([
            "No snapshot has been carried through the fit yet. Run ",
            html.Code("python app.py daily"), " (or ", html.Code("python app.py iv"),
            " then ", html.Code("python app.py surface"), ") and reload this page."],
            style={"marginTop": "24px"})], style=PAGE)
    at = names.index(start) if start in names else len(names) - 1
    button = {"fontSize": "16px", "padding": "2px 10px", "cursor": "pointer",
              "background": PANEL, "color": INK, "border": f"1px solid {GRID}",
              "borderRadius": "4px"}
    controls = html.Div([
        html.Button("◀", id="prev", title="the snapshot before", style=button),
        html.Div(dcc.Slider(id="snap", min=0, max=len(names) - 1, step=1, value=at,
                            marks=_marks(names), included=False),
                 style={"flex": "1", "padding": "0 8px"}),
        html.Button("▶", id="next", title="the snapshot after", style=button),
    ], style={"display": "flex", "alignItems": "center", "margin": "10px 0 4px"})
    options = dcc.Checklist(
        id="options", value=["contours", "fixed"], inline=True,
        options=[{"label": " contour lines", "value": "contours"},
                 {"label": " axes held fixed across snapshots", "value": "fixed"}],
        inputStyle={"marginLeft": "14px"}, style={"fontSize": "13px"})
    # Where each window opens: the surface large on the left, the strip on
    # the right, the snapshot's facts below the surface. Layout only.
    workspace = html.Div([
        window("win-surface", "IV surface: strike × expiry × IV", _graph("surface"),
               {"left": "0", "top": "0", "width": "calc(58% - 8px)", "height": "640px"}),
        window("win-strip", "Variance strip: the integral and its windows", html.Div([
            # A fixed height: a readout that grew would push the chart down
            # under the mouse, which then hovers another point (seen in the
            # browser, 2026-11-20). A long one scrolls instead.
            html.Div([
                html.Div(READOUT_IDLE, id="readout",
                         style={"flex": "1 1 auto", "height": "100%", "overflowY": "auto"}),
                html.Button("let go", id="letgo", title="release the held highlight",
                            style=LETGO_HIDDEN),
            ], style={"display": "flex", "alignItems": "flex-start", "gap": "8px",
                      "padding": "6px 10px", "height": "104px", "flex": "0 0 auto",
                      "boxSizing": "border-box", "fontSize": "12px", "lineHeight": "1.4",
                      "color": INK_2, "borderBottom": f"1px solid {GRID}"}),
            html.Div(_graph("strip"), style={"flex": "1 1 auto", "minHeight": "0"}),
        ], style={"display": "flex", "flexDirection": "column", "height": "100%"}),
               {"left": "58%", "top": "0", "width": "42%", "height": "640px"}),
        window("win-info", "Snapshot", html.Div(id="side"),
               {"left": "0", "top": "652px", "width": "calc(58% - 8px)", "height": "330px"},
               scroll=True),
    ], className="workspace")
    return html.Div(head + [
        dcc.Store(id="names", data=names),
        dcc.Store(id="ranges", data=ui.axis_ranges(names)),
        dcc.Store(id="focus"),          # the snapshot's highlights (focus_data)
        dcc.Store(id="held"),           # the held highlight's key, or None
        html.H3(id="title", style={"margin": "12px 0 0", "fontSize": "16px"}),
        controls, options, workspace,
    ], style=PAGE)


# Dash's own page around the layout: its default body is white with a margin,
# and Dash 4 colours its slider, checklist and inputs through --Dash-*
# variables set for a white page (read from the running page, 2026-11-20).
# They are set again here for the grey one: light text and strokes, the
# panel grey behind inputs, and the palette's blue (dark-mode slot 1) for
# the slider's handle and a ticked box in place of Dash's purple.
# `html:root` outranks Dash's own `:root`, whichever stylesheet loads last.
INDEX = """<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
      html, body { margin: 0; background: PAGE_BG; color-scheme: dark; }
      html:root {
        --Dash-Stroke-Strong: rgba(240, 239, 236, 0.45);
        --Dash-Stroke-Weak: rgba(240, 239, 236, 0.16);
        --Dash-Fill-Interactive-Strong: #3987e5;
        --Dash-Fill-Interactive-Weak: rgba(240, 239, 236, 0.06);
        --Dash-Fill-Inverse-Strong: PANEL_BG;
        --Dash-Text-Primary: rgba(240, 239, 236, 0.87);
        --Dash-Text-Strong: rgba(240, 239, 236, 0.95);
        --Dash-Text-Weak: rgba(240, 239, 236, 0.65);
        --Dash-Text-Disabled: rgba(240, 239, 236, 0.4);
        --Dash-Fill-Primary-Hover: rgba(240, 239, 236, 0.06);
        --Dash-Fill-Primary-Active: rgba(240, 239, 236, 0.12);
        --Dash-Fill-Disabled: rgba(240, 239, 236, 0.1);
      }
      .workspace { position: relative; min-height: 1000px; margin-top: 10px; }
      .win { position: absolute; display: flex; flex-direction: column;
             box-sizing: border-box; background: WIN_BG; border: 1px solid GRID_C;
             border-radius: 6px; box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
             resize: both; overflow: hidden; min-width: 300px; min-height: 180px; }
      .win-bar { flex: 0 0 auto; padding: 6px 10px; font-size: 13px; color: INK_2_C;
                 background: BAR_BG; border-bottom: 1px solid GRID_C; cursor: move;
                 user-select: none; }
      .win-body { flex: 1 1 auto; min-height: 0; position: relative; }
      .win-body.scroll { overflow: auto; padding: 10px 14px; font-size: 14px; }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>""".replace("PAGE_BG", BG).replace("PANEL_BG", PANEL).replace(
    "WIN_BG", WIN_BG).replace("BAR_BG", BAR_BG).replace("GRID_C", GRID).replace("INK_2_C", INK_2)


def create_app(start=None):
    app = dash.Dash(__name__, title="SPY screener", update_title=None,
                    suppress_callback_exceptions=True)
    app.index_string = INDEX
    app.layout = lambda: layout(start)

    @app.callback(Output("snap", "value"),
                  Input("prev", "n_clicks"), Input("next", "n_clicks"),
                  State("snap", "value"), State("names", "data"),
                  prevent_initial_call=True)
    def step(_prev, _next, value, names):
        if dash.ctx.triggered_id == "prev":
            return max(0, value - 1)
        return min(len(names) - 1, value + 1)

    @app.callback(Output("surface", "figure"), Output("strip", "figure"),
                  Output("side", "children"), Output("title", "children"),
                  Output("focus", "data"), Output("held", "data"),
                  Output("readout", "children"), Output("letgo", "style"),
                  Input("snap", "value"), Input("options", "value"),
                  State("names", "data"), State("ranges", "data"),
                  State("surface", "relayoutData"))
    def render(value, options, names, ranges, relayout):
        # A new snapshot, or new options, starts with no highlight: the
        # keys belong to the snapshot they were made for.
        return (*page_for(names[value], options, ranges, camera_from(relayout)),
                None, READOUT_IDLE, LETGO_HIDDEN)

    # The link between the two windows. Each hover or click is a round trip
    # to here and back (record, section 9); what comes back is a Patch, only
    # the strip's shapes and the surface's highlight trace, so neither
    # figure is sent again. The camera is not touched: the patched figure
    # keeps its layout, and with it the view the user turned to.
    @app.callback(Output("strip", "figure", allow_duplicate=True),
                  Output("surface", "figure", allow_duplicate=True),
                  Output("readout", "children", allow_duplicate=True),
                  Output("held", "data", allow_duplicate=True),
                  Output("letgo", "style", allow_duplicate=True),
                  Input("strip", "hoverData"), Input("strip", "clickData"),
                  Input("surface", "hoverData"), Input("surface", "clickData"),
                  Input("letgo", "n_clicks"),
                  State("focus", "data"), State("held", "data"),
                  prevent_initial_call=True)
    def link(_sh, _sc, _uh, _uc, _go, data, held):
        if not dash.ctx.triggered:
            return (dash.no_update,) * 5
        fired = dash.ctx.triggered[0]
        return respond(fired["prop_id"], fired["value"], data, held)

    return app


def respond(prop_id, value, data, held):
    """What the page sends back for one event: `prop_id` is Dash's name for
    what fired ("strip.hoverData", "surface.clickData", "letgo.n_clicks"),
    `value` what it carried, `data` the snapshot's focus_data and `held` the
    held key. Returns (strip patch, surface patch, readout, held, let-go
    button style), each dash.no_update where nothing changes. A plain
    function so the tests can send it the events Dash sends."""
    nothing = (dash.no_update,) * 5
    if not data:
        return nothing
    event = ("letgo" if prop_id.startswith("letgo.")
             else "click" if prop_id.endswith(".clickData") else "hover")
    key = None if event == "letgo" else key_from(value, data["foci"], data.get("surface_curve"))
    if event != "letgo" and key is None:
        return nothing
    if event == "hover" and held is not None:
        return nothing                      # held: hovering moves nothing
    focus, now_held = next_focus(event, key, held)
    if focus is None:
        return nothing
    h = highlight(data, focus, now_held is not None)
    strip, surface = dash.Patch(), dash.Patch()
    strip["layout"]["shapes"] = h["shapes"]
    surface["data"][0]["x"] = h["surface"]["x"]
    surface["data"][0]["y"] = h["surface"]["y"]
    surface["data"][0]["z"] = h["surface"]["z"]
    readout = [html.Div(line) for line in h["readout"]]
    return (strip, surface, readout, now_held,
            LETGO_SHOWN if now_held is not None else LETGO_HIDDEN)
