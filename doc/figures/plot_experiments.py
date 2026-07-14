"""Generate paper-quality figures for SkillQ experiment results (Series B, 5 rounds).

Output: doc/figures/fig1_q_convergence.pdf, fig2_q_vs_passrate.pdf,
        fig3_stability.pdf, fig4_passrate_trend.pdf

Requires: matplotlib (uv pip install matplotlib)
"""

from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path

matplotlib.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 12,
        "legend.fontsize": 10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
    }
)

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)

# ── colour palette ──────────────────────────────────────────────────
C_BLUE = "#2171b5"
C_ORANGE = "#d95f02"
C_GREEN = "#1b9e77"
C_RED = "#e41a1c"
C_GREY = "#999999"
C_LIGHT = "#f0f0f0"
BAR_COLORS = [C_GREY, C_GREY, C_GREY, C_BLUE, C_BLUE, C_BLUE, C_BLUE]


# =====================================================================
# Figure 1: Q-table convergence + skill library growth (dual Y-axis)
# =====================================================================
def fig1_q_convergence() -> None:
    rounds = ["R1", "R2", "R3", "R4", "R5"]
    nondef_q = [10, 60, 68, 66, 69]
    skills = [62, 82, 93, 104, 112]

    fig, ax1 = plt.subplots(figsize=(7, 4.2))

    # Bar: non-default Q ratio
    bars = ax1.bar(rounds, nondef_q, color=C_BLUE, alpha=0.85, width=0.55, zorder=3)
    ax1.set_ylabel("Non-Default Q Ratio (%)", color=C_BLUE)
    ax1.set_ylim(0, 85)
    ax1.tick_params(axis="y", labelcolor=C_BLUE)
    ax1.yaxis.set_major_locator(mticker.MultipleLocator(20))

    # Annotate bars — R4/R5 labels inside bar (white text) to avoid overlap
    for i, (bar, val) in enumerate(zip(bars, nondef_q)):
        y_offset = -12 if i >= 3 else 1.5
        va = "top" if i >= 3 else "bottom"
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + y_offset,
            f"{val}%",
            ha="center",
            va=va,
            fontsize=9,
            color="white" if i >= 3 else C_BLUE,
        )

    # Line: skill count
    ax2 = ax1.twinx()
    (line,) = ax2.plot(
        rounds,
        skills,
        color=C_ORANGE,
        marker="o",
        markersize=8,
        linewidth=2.2,
        zorder=5,
    )
    ax2.set_ylabel("Skills in Library", color=C_ORANGE)
    ax2.set_ylim(40, 130)
    ax2.tick_params(axis="y", labelcolor=C_ORANGE)

    # Annotate line points — offset R4/R5 downwards to avoid bar labels
    for i, (x, y) in enumerate(zip(rounds, skills)):
        y_offset = -20 if i >= 3 else 10
        ax2.annotate(
            str(y),
            (x, y),
            textcoords="offset points",
            xytext=(0, y_offset),
            ha="center",
            fontsize=9,
            color=C_ORANGE,
        )

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=C_BLUE, alpha=0.85, label="Non-Default Q Ratio"),
        plt.Line2D([0], [0], color=C_ORANGE, marker="o", linewidth=2.2, label="Skills in Library"),
    ]
    ax1.legend(handles=legend_elements, loc="upper left", framealpha=0.9)

    ax1.set_title("Q-Table Convergence & Skill Library Growth (Series B)")
    ax1.set_xlabel("Round")
    ax1.grid(axis="y", alpha=0.3, zorder=0)

    fig.tight_layout()
    fig.savefig(OUT / "fig1_q_convergence.pdf")
    fig.savefig(OUT / "fig1_q_convergence.png")
    plt.close(fig)
    print("  ✓ fig1_q_convergence.pdf")


# =====================================================================
# Figure 2: Q-value vs pass rate (grouped bar)
# =====================================================================
def fig2_q_vs_passrate() -> None:
    labels = ["≤0.35", "0.40", "0.45", "0.50\n(default)", "0.55", "0.60", "≥0.65"]
    pass_rates = [0, 0, 0, 47, 93, 90, 100]
    trials = [10, 15, 8, 15, 14, 20, 7]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = range(len(labels))
    bars = ax.bar(x, pass_rates, color=BAR_COLORS, width=0.6, edgecolor="white", linewidth=0.5)

    # Colour the significant bars
    for i in [3, 4, 5, 6]:
        bars[i].set_color(C_GREEN)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Pass Rate (%)")
    ax.set_xlabel("Q-Value Range")
    ax.set_title("Q-Value vs Task Pass Rate (Series A, R2 Data)")
    ax.set_ylim(0, 110)

    # Annotate
    for bar, pr, tr in zip(bars, pass_rates, trials):
        color = C_GREEN if pr >= 90 else C_RED if pr == 0 else C_GREY
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{pr}%\n(n={tr})",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=color,
        )

    # Threshold line
    ax.axhline(y=90, color=C_RED, linestyle="--", linewidth=1, alpha=0.5)
    ax.text(6.3, 92, "90% threshold", fontsize=8, color=C_RED, ha="right")

    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_q_vs_passrate.pdf")
    fig.savefig(OUT / "fig2_q_vs_passrate.png")
    plt.close(fig)
    print("  ✓ fig2_q_vs_passrate.pdf")


# =====================================================================
# Figure 3: Cross-round stability (stacked bar)
# =====================================================================
def fig3_stability() -> None:
    categories = ["Stable\nPass", "Stable\nFail", "Improved\n(Fail→Pass)", "Degraded\n(Pass→Fail)"]
    counts = [41, 31, 6, 6]
    colors_stacked = [C_GREEN, C_RED, C_BLUE, C_ORANGE]

    fig, ax = plt.subplots(figsize=(6, 4.5))
    bars = ax.bar(categories, counts, color=colors_stacked, width=0.55, edgecolor="white")

    for bar, val in zip(bars, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.8,
            f"{val} ({val/84*100:.0f}%)",
            ha="center",
            fontsize=10,
        )

    ax.set_ylabel("Number of Tasks")
    ax.set_title("Cross-Round Task Stability (R1 → R4, 84 Common Tasks)")
    ax.set_ylim(0, 52)
    ax.grid(axis="y", alpha=0.3)

    # Annotate total stability
    ax.text(
        0.98, 0.95, "Stability = 86%",
        transform=ax.transAxes, fontsize=11, ha="right", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=C_LIGHT, edgecolor=C_GREY, alpha=0.8),
    )

    fig.tight_layout()
    fig.savefig(OUT / "fig3_stability.pdf")
    fig.savefig(OUT / "fig3_stability.png")
    plt.close(fig)
    print("  ✓ fig3_stability.pdf")


# =====================================================================
# Figure 4: Per-round pass rate trend
# =====================================================================
def fig4_passrate_trend() -> None:
    rounds = ["R1", "R2", "R3", "R4", "R5"]
    pass_rates = [55.1, 53.9, 52.8, 57.6, 49.4]
    # Tasks per round: R1-R3=89, R4-R5=85
    tasks = [89, 89, 89, 85, 85]

    fig, ax = plt.subplots(figsize=(7, 4.2))

    # Main line
    ax.plot(rounds, pass_rates, color=C_BLUE, marker="o", markersize=9, linewidth=2.2, zorder=5)

    # Annotate points with pass count
    for i, (r, pr, t) in enumerate(zip(rounds, pass_rates, tasks)):
        n_pass = int(round(pr * t / 100))
        ax.annotate(
            f"{pr:.1f}%\n({n_pass}/{t})",
            (r, pr),
            textcoords="offset points",
            xytext=(0, 18 if i != 4 else -22),
            ha="center",
            fontsize=9,
            color=C_BLUE,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor=C_BLUE, alpha=0.7),
        )

    # Baseline (50%)
    ax.axhline(y=50, color=C_GREY, linestyle=":", linewidth=1, alpha=0.6)
    ax.text(4.4, 50.8, "50% baseline", fontsize=8, color=C_GREY, ha="right")

    # R4-R5 change highlight
    ax.annotate(
        "",
        xy=(4, 49.4),
        xytext=(3, 57.6),
        arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.5),
    )
    ax.text(3.5, 53.5, "−8.2pp", fontsize=9, color=C_RED, ha="center", fontweight="bold")

    ax.set_ylabel("Pass Rate (%)")
    ax.set_xlabel("Round")
    ax.set_title("Pass Rate Trend Across Rounds (Series B)")
    ax.set_ylim(40, 65)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUT / "fig4_passrate_trend.pdf")
    fig.savefig(OUT / "fig4_passrate_trend.png")
    plt.close(fig)
    print("  ✓ fig4_passrate_trend.pdf")


# =====================================================================
# Main
# =====================================================================
if __name__ == "__main__":
    print("Generating SkillQ paper figures …")
    fig1_q_convergence()
    fig2_q_vs_passrate()
    fig3_stability()
    fig4_passrate_trend()
    print(f"Done. Figures saved to {OUT}/")
