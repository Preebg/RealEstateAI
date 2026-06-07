from fpdf import FPDF
import datetime
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _build_quantum_risk_chart(quantum_risk: dict) -> bytes:
    """Bar chart of QAOA alignment scores by dimension."""
    labels = [
        "Cash Flow\nAlignment",
        "Appreciation\nAlignment",
        "Combined CF+App\n(Joint |1⟩)",
        "Overall\n(Cost-Based)",
    ]
    values = [
        quantum_risk["cashflow_success_pct"],
        quantum_risk["appreciation_success_pct"],
        quantum_risk["combined_wealth_success_pct"],
        quantum_risk["overall_success_pct"],
    ]
    colors = ["#3498db", "#9b59b6", "#2ecc71", "#e67e22"]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, values, color=colors, edgecolor="#333333", linewidth=0.8)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Optimization Alignment (%)")
    ax.set_title("QAOA Alignment Analysis", fontsize=14, fontweight="bold")
    ax.axhline(50, color="#95a5a6", linestyle="--", linewidth=1, alpha=0.7)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_property_pdf(
    address,
    property_info,
    metrics,
    table_data,
    params,
    location_score,
    quantum_risk=None,
):
    pdf = FPDF()
    pdf.add_page()

    # Header & Address
    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 10, "Property Analysis Report", ln=True, align="C")
    pdf.set_font("Times", "", 12)
    pdf.cell(0, 10, f"Address: {address}", ln=True, align="C")
    pdf.ln(5)

    # Investment Parameters
    pdf.set_font("Times", "B", 11)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 8, "Investment Parameters", ln=True, fill=True)
    pdf.set_font("Times", "", 10)

    param_text = (
        f"Down Payment: {params['Down Payment']}  |  "
        f"Interest Rate: {params['Interest Rate']}  |  "
        f"Loan Term: {params['Loan Term']}"
    )
    pdf.cell(0, 8, param_text, ln=True)
    pdf.ln(5)

    # Summary Section
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 10, "Property Summary:", ln=True)
    pdf.set_font("Times", "", 10)
    pdf.multi_cell(0, 5, property_info.get("summary", "No summary available."))
    pdf.ln(5)

    # QAOA alignment section
    if quantum_risk:
        pdf.set_font("Times", "B", 12)
        pdf.cell(0, 10, "QAOA Alignment Analysis", ln=True)
        pdf.set_font("Times", "", 10)
        pdf.multi_cell(
            0,
            5,
            "Scores from a QAOA quantum simulation measuring how well a 3-qubit optimizer "
            "aligns with your normalized investment targets (cash flow, appreciation, "
            "location). Targets are encoded in the Hamiltonian only; these are "
            "optimization-alignment metrics, not predictions of market performance.",
        )
        pdf.ln(2)
        pdf.set_font("Times", "", 10)
        pdf.cell(
            0,
            6,
            f"Cash Flow Alignment (P qubit |1>): {quantum_risk['cashflow_success_pct']:.1f}%",
            ln=True,
        )
        pdf.cell(
            0,
            6,
            f"Appreciation Alignment (P qubit |1>): {quantum_risk['appreciation_success_pct']:.1f}%",
            ln=True,
        )
        pdf.cell(
            0,
            6,
            f"Combined CF+App Alignment (joint |1>): "
            f"{quantum_risk['combined_wealth_success_pct']:.1f}%",
            ln=True,
        )
        pdf.cell(
            0,
            6,
            f"Overall Alignment (expected cost mapped to score): "
            f"{quantum_risk['overall_success_pct']:.1f}%",
            ln=True,
        )
        pdf.ln(3)

        chart_png = _build_quantum_risk_chart(quantum_risk)
        chart_stream = io.BytesIO(chart_png)
        pdf.image(chart_stream, x=10, w=190)
        pdf.ln(5)

    # Detailed Breakdown Table
    pdf.set_font("Times", "B", 11)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 10, "Description", border=1, fill=True)
    pdf.cell(45, 10, "Monthly Amount", border=1, ln=True, fill=True)

    pdf.set_font("Times", "", 11)

    for i in range(len(table_data["Description"])):
        pdf.cell(95, 10, table_data["Description"][i], border=1)
        pdf.cell(45, 10, table_data["Amount"][i], border=1, ln=True)

    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Proprietary Location Score: {location_score}/10", ln=True)

    pdf.set_font("Arial", "I", 10)
    pdf.multi_cell(
        0,
        5,
        "This score represents a weighted analysis of local appreciation trends, "
        "school ratings, and neighborhood factors. Quantum alignment scores are "
        "separate optimization metrics and do not predict market volatility.",
    )
    pdf.ln(5)

    # Final Investment Metrics
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 10, "Final Projections:", ln=True)
    pdf.set_font("Times", "", 11)
    for label, value in metrics.items():
        pdf.cell(0, 8, f"{label}: {value}", ln=True)

    pdf.set_font("Times", "I", 8)
    pdf.ln(5)
    pdf.multi_cell(
        0,
        4,
        f"Report generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}. "
        "Quantum alignment scores are educational optimization simulations, not financial guarantees.",
    )

    return bytes(pdf.output())
