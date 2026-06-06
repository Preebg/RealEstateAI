import json
import math
import unittest
from unittest.mock import patch

from scipy.optimize import minimize as scipy_minimize

# Mock streamlit before importing engine to avoid secrets errors
with patch("streamlit.secrets", {"GEMINI_API_KEY": "fake_key"}):
    from engine import calculate_quantum_probability, calculate_quantum_risk
    from engine import (
        DISCOVERY_FALLBACK_MODEL,
        DISCOVERY_MODEL,
        RESEARCH_MODEL,
        discover_hot_market_listings,
        is_daily_quota_exhausted,
        research_property,
        should_skip_synthesis,
    )
    from finance import calculate_10yr_appreciation
    from google.genai import errors

from qiskit_aer import AerSimulator

QUANTUM_RISK_KEYS = (
    "cashflow_success_pct",
    "appreciation_success_pct",
    "location_success_pct",
    "combined_wealth_success_pct",
    "overall_success_pct",
)

# Deterministic snapshots with AerSimulator(seed_simulator=42) and COBYLA (maxiter=30).
GOLDEN_PERFECT_RISK = {
    "cashflow_success_pct": 51.85546875,
    "appreciation_success_pct": 49.12109375,
    "location_success_pct": 48.6328125,
    "combined_wealth_success_pct": 25.68359375,
    "overall_success_pct": 10.9375,
}

GOLDEN_AVERAGE_RISK = {
    "cashflow_success_pct": 51.85546875,
    "appreciation_success_pct": 49.12109375,
    "location_success_pct": 48.6328125,
    "combined_wealth_success_pct": 25.68359375,
    "overall_success_pct": 10.9375,
}


def assert_valid_quantum_risk(test_case: unittest.TestCase, risk: dict[str, float]) -> None:
    """All breakdown fields must be finite and within [0, 100]."""
    for key in QUANTUM_RISK_KEYS:
        test_case.assertIn(key, risk)
        value = risk[key]
        test_case.assertFalse(math.isnan(value), f"{key} is NaN")
        test_case.assertFalse(math.isinf(value), f"{key} is infinite")
        test_case.assertGreaterEqual(value, 0.0, f"{key} below 0")
        test_case.assertLessEqual(value, 100.0, f"{key} above 100")


class TestAIUnderwriterEngine(unittest.TestCase):

    def test_calculate_10yr_appreciation_zero_value(self):
        """
        Test that passing a current_value of 0 returns the guard-clause
        dictionary instead of raising a ZeroDivisionError.
        """
        result = calculate_10yr_appreciation(0, 10)
        expected = {"future_value": 0, "annual_rate": 0, "total_growth": 0}
        self.assertEqual(result, expected)

    def test_calculate_quantum_probability_legacy(self):
        """
        Verify that calculate_quantum_probability correctly maps
        location_score 0 to 0%, 10 to 100%, and 5 to 50% for legacy single-argument calls.
        """
        self.assertAlmostEqual(calculate_quantum_probability(0), 0.0)
        self.assertAlmostEqual(calculate_quantum_probability(10), 100.0)
        self.assertAlmostEqual(calculate_quantum_probability(5), 50.0)

    def test_calculate_quantum_probability_qaoa_three_args(self):
        """
        Three-argument path runs the COBYLA hybrid loop (scipy.optimize.minimize)
        and returns deterministic, bounded probabilities.
        """
        with patch("engine.minimize", wraps=scipy_minimize) as mock_minimize:
            score_perfect = calculate_quantum_probability(1000.0, 10.0, 10.0)
            score_avg = calculate_quantum_probability(500.0, 5.0, 5.0)

        self.assertEqual(mock_minimize.call_count, 2)
        for call in mock_minimize.call_args_list:
            self.assertEqual(call.kwargs["method"], "COBYLA")
            self.assertEqual(call.kwargs["options"]["maxiter"], 30)

        risk_perfect = calculate_quantum_risk(1000.0, 10.0, 10.0)
        risk_avg = calculate_quantum_risk(500.0, 5.0, 5.0)
        assert_valid_quantum_risk(self, risk_perfect)
        assert_valid_quantum_risk(self, risk_avg)

        for key in QUANTUM_RISK_KEYS:
            self.assertAlmostEqual(risk_perfect[key], GOLDEN_PERFECT_RISK[key], places=4)
            self.assertAlmostEqual(risk_avg[key], GOLDEN_AVERAGE_RISK[key], places=4)

        self.assertAlmostEqual(score_perfect, GOLDEN_PERFECT_RISK["overall_success_pct"])
        self.assertAlmostEqual(score_avg, GOLDEN_AVERAGE_RISK["overall_success_pct"])

        score_poor = calculate_quantum_probability(0.0, 0.0, 0.0)
        self.assertEqual(score_poor, 0.0)

        with patch("engine.minimize", wraps=scipy_minimize) as mock_minimize:
            calculate_quantum_probability(0.0, 0.0, 0.0)
        mock_minimize.assert_not_called()

    def test_quantum_optimizer_convergence_perfect_property(self):
        """
        High-value inputs should yield strong marginal success rates after COBYLA
        minimizes the QAOA cost Hamiltonian (optimized cost <= initial cost).
        """
        opt_results: list = []
        call_records: list[tuple] = []

        def tracking_minimize(cost_function, x0, *args, **kwargs):
            result = scipy_minimize(cost_function, x0, *args, **kwargs)
            opt_results.append(result)
            call_records.append((cost_function, x0))
            return result

        with patch("engine.minimize", side_effect=tracking_minimize):
            risk = calculate_quantum_risk(1000.0, 10.0, 10.0)

        self.assertEqual(len(opt_results), 1)
        opt_result = opt_results[0]
        cost_function, x0 = call_records[0]
        initial_cost = cost_function(x0)

        self.assertLessEqual(
            opt_result.fun,
            initial_cost,
            "COBYLA should not increase the expected Hamiltonian cost",
        )
        self.assertTrue(math.isfinite(opt_result.fun))

        assert_valid_quantum_risk(self, risk)
        self.assertGreaterEqual(risk["combined_wealth_success_pct"], 20.0)
        self.assertGreaterEqual(risk["cashflow_success_pct"], 45.0)
        self.assertGreaterEqual(risk["appreciation_success_pct"], 45.0)
        self.assertGreater(
            risk["combined_wealth_success_pct"],
            risk["overall_success_pct"],
            "Marginal two-qubit success should exceed rare |111⟩ alignment",
        )

        for key, expected in GOLDEN_PERFECT_RISK.items():
            self.assertAlmostEqual(risk[key], expected, places=4)

    def test_quantum_optimizer_bounds(self):
        """Extreme inputs are clamped; outputs stay in [0, 100] with no optimizer failure."""
        extreme_cases = (
            (-1_000_000_000.0, 999_999.0, -1_000_000.0),
            (1_000_000_000.0, -500.0, 10_000.0),
            (50_000.0, 500.0, 500.0),
        )

        clamped_reference = calculate_quantum_risk(0.0, 10.0, 0.0)
        capped_reference = calculate_quantum_risk(1000.0, 0.0, 10.0)

        for cash_flow, forecast_rate, location_score in extreme_cases:
            with patch("engine.minimize", wraps=scipy_minimize) as mock_minimize:
                risk = calculate_quantum_risk(cash_flow, forecast_rate, location_score)

            mock_minimize.assert_called_once()
            assert_valid_quantum_risk(self, risk)

        self.assertEqual(
            calculate_quantum_risk(-1_000_000_000.0, 999_999.0, -1_000_000.0),
            clamped_reference,
        )
        self.assertEqual(
            calculate_quantum_risk(1_000_000_000.0, -500.0, 10_000.0),
            capped_reference,
        )
        all_zero = calculate_quantum_risk(-99_999.0, -99_999.0, -99_999.0)
        assert_valid_quantum_risk(self, all_zero)
        self.assertEqual(all_zero["overall_success_pct"], 0.0)

        with patch("engine.minimize", wraps=scipy_minimize) as mock_minimize:
            oversaturated = calculate_quantum_risk(50_000.0, 500.0, 500.0)
        mock_minimize.assert_called_once()
        assert_valid_quantum_risk(self, oversaturated)
        self.assertEqual(oversaturated, GOLDEN_PERFECT_RISK)

    def test_quantum_simulator_uses_fixed_seed(self):
        """Every AerSimulator.run in the QAOA path must pass seed_simulator=42."""
        seeds: list[int | None] = []
        original_run = AerSimulator.run

        def run_recording_seed(simulator, circuit, **kwargs):
            seeds.append(kwargs.get("seed_simulator"))
            return original_run(simulator, circuit, **kwargs)

        with patch.object(AerSimulator, "run", run_recording_seed):
            calculate_quantum_risk(500.0, 5.0, 5.0)

        self.assertGreaterEqual(len(seeds), 2, "optimize + final evaluation runs expected")
        self.assertTrue(all(seed == 42 for seed in seeds))

    def test_calculate_quantum_risk_breakdown(self):
        """Breakdown includes cash-flow and appreciation success probabilities."""
        risk = calculate_quantum_risk(1000.0, 10.0, 10.0)
        assert_valid_quantum_risk(self, risk)

        risk_poor = calculate_quantum_risk(0.0, 0.0, 0.0)
        self.assertEqual(risk_poor["combined_wealth_success_pct"], 0.0)

    def test_calculate_quantum_risk_legacy_location_only(self):
        """Legacy shortcut: zero cash flow + zero forecast maps location score to all fields."""
        breakdown_keys = QUANTUM_RISK_KEYS
        for score, expected in ((0, 0.0), (5, 50.0), (10, 100.0)):
            risk = calculate_quantum_risk(0, 0, score)
            for key in breakdown_keys:
                self.assertAlmostEqual(risk[key], expected)

    def test_calculate_quantum_risk_is_deterministic(self):
        """Same inputs must yield identical probabilities (fixed simulator seed)."""
        args = (500.0, 5.0, 5.0)
        first = calculate_quantum_risk(*args)
        second = calculate_quantum_risk(*args)
        self.assertEqual(first, second)

    def test_calculate_quantum_risk_clamps_negative_cash_flow(self):
        """Negative cash flow is clamped to 0 before QAOA normalization."""
        negative = calculate_quantum_risk(-500.0, 5.0, 5.0)
        zero_cf = calculate_quantum_risk(0.0, 5.0, 5.0)
        self.assertEqual(negative, zero_cf)


class TestDailyQuotaDetection(unittest.TestCase):
    def test_detects_explicit_daily_quota_message(self):
        err = errors.ClientError(
            429,
            {
                "error": {
                    "message": "Quota exceeded for metric generate_requests_per_model_per_day",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )
        self.assertTrue(is_daily_quota_exhausted(err))

    def test_detects_runtime_error_after_retry_exhaustion(self):
        cause = errors.ClientError(
            429,
            {"error": {"message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED"}},
        )
        wrapped = RuntimeError("Max retries (5) exceeded for model=gemini-2.5-flash")
        wrapped.__cause__ = cause
        self.assertTrue(is_daily_quota_exhausted(wrapped))

    def test_ignores_non_quota_client_errors(self):
        err = errors.ClientError(400, {"error": {"message": "Invalid request"}})
        self.assertFalse(is_daily_quota_exhausted(err))


class TestSearchGrounding(unittest.TestCase):
    def test_discovery_uses_search_for_gemini_and_gemma_fallback(self):
        with patch("engine.generate_with_retry", return_value="[]") as mock_gen:
            discover_hot_market_listings(model=DISCOVERY_MODEL)
            self.assertTrue(mock_gen.call_args.kwargs["use_search"])

            mock_gen.reset_mock()
            discover_hot_market_listings(model=DISCOVERY_FALLBACK_MODEL)
            self.assertTrue(mock_gen.call_args.kwargs["use_search"])

    def test_research_uses_search_grounding(self):
        payload = json.dumps(
            {
                "address": "1 Main St, Rochester, NY",
                "price": 150000,
                "taxes": 3000,
                "hoa": 0,
                "square_footage": 1200,
                "property_condition": "Good",
            }
        )
        with patch("engine.generate_with_retry", return_value=payload) as mock_gen:
            research_property("1 Main St, Rochester, NY")
            self.assertTrue(mock_gen.call_args.kwargs["use_search"])
            self.assertEqual(mock_gen.call_args.args[0], RESEARCH_MODEL)


class TestHarvestSkipLogic(unittest.TestCase):
    def test_skip_synthesis_on_zero_price(self):
        self.assertTrue(
            should_skip_synthesis({"property_condition": "Good", "price": 0})
        )


if __name__ == "__main__":
    unittest.main()
