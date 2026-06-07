"""QAOA-based portfolio alignment scoring for real-estate investment inputs."""

from __future__ import annotations

__all__ = (
    "ALIGNMENT_SCORE_KEYS",
    "CLASSICAL_QAOA_DIVERGENCE_HELP",
    "AlignmentBreakdown",
    "PortfolioInputs",
    "QuantumResult",
    "classical_baseline",
    "score_portfolio",
)

import logging
from dataclasses import dataclass
from typing import Final

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from scipy.optimize import minimize

_log = logging.getLogger(__name__)

ALIGNMENT_SCORE_KEYS: Final[tuple[str, ...]] = (
    "cashflow_success_pct",
    "appreciation_success_pct",
    "location_success_pct",
    "combined_wealth_success_pct",
    "overall_success_pct",
)

CLASSICAL_QAOA_DIVERGENCE_HELP: Final[str] = (
    "Classical and QAOA optimize the same alignment cost on cash flow, appreciation, "
    "and location. They diverge when finite QAOA shots, COBYLA iteration limits, or "
    "circuit parameter bounds prevent the quantum sampler from reaching the classical optimum."
)

COUPLING_WEIGHT: Final[float] = 0.15

_GAMMA_BOUNDS: Final[tuple[float, float]] = (0.0, 3.14159)
_BETA_BOUNDS: Final[tuple[float, float]] = (0.0, 1.57079)
_OPTIMIZE_SHOTS: Final[int] = 256
_FINAL_SHOTS: Final[int] = 1024
_SIMULATOR_SEED: Final[int] = 42


@dataclass(frozen=True, slots=True)
class PortfolioInputs:
    """Investment metrics fed into the alignment Hamiltonian."""

    monthly_cash_flow: float
    forecast_rate: float
    location_score: float


@dataclass(frozen=True, slots=True)
class AlignmentBreakdown:
    """Per-dimension alignment scores on a 0–100% scale."""

    cashflow_success_pct: float
    appreciation_success_pct: float
    location_success_pct: float
    combined_wealth_success_pct: float
    overall_success_pct: float

    def to_dict(self) -> dict[str, float]:
        return {
            "cashflow_success_pct": self.cashflow_success_pct,
            "appreciation_success_pct": self.appreciation_success_pct,
            "location_success_pct": self.location_success_pct,
            "combined_wealth_success_pct": self.combined_wealth_success_pct,
            "overall_success_pct": self.overall_success_pct,
        }


@dataclass(frozen=True, slots=True)
class QuantumResult:
    """QAOA alignment scores with parallel classical baselines."""

    qaoa: AlignmentBreakdown
    classical: AlignmentBreakdown

    @property
    def overall_success_pct(self) -> float:
        return self.qaoa.overall_success_pct

    def to_dict(self) -> dict[str, float]:
        merged = dict(self.qaoa.to_dict())
        for key, value in self.classical.to_dict().items():
            merged[f"classical_{key}"] = value
        return merged


def _success_targets(
    cash_flow: float, forecast_rate: float, location_score: float
) -> tuple[float, float, float]:
    """
    Map investment inputs to [0, 1] success targets for each QAOA qubit.

    Negative or zero cash flow targets 0 (cash-flow qubit should stay |0⟩).
    """
    if cash_flow <= 0:
        cf_t = 0.0
    else:
        cf_t = min(cash_flow / 800.0, 1.0)

    rate_t = min(max(forecast_rate / 8.0, 0.0), 1.0)
    loc_t = min(max(location_score / 10.0, 0.0), 1.0)
    return cf_t, rate_t, loc_t


def _alignment_cost(
    x0: int, x1: int, x2: int, *, cf_t: float, rate_t: float, loc_t: float
) -> float:
    """Classical multi-objective cost: squared target misalignment plus pairwise coupling."""
    misalignment = (cf_t - x0) ** 2 + (rate_t - x1) ** 2 + (loc_t - x2) ** 2
    coupling = COUPLING_WEIGHT * ((x0 - x1) ** 2 + (x1 - x2) ** 2)
    return misalignment + coupling


def _scores_from_binary_state(
    x0: int, x1: int, x2: int, *, cf_t: float, rate_t: float, loc_t: float
) -> AlignmentBreakdown:
    """Map a {0,1}^3 alignment state to interpretable success percentages."""
    cf_pct = 100.0 * cf_t * x0
    app_pct = 100.0 * rate_t * x1
    loc_pct = 100.0 * loc_t * x2
    combined = 100.0 * cf_t * rate_t * x0 * x1
    overall = 0.45 * cf_pct + 0.35 * app_pct + 0.20 * loc_pct
    return AlignmentBreakdown(
        cashflow_success_pct=min(max(cf_pct, 0.0), 100.0),
        appreciation_success_pct=min(max(app_pct, 0.0), 100.0),
        location_success_pct=min(max(loc_pct, 0.0), 100.0),
        combined_wealth_success_pct=min(max(combined, 0.0), 100.0),
        overall_success_pct=min(max(overall, 0.0), 100.0),
    )


def _zero_alignment_breakdown() -> AlignmentBreakdown:
    return AlignmentBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)


def _legacy_location_only_breakdown(loc_t: float) -> AlignmentBreakdown:
    loc_pct = loc_t * 100.0
    return AlignmentBreakdown(loc_pct, loc_pct, loc_pct, loc_pct, loc_pct)


def classical_baseline(inputs: PortfolioInputs) -> AlignmentBreakdown:
    """
    Classical optimum for the same alignment objective minimized by QAOA.

    Exhaustively searches {0,1}^3 for the bitstring that minimizes squared
    target misalignment plus pairwise coupling, then maps that state to
    the same alignment scores as the quantum path.
    """
    cash_flow = inputs.monthly_cash_flow
    forecast_rate = inputs.forecast_rate
    location_score = inputs.location_score
    cf_t, rate_t, loc_t = _success_targets(cash_flow, forecast_rate, location_score)

    if cf_t == 0.0 and rate_t == 0.0 and loc_t == 0.0:
        return _zero_alignment_breakdown()

    if cf_t == 0.0 and rate_t == 0.0 and location_score > 0:
        return _legacy_location_only_breakdown(loc_t)

    best_cost = float("inf")
    best_state = (0, 0, 0)
    for x0 in (0, 1):
        for x1 in (0, 1):
            for x2 in (0, 1):
                cost = _alignment_cost(x0, x1, x2, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t)
                state = (x0, x1, x2)
                if cost < best_cost or (cost == best_cost and state > best_state):
                    best_cost = cost
                    best_state = state

    x0, x1, x2 = best_state
    return _scores_from_binary_state(x0, x1, x2, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t)


def _probabilities_from_measurement_counts(
    counts: dict[str, int],
    *,
    cf_t: float,
    rate_t: float,
    loc_t: float,
) -> AlignmentBreakdown:
    """
    Derive interpretable success probabilities from QAOA bitstrings.

    Qubit 0 = cash flow, qubit 1 = appreciation, qubit 2 = location.
    Each score scales the measured |1⟩ probability by the input target so
    negative cash flow cannot produce a high cash-flow success rate.
    """
    total = sum(counts.values()) or 1
    exp_x0 = exp_x1 = exp_x2 = 0.0

    for state_str, count in counts.items():
        prob = count / total
        bits = state_str.zfill(3)
        exp_x0 += prob * (bits[2] == "1")
        exp_x1 += prob * (bits[1] == "1")
        exp_x2 += prob * (bits[0] == "1")

    cf_pct = 100.0 * cf_t * exp_x0
    app_pct = 100.0 * rate_t * exp_x1
    loc_pct = 100.0 * loc_t * exp_x2
    combined = 100.0 * cf_t * rate_t * exp_x0 * exp_x1
    overall = 0.45 * cf_pct + 0.35 * app_pct + 0.20 * loc_pct

    return AlignmentBreakdown(
        cashflow_success_pct=min(max(cf_pct, 0.0), 100.0),
        appreciation_success_pct=min(max(app_pct, 0.0), 100.0),
        location_success_pct=min(max(loc_pct, 0.0), 100.0),
        combined_wealth_success_pct=min(max(combined, 0.0), 100.0),
        overall_success_pct=min(max(overall, 0.0), 100.0),
    )


def _clip_gamma_beta(params: list[float] | tuple[float, ...]) -> tuple[float, float]:
    gamma = min(max(float(params[0]), _GAMMA_BOUNDS[0]), _GAMMA_BOUNDS[1])
    beta = min(max(float(params[1]), _BETA_BOUNDS[0]), _BETA_BOUNDS[1])
    return gamma, beta


def _build_qaoa_circuit(
    gamma: float, beta: float, *, cf_t: float, rate_t: float, loc_t: float
) -> QuantumCircuit:
    qc = QuantumCircuit(3)
    qc.h([0, 1, 2])
    for i, target in enumerate([cf_t, rate_t, loc_t]):
        qc.rz(gamma * (2.0 * target - 1.0), i)
    qc.rzz(-COUPLING_WEIGHT * gamma, 0, 1)
    qc.rzz(-COUPLING_WEIGHT * gamma, 1, 2)
    for i in range(3):
        qc.rx(2 * beta, i)
    return qc


def _run_qaoa_alignment(
    *,
    cf_t: float,
    rate_t: float,
    loc_t: float,
) -> AlignmentBreakdown:
    def compute_cost(x0: int, x1: int, x2: int) -> float:
        return _alignment_cost(x0, x1, x2, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t)

    simulator = AerSimulator()

    def cost_function(params: list[float] | tuple[float, ...]) -> float:
        gamma, beta = _clip_gamma_beta(params)
        qc_measure = _build_qaoa_circuit(
            gamma, beta, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t
        ).copy()
        qc_measure.measure_all()
        compiled_circuit = transpile(qc_measure, simulator)
        job = simulator.run(
            compiled_circuit, shots=_OPTIMIZE_SHOTS, seed_simulator=_SIMULATOR_SEED
        )
        counts = job.result().get_counts()
        total = sum(counts.values()) or 1
        expected_cost = 0.0
        for state_str, count in counts.items():
            prob = count / total
            bits = state_str.zfill(3)
            x2 = int(bits[0])
            x1 = int(bits[1])
            x0 = int(bits[2])
            expected_cost += prob * compute_cost(x0, x1, x2)
        return expected_cost

    initial_params = [1.04719, 0.52359]
    final_gamma, final_beta = _clip_gamma_beta(initial_params)

    try:
        opt_result = minimize(
            cost_function,
            x0=initial_params,
            method="COBYLA",
            options={"maxiter": 30, "rhobeg": 0.35},
        )
        final_gamma, final_beta = _clip_gamma_beta(opt_result.x)
        if not opt_result.success:
            _log.warning(
                "qaoa_optimizer_did_not_converge message=%s nit=%s final_cost=%s "
                "gamma=%s beta=%s",
                opt_result.message,
                getattr(opt_result, "nit", None),
                float(opt_result.fun),
                final_gamma,
                final_beta,
            )
    except Exception:
        _log.exception(
            "qaoa_optimizer_failed gamma=%s beta=%s", final_gamma, final_beta
        )

    opt_qc = _build_qaoa_circuit(
        final_gamma, final_beta, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t
    )
    opt_qc.measure_all()
    compiled_circuit = transpile(opt_qc, simulator)
    job = simulator.run(
        compiled_circuit, shots=_FINAL_SHOTS, seed_simulator=_SIMULATOR_SEED
    )
    counts = job.result().get_counts()
    return _probabilities_from_measurement_counts(
        counts, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t
    )


def score_portfolio(inputs: PortfolioInputs) -> QuantumResult:
    """
    QAOA simulation returning cash-flow, appreciation, and combined wealth success odds,
    plus classical baseline scores from the same alignment objective.
    """
    cash_flow = inputs.monthly_cash_flow
    forecast_rate = inputs.forecast_rate
    location_score = inputs.location_score
    cf_t, rate_t, loc_t = _success_targets(cash_flow, forecast_rate, location_score)
    classical = classical_baseline(inputs)

    if cf_t == 0.0 and rate_t == 0.0 and loc_t == 0.0:
        return QuantumResult(qaoa=_zero_alignment_breakdown(), classical=classical)

    if cf_t == 0.0 and rate_t == 0.0 and location_score > 0:
        return QuantumResult(
            qaoa=_legacy_location_only_breakdown(loc_t), classical=classical
        )

    qaoa = _run_qaoa_alignment(cf_t=cf_t, rate_t=rate_t, loc_t=loc_t)
    return QuantumResult(qaoa=qaoa, classical=classical)
