import json
import logging
import math
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from google.genai import errors

from scipy.optimize import minimize as scipy_minimize

_VERIFIED_DISCOVERY_ROW = {
    "address": "10 Park Ave, Rochester, NY 14607",
    "city": "Rochester",
    "list_price": 210000,
    "listing_url": "https://www.zillow.com/homedetails/10-Park-Ave-Rochester-NY-14607/123_zpid/",
}


def _discovery_generate_return(payload: str) -> tuple[str, list[str]]:
    return payload, []


# Mock streamlit before importing engine to avoid secrets errors
with patch("streamlit.secrets", {"GEMINI_API_KEY": "fake_key"}):
    from engine import (
        ALIGNMENT_SCORE_KEYS,
        calculate_quantum_probability,
        calculate_quantum_risk,
        clear_quantum_risk_cache,
    )
    from engine import (
        DISCOVERY_FALLBACK_MODEL,
        DISCOVERY_FALLBACK_MODELS,
        DISCOVERY_MODEL,
        DISCOVERY_MODEL_CHAIN,
        RESEARCH_MODEL,
        discover_hot_market_listings,
        DEFAULT_MODEL_RPM,
        SharedModelRateLimiter,
        acquire_model_rpm,
        is_daily_quota_exhausted,
        model_rpm_limit,
        research_property,
        is_disallowed_property_type,
        should_skip_synthesis,
        synthesis_skip_reason,
        research_stage_skip_reason,
        is_plausible_discovery_address,
        MAX_CONCURRENT_RESEARCH_AGENTS,
        _repair_discovery_address,
        _build_listings_from_raw,
    )
    from finance import (
        DEFAULT_METRO_CAGR,
        LOCATION_ADJUSTMENT_BAND,
        METRO_HISTORICAL_CAGR,
        calculate_10yr_appreciation,
        expected_annual_appreciation_rate,
        location_rate_adjustment,
        monte_carlo_appreciation_forecast,
        resolve_metro_base_rate,
    )
    from google.genai import errors

from qiskit_aer import AerSimulator

QUANTUM_RISK_KEYS = ALIGNMENT_SCORE_KEYS

ALL_RISK_KEYS = QUANTUM_RISK_KEYS

# Deterministic snapshots with AerSimulator(seed_simulator=42) and COBYLA (maxiter=30).
GOLDEN_PERFECT_RISK = {
    "cashflow_success_pct": 51.85546875,
    "appreciation_success_pct": 49.12109375,
    "location_success_pct": 48.6328125,
    "combined_wealth_success_pct": 25.471973419189453,
    "overall_success_pct": 50.25390625,
}

GOLDEN_AVERAGE_RISK = {
    "cashflow_success_pct": 32.40966796875,
    "appreciation_success_pct": 30.70068359375,
    "location_success_pct": 24.31640625,
    "combined_wealth_success_pct": 9.94998961687088,
    "overall_success_pct": 30.19287109375,
}


def assert_valid_quantum_risk(test_case: unittest.TestCase, risk: dict[str, float]) -> None:
    """All QAOA breakdown fields must be finite and within [0, 100]."""
    for key in ALL_RISK_KEYS:
        test_case.assertIn(key, risk)
        value = risk[key]
        test_case.assertFalse(math.isnan(value), f"{key} is NaN")
        test_case.assertFalse(math.isinf(value), f"{key} is infinite")
        test_case.assertGreaterEqual(value, 0.0, f"{key} below 0")
        test_case.assertLessEqual(value, 100.0, f"{key} above 100")


def _qaoa_subset(risk: dict[str, float]) -> dict[str, float]:
    return {key: risk[key] for key in QUANTUM_RISK_KEYS}


class TestAIUnderwriterEngine(unittest.TestCase):

    def test_calculate_10yr_appreciation_zero_value(self):
        """
        Test that passing a current_value of 0 returns the guard-clause
        dictionary instead of raising a ZeroDivisionError.
        """
        result = calculate_10yr_appreciation(0, 10, "Rochester")
        self.assertEqual(result["future_value"], 0)
        self.assertEqual(result["annual_rate"], 0)
        self.assertEqual(result["total_growth"], 0)
        self.assertEqual(result["future_value_p10"], 0)
        self.assertEqual(result["future_value_p50"], 0)
        self.assertEqual(result["future_value_p90"], 0)
        self.assertEqual(result["value_schedule_p50"], [])

    def test_location_rate_adjustment_bounded_band(self):
        self.assertAlmostEqual(location_rate_adjustment(5.0), 0.0)
        self.assertAlmostEqual(location_rate_adjustment(10.0), LOCATION_ADJUSTMENT_BAND)
        self.assertAlmostEqual(location_rate_adjustment(0.0), -LOCATION_ADJUSTMENT_BAND)
        # Scores outside 0–10 are clamped to the band edges.
        self.assertAlmostEqual(location_rate_adjustment(15.0), LOCATION_ADJUSTMENT_BAND)
        self.assertAlmostEqual(location_rate_adjustment(-5.0), -LOCATION_ADJUSTMENT_BAND)

    def test_resolve_metro_base_rate_known_and_unknown(self):
        self.assertAlmostEqual(resolve_metro_base_rate("Raleigh"), METRO_HISTORICAL_CAGR["Raleigh"])
        self.assertAlmostEqual(resolve_metro_base_rate("raleigh"), METRO_HISTORICAL_CAGR["Raleigh"])
        self.assertAlmostEqual(resolve_metro_base_rate("Unknown Metro"), DEFAULT_METRO_CAGR)
        self.assertAlmostEqual(resolve_metro_base_rate(None), DEFAULT_METRO_CAGR)

    def test_appreciation_monotonic_in_location_score(self):
        """Higher location score → higher or equal expected appreciation (fixed metro)."""
        market = "Charlotte"
        value = 250_000.0
        scores = [0.0, 2.5, 5.0, 7.5, 10.0]
        prior_rate = -1.0
        prior_future = -1.0
        for score in scores:
            rate = expected_annual_appreciation_rate(market, score)
            forecast = calculate_10yr_appreciation(value, score, market)
            self.assertGreaterEqual(rate, prior_rate)
            self.assertGreaterEqual(forecast["future_value_p50"], prior_future)
            self.assertGreaterEqual(forecast["annual_rate"], prior_rate * 100.0)
            prior_rate = rate
            prior_future = forecast["future_value_p50"]

    def test_appreciation_percentiles_ordered(self):
        forecast = calculate_10yr_appreciation(300_000, 6.5, "DFW")
        self.assertLessEqual(forecast["future_value_p10"], forecast["future_value_p50"])
        self.assertLessEqual(forecast["future_value_p50"], forecast["future_value_p90"])
        self.assertLessEqual(forecast["annual_rate_p10"], forecast["annual_rate_p50"])
        self.assertLessEqual(forecast["annual_rate_p50"], forecast["annual_rate_p90"])
        schedules = zip(
            forecast["value_schedule_p10"],
            forecast["value_schedule_p50"],
            forecast["value_schedule_p90"],
        )
        for low, mid, high in schedules:
            self.assertLessEqual(low, mid)
            self.assertLessEqual(mid, high)

    def test_appreciation_metro_changes_base_not_location_band(self):
        low_metro = calculate_10yr_appreciation(200_000, 5.0, "Syracuse")
        high_metro = calculate_10yr_appreciation(200_000, 5.0, "Austin")
        self.assertGreater(high_metro["metro_base_rate"], low_metro["metro_base_rate"])
        self.assertAlmostEqual(high_metro["location_adjustment"], 0.0)
        self.assertAlmostEqual(low_metro["location_adjustment"], 0.0)
        self.assertGreater(high_metro["future_value_p50"], low_metro["future_value_p50"])

    def test_monte_carlo_forecast_is_deterministic_with_seed(self):
        args = (275_000.0, "Rochester", 7.0)
        first = monte_carlo_appreciation_forecast(*args, seed=99)
        second = monte_carlo_appreciation_forecast(*args, seed=99)
        self.assertEqual(first["future_value_p50"], second["future_value_p50"])
        self.assertEqual(first["value_schedule_p50"], second["value_schedule_p50"])

    def test_expected_rate_matches_metro_plus_bounded_adjustment(self):
        market = "Ohio"
        score = 8.0
        expected = (
            resolve_metro_base_rate(market) + location_rate_adjustment(score)
        ) * 100.0
        forecast = calculate_10yr_appreciation(100_000, score, market)
        self.assertAlmostEqual(forecast["annual_rate"], expected)
        self.assertAlmostEqual(
            forecast["location_adjustment"],
            location_rate_adjustment(score) * 100.0,
        )

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
        with patch("quantum_portfolio.minimize", wraps=scipy_minimize) as mock_minimize:
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

        with patch("quantum_portfolio.minimize", wraps=scipy_minimize) as mock_minimize:
            calculate_quantum_probability(0.0, 0.0, 0.0)
        mock_minimize.assert_not_called()

    def test_quantum_optimizer_convergence_perfect_property(self):
        """
        High-value inputs should yield strong marginal success rates after COBYLA
        minimizes the QAOA cost Hamiltonian (optimized cost <= initial cost).
        """
        clear_quantum_risk_cache()
        opt_results: list = []
        call_records: list[tuple] = []

        def tracking_minimize(cost_function, x0, *args, **kwargs):
            result = scipy_minimize(cost_function, x0, *args, **kwargs)
            opt_results.append(result)
            call_records.append((cost_function, x0))
            return result

        with patch("quantum_portfolio.minimize", side_effect=tracking_minimize):
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
        self.assertGreaterEqual(risk["overall_success_pct"], 40.0)
        self.assertGreaterEqual(risk["cashflow_success_pct"], 45.0)
        self.assertGreaterEqual(risk["appreciation_success_pct"], 45.0)
        self.assertGreater(
            risk["overall_success_pct"],
            risk["combined_wealth_success_pct"],
            "Overall weighted score should exceed joint cash-flow + appreciation alignment",
        )

        for key, expected in GOLDEN_PERFECT_RISK.items():
            self.assertAlmostEqual(risk[key], expected, places=4)

    def test_quantum_optimizer_bounds(self):
        """Extreme inputs are clamped; outputs stay in [0, 100] with no optimizer failure."""
        clear_quantum_risk_cache()
        extreme_cases = (
            (-1_000_000_000.0, 999_999.0, -1_000_000.0),
            (1_000_000_000.0, -500.0, 10_000.0),
            (50_000.0, 500.0, 500.0),
        )

        clamped_reference = calculate_quantum_risk(0.0, 10.0, 0.0)
        capped_reference = calculate_quantum_risk(1000.0, 0.0, 10.0)

        for cash_flow, forecast_rate, location_score in extreme_cases:
            with patch("quantum_portfolio.minimize", wraps=scipy_minimize) as mock_minimize:
                risk = calculate_quantum_risk(cash_flow, forecast_rate, location_score)

            mock_minimize.assert_called_once()
            assert_valid_quantum_risk(self, risk)

        self.assertEqual(
            _qaoa_subset(calculate_quantum_risk(-1_000_000_000.0, 999_999.0, -1_000_000.0)),
            _qaoa_subset(clamped_reference),
        )
        self.assertEqual(
            _qaoa_subset(calculate_quantum_risk(1_000_000_000.0, -500.0, 10_000.0)),
            _qaoa_subset(capped_reference),
        )
        all_zero = calculate_quantum_risk(-99_999.0, -99_999.0, -99_999.0)
        assert_valid_quantum_risk(self, all_zero)
        self.assertEqual(all_zero["overall_success_pct"], 0.0)

        clear_quantum_risk_cache()
        with patch("quantum_portfolio.minimize", wraps=scipy_minimize) as mock_minimize:
            oversaturated = calculate_quantum_risk(50_000.0, 500.0, 500.0)
        mock_minimize.assert_called_once()
        assert_valid_quantum_risk(self, oversaturated)
        self.assertEqual(_qaoa_subset(oversaturated), GOLDEN_PERFECT_RISK)

    def test_quantum_risk_bounds_ordering_and_golden(self):
        """QAOA scores are bounded, rank perfect above poor inputs, and match golden fixtures."""
        fixtures = (
            ("perfect", (1000.0, 10.0, 10.0), GOLDEN_PERFECT_RISK),
            ("average", (500.0, 5.0, 5.0), GOLDEN_AVERAGE_RISK),
        )

        for _label, args, golden_qaoa in fixtures:
            risk = calculate_quantum_risk(*args)
            assert_valid_quantum_risk(self, risk)

            for key in QUANTUM_RISK_KEYS:
                self.assertAlmostEqual(risk[key], golden_qaoa[key], places=4)

        perfect = calculate_quantum_risk(1000.0, 10.0, 10.0)
        poor = calculate_quantum_risk(0.0, 0.0, 0.0)
        for key in QUANTUM_RISK_KEYS:
            self.assertGreater(perfect[key], poor[key])

    def test_quantum_simulator_uses_fixed_seed(self):
        """Every AerSimulator.run in the QAOA path must pass seed_simulator=42."""
        clear_quantum_risk_cache()
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
        """Negative cash flow yields 0% cash-flow success; great inputs score higher."""
        negative = calculate_quantum_risk(-500.0, 5.0, 5.0)
        great = calculate_quantum_risk(1000.0, 10.0, 10.0)
        self.assertEqual(negative["cashflow_success_pct"], 0.0)
        self.assertGreater(
            great["overall_success_pct"], negative["overall_success_pct"]
        )


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

    def test_generate_with_retry_fails_fast_on_daily_quota(self):
        from engine import generate_with_retry

        quota_err = errors.ClientError(
            429,
            {
                "error": {
                    "message": "Quota exceeded for metric generate_requests_per_model_per_day",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )
        with patch("engine.get_session") as mock_session:
            mock_session.return_value.client.models.generate_content.side_effect = (
                quota_err
            )
            with patch("engine.time.sleep") as mock_sleep:
                with self.assertRaises(errors.ClientError):
                    generate_with_retry(DISCOVERY_MODEL, "prompt")
                mock_sleep.assert_not_called()

    def test_discovery_switches_to_gemma_on_flash_quota(self):
        payload = json.dumps([_VERIFIED_DISCOVERY_ROW])
        quota_err = errors.ClientError(
            429,
            {
                "error": {
                    "message": "Quota exceeded for metric generate_requests_per_model_per_day",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )
        calls: list[str] = []

        def fake_generate(model, contents, **kwargs):
            calls.append(model)
            if model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
                raise quota_err
            return _discovery_generate_return(payload)

        with patch("engine._generate_with_grounding_retry", side_effect=fake_generate):
            listings = discover_hot_market_listings()
        self.assertEqual(len(listings), 1)
        self.assertEqual(calls[0], DISCOVERY_MODEL)
        self.assertEqual(
            DISCOVERY_MODEL_CHAIN,
            ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemma-4-26b-a4b-it"),
        )
        self.assertTrue(any(model == "gemma-4-26b-a4b-it" for model in calls))

    def test_discovery_on_listing_found_fires_per_new_listing(self):
        rochester_row = dict(_VERIFIED_DISCOVERY_ROW)
        syracuse_row = {
            "address": "20 E Genesee St, Syracuse, NY 13202",
            "city": "Syracuse",
            "list_price": 180000,
            "listing_url": "https://www.zillow.com/homedetails/20-E-Genesee-St-Syracuse-NY-13202/456_zpid/",
        }
        found: list[str] = []

        def fake_attempt(**kwargs):
            if kwargs.get("total_needed") is not None:
                return [], ""
            if kwargs.get("split_region") or kwargs.get("split_market"):
                return [rochester_row, syracuse_row], "regional"
            return [rochester_row, syracuse_row], "combined"

        with patch("engine._run_discovery_attempt", side_effect=fake_attempt):
            listings = discover_hot_market_listings(
                model=DISCOVERY_FALLBACK_MODEL,
                on_listing_found=lambda item: found.append(item["address"]),
            )

        self.assertGreaterEqual(len(found), 2)
        self.assertIn(rochester_row["address"], found)
        self.assertIn(syracuse_row["address"], found)
        self.assertGreaterEqual(len(listings), 2)


class TestModelRpmLimits(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_path = Path(self._tmpdir.name) / "rpm.json"
        self._limiter = SharedModelRateLimiter(self._state_path, window_sec=60.0)
        self._enforce_patch = patch(
            "engine._rpm_enforcement_enabled", return_value=True
        )
        self._enforce_patch.start()

    def tearDown(self) -> None:
        self._enforce_patch.stop()
        self._tmpdir.cleanup()

    def test_model_rpm_limits(self) -> None:
        self.assertEqual(model_rpm_limit("gemini-2.5-flash"), 5)
        self.assertEqual(model_rpm_limit("gemini-2.5-flash-lite"), 10)
        self.assertEqual(model_rpm_limit("gemma-4-26b-a4b-it"), DEFAULT_MODEL_RPM)
        self.assertEqual(model_rpm_limit("gemma-4-31b-it"), DEFAULT_MODEL_RPM)

    def test_flash_rpm_window_blocks_immediate_extra_call(self) -> None:
        for _ in range(5):
            self.assertIsNone(self._limiter.try_acquire("gemini-2.5-flash"))
        wait_sec = self._limiter.try_acquire("gemini-2.5-flash")
        self.assertIsNotNone(wait_sec)
        self.assertGreater(wait_sec or 0.0, 0.0)

    def test_shared_rpm_across_pipelines(self) -> None:
        other = SharedModelRateLimiter(self._state_path, window_sec=60.0)
        for _ in range(13):
            self._limiter.try_acquire("gemma-4-31b-it")
        wait_sec = other.try_acquire("gemma-4-31b-it")
        self.assertIsNotNone(wait_sec)

    def test_generate_with_retry_uses_shared_rpm(self) -> None:
        from engine import generate_with_retry

        with patch("engine.get_shared_model_rate_limiter", return_value=self._limiter):
            with patch("engine.get_session") as mock_session:
                mock_session.return_value.client.models.generate_content.return_value = (
                    type("Resp", (), {"text": "ok"})()
                )
                for _ in range(5):
                    generate_with_retry("gemini-2.5-flash", "prompt")
                wait_sec = self._limiter.try_acquire("gemini-2.5-flash")
        self.assertIsNotNone(wait_sec)


class TestSearchGrounding(unittest.TestCase):
    def test_discovery_uses_search_for_gemini_and_gemma_fallback(self):
        with patch(
            "engine._generate_with_grounding_retry",
            return_value=_discovery_generate_return("[]"),
        ) as mock_gen:
            for discovery_model in DISCOVERY_MODEL_CHAIN:
                discover_hot_market_listings(model=discovery_model)
                self.assertTrue(mock_gen.call_args.kwargs["use_search"])
                mock_gen.reset_mock()

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

    def test_research_uses_only_gemma_31b(self):
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
            self.assertEqual(mock_gen.call_args.args[0], RESEARCH_MODEL)
            self.assertEqual(RESEARCH_MODEL, "gemma-4-31b-it")

    def test_discovery_enables_maps_only_for_gemini(self):
        with patch(
            "engine._generate_with_grounding_retry",
            return_value=_discovery_generate_return("[]"),
        ) as mock_gen:
            for discovery_model in DISCOVERY_MODEL_CHAIN:
                discover_hot_market_listings(model=discovery_model)
                use_maps = mock_gen.call_args.kwargs.get("use_maps")
                if discovery_model.startswith("gemini"):
                    self.assertTrue(use_maps, discovery_model)
                else:
                    self.assertFalse(use_maps, discovery_model)
                mock_gen.reset_mock()


class TestGeospatialEnrichment(unittest.TestCase):
    def test_geocoding_and_synthesis_model_chains(self):
        from engine import (
            COORDINATE_CATCH_MODEL,
            GEOCODING_MODEL_CHAIN,
            PROPERTY_VALUE_MODEL,
            PROPERTY_VALUE_TRIGGERED_MODEL,
            SYNTHESIS_MODEL,
            SYNTHESIS_MODEL_CHAIN,
        )

        self.assertEqual(
            GEOCODING_MODEL_CHAIN,
            ("gemini-2.5-flash", "gemini-2.5-flash-lite"),
        )
        self.assertEqual(SYNTHESIS_MODEL, "gemini-3.1-flash-lite-preview")
        self.assertEqual(COORDINATE_CATCH_MODEL, SYNTHESIS_MODEL)
        self.assertEqual(PROPERTY_VALUE_MODEL, "gemma-4-26b-a4b-it")
        self.assertEqual(PROPERTY_VALUE_TRIGGERED_MODEL, "gemma-4-31b-it")
        self.assertEqual(
            SYNTHESIS_MODEL_CHAIN,
            (
                "gemini-3.1-flash-lite-preview",
                "gemini-3.5-flash",
                "gemma-4-26b-a4b-it",
            ),
        )

    def test_property_value_trigger_keywords(self):
        from engine import matches_property_value_trigger

        self.assertTrue(matches_property_value_trigger("Turnkey Rental"))
        self.assertTrue(matches_property_value_trigger("cash-flower"))
        self.assertTrue(matches_property_value_trigger("Suburban Core Rental"))
        self.assertTrue(matches_property_value_trigger("buy and hold"))
        self.assertTrue(matches_property_value_trigger("Strong Cash Flowing Asset"))
        self.assertFalse(matches_property_value_trigger("Value-Add Play"))
        self.assertFalse(matches_property_value_trigger(""))

    def test_coordinate_catch_only_when_discovery_lacked_maps(self):
        from engine import (
            DISCOVERY_MODEL,
            DISCOVERY_FALLBACK_MODEL,
            _needs_coordinate_catch,
        )

        self.assertFalse(
            _needs_coordinate_catch(DISCOVERY_MODEL, 43.1, -77.6),
        )
        self.assertTrue(
            _needs_coordinate_catch(DISCOVERY_MODEL, None, None),
        )
        self.assertTrue(
            _needs_coordinate_catch(DISCOVERY_MODEL, 0.0, 0.0),
        )
        self.assertTrue(
            _needs_coordinate_catch(DISCOVERY_FALLBACK_MODEL, None, None),
        )
        self.assertTrue(
            _needs_coordinate_catch(DISCOVERY_FALLBACK_MODEL, 0.0, 0.0),
        )

    def test_run_geospatial_enrichment_uses_search_then_maps(self):
        from engine import run_geospatial_enrichment

        scout_payload = json.dumps(
            {
                "latitude": 43.15,
                "longitude": -77.60,
                "confidence": "medium",
            }
        )
        maps_payload = json.dumps(
            {
                "latitude": 43.15612,
                "longitude": -77.60845,
                "confidence": "high",
                "environmental_risk": {
                    "score": 3.5,
                    "level": "Low",
                    "factors": ["No major flood zone flagged"],
                    "summary": "Low environmental risk for this parcel.",
                },
            }
        )

        with patch(
            "engine._generate_with_grounding_retry",
            return_value=(scout_payload, []),
        ) as mock_search, patch(
            "engine._generate_with_map_grounding_retry",
            return_value=(maps_payload, [{"place_id": "places/abc", "uri": "https://maps"}]),
        ) as mock_maps:
            result = run_geospatial_enrichment(
                "10 Park Ave, Rochester, NY 14607",
                market_city="Rochester",
            )

        self.assertTrue(mock_search.called)
        self.assertTrue(mock_maps.called)
        self.assertAlmostEqual(result["latitude"], 43.15612, places=4)
        self.assertAlmostEqual(result["longitude"], -77.60845, places=4)
        self.assertEqual(result["geocode_confidence"], "high")
        self.assertEqual(result["environmental_risk"]["level"], "Low")

    def test_attach_geospatial_penalizes_location_score_for_high_risk(self):
        from engine import attach_geospatial_to_property

        updated = attach_geospatial_to_property(
            {"location_score": 8.0},
            {
                "latitude": 43.15,
                "longitude": -77.60,
                "environmental_risk": {"score": 8.0, "level": "High", "factors": [], "summary": ""},
            },
        )
        self.assertLess(updated["location_score"], 8.0)

    def test_attach_geospatial_ignores_null_island(self):
        from engine import attach_geospatial_to_property

        updated = attach_geospatial_to_property(
            {"location_score": 8.0},
            {"latitude": 0.0, "longitude": 0.0, "geocode_confidence": "low"},
        )
        self.assertNotIn("latitude", updated)
        self.assertNotIn("longitude", updated)

    def test_sanitize_property_coordinates_strips_null_island_and_falls_back(self):
        from engine import sanitize_property_coordinates

        payload = {
            "address": "210 Everclay Dr, Rochester, NY 14618",
            "market_city": "Rochester",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        sanitize_property_coordinates(payload)
        self.assertNotEqual(payload.get("latitude"), 0.0)
        self.assertNotEqual(payload.get("longitude"), 0.0)
        self.assertEqual(payload.get("geocode_source"), "local_fallback")

    def test_attach_coordinates_prefers_stored_coords(self):
        from portfolio_map_page import attach_coordinates
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "address": "10 Park Ave, Rochester, NY 14607",
                    "zip_code": "14607",
                    "market_city": "Rochester",
                    "lat": 43.15612,
                    "lon": -77.60845,
                }
            ]
        )
        enriched = attach_coordinates(df)
        self.assertAlmostEqual(float(enriched.iloc[0]["lat"]), 43.15612, places=4)
        self.assertAlmostEqual(float(enriched.iloc[0]["lon"]), -77.60845, places=4)

    def test_attach_coordinates_falls_back_when_lat_lon_are_nan(self):
        """Missing DB coords become NaN in float columns; must still geocode locally."""
        from portfolio_map_page import attach_coordinates
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "address": "210 Everclay Dr, Rochester, NY 14618",
                    "zip_code": "14618",
                    "market_city": "Rochester",
                    "lat": None,
                    "lon": None,
                }
            ]
        )
        enriched = attach_coordinates(df)
        self.assertTrue(enriched["lat"].notna().iloc[0])
        self.assertTrue(enriched["lon"].notna().iloc[0])

    def test_attach_coordinates_ignores_null_island_sentinel(self):
        """Failed geocoding stores (0, 0); map must fall back to ZIP/market coords."""
        from portfolio_map_page import attach_coordinates
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "address": "210 Everclay Dr, Rochester, NY 14618",
                    "zip_code": "14618",
                    "market_city": "Rochester",
                    "lat": 0.0,
                    "lon": 0.0,
                }
            ]
        )
        enriched = attach_coordinates(df)
        lat = float(enriched.iloc[0]["lat"])
        lon = float(enriched.iloc[0]["lon"])
        self.assertNotAlmostEqual(lat, 0.0, places=3)
        self.assertNotAlmostEqual(lon, 0.0, places=3)
        self.assertAlmostEqual(lat, 43.1, delta=0.5)
        self.assertAlmostEqual(lon, -77.5, delta=0.5)


class TestHarvestSkipLogic(unittest.TestCase):
    def test_skip_synthesis_on_zero_price(self):
        self.assertTrue(
            should_skip_synthesis({"property_condition": "Good", "price": 0})
        )

    def test_disallowed_property_types(self):
        self.assertTrue(is_disallowed_property_type("Manufactured Home"))
        self.assertTrue(is_disallowed_property_type("Mobile Home"))
        self.assertTrue(is_disallowed_property_type("Multi-Family (6 units)"))
        self.assertTrue(is_disallowed_property_type("Apartment Building"))
        self.assertFalse(is_disallowed_property_type("Single Family"))
        self.assertFalse(is_disallowed_property_type("Townhome"))
        self.assertFalse(is_disallowed_property_type("Duplex"))
        self.assertFalse(is_disallowed_property_type("Triplex"))
        self.assertFalse(is_disallowed_property_type("Fourplex"))
        self.assertFalse(is_disallowed_property_type("Multi-Family (4 units)"))
        self.assertFalse(is_disallowed_property_type("Unknown"))

    def test_skip_synthesis_on_excluded_property_type(self):
        research = {
            "property_condition": "Good",
            "price": 200_000,
            "property_type": "Manufactured Home",
        }
        self.assertTrue(should_skip_synthesis(research))
        self.assertEqual(
            synthesis_skip_reason(research),
            "Excluded property type: Manufactured Home",
        )

    def test_research_stage_skips_sold_listing(self):
        research = {
            "property_condition": "Good",
            "price": 240_000,
            "property_type": "Single Family",
            "listing_status": "Sold",
        }
        self.assertEqual(
            research_stage_skip_reason(research),
            "Not actively for sale (Sold)",
        )

    def test_research_stage_skips_price_mismatch_with_discovery(self):
        research = {
            "property_condition": "Good",
            "price": 240_000,
            "property_type": "Single Family",
            "listing_status": "For Sale",
        }
        discovery = {
            "list_price": 540_000,
            "listing_url": "https://www.zillow.com/homedetails/example/123_zpid/",
        }
        reason = research_stage_skip_reason(research, discovery)
        self.assertIsNotNone(reason)
        self.assertIn("Price mismatch", reason or "")

    def test_max_concurrent_research_agents_is_thirteen(self):
        self.assertEqual(MAX_CONCURRENT_RESEARCH_AGENTS, 13)


class TestDiscoveryParsing(unittest.TestCase):
    def test_extract_wrapped_listings_object(self):
        from engine import _build_listings_from_raw

        raw = json.dumps({"listings": [{**_VERIFIED_DISCOVERY_ROW, "price": 210000}]})
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")
        self.assertEqual(listings[0]["list_price"], 210000.0)

    def test_discover_global_topup_when_combined_empty(self):
        calls = {"count": 0}

        def fake_generate(model, prompt, **kwargs):
            calls["count"] += 1
            if calls["count"] <= 4:
                return _discovery_generate_return("No parseable listings in this response.")
            return _discovery_generate_return(
                json.dumps(
                    [
                        {
                            "address": "15 Maple Dr, Rochester, NY 14609",
                            "city": "Rochester",
                            "list_price": 199000,
                            "listing_url": "https://www.redfin.com/NY/Rochester/15-Maple-Dr-14609/home/999",
                        }
                    ]
                )
            )

        with patch("engine._generate_with_grounding_retry", side_effect=fake_generate):
            listings = discover_hot_market_listings(model=DISCOVERY_MODEL)

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")
        self.assertGreaterEqual(calls["count"], 5)

    def test_plan_redistributes_unfilled_rochester_slots(self):
        from engine import (
            HOT_MARKETS,
            MAX_DISCOVERY_LISTINGS,
            _plan_market_discovery_pass,
            _scaled_market_target,
        )

        rochester_shortfall = _scaled_market_target("Rochester") - 3
        listings: list[dict] = []
        for name, _, _ in HOT_MARKETS:
            count = 3 if name == "Rochester" else _scaled_market_target(name)
            for idx in range(count):
                listings.append(
                    {
                        "address": f"{idx} Main St, {name} Metro",
                        "city": name,
                        "list_price": 180000.0,
                        "listing_url": f"https://www.zillow.com/homedetails/{name}-{idx}/",
                    }
                )

        self.assertEqual(len(listings), MAX_DISCOVERY_LISTINGS - rochester_shortfall)
        plan = _plan_market_discovery_pass(listings, {"Rochester"})
        planned_total = sum(count for _, count in plan)
        self.assertEqual(planned_total, rochester_shortfall)
        self.assertNotIn("Rochester", [market for market, _ in plan])
        self.assertEqual(plan[0][0], "Syracuse")

    def test_plan_keeps_trying_rochester_until_exhausted(self):
        from engine import (
            MAX_DISCOVERY_LISTINGS,
            _plan_market_discovery_pass,
            _scaled_market_target,
        )

        listings = [
            {
                "address": f"{idx} Main St, Rochester, NY",
                "city": "Rochester",
                "list_price": 180000.0,
                "listing_url": f"https://www.zillow.com/homedetails/rochester-{idx}/",
            }
            for idx in range(3)
        ]
        plan = _plan_market_discovery_pass(listings, set())
        rochester_need = next((count for name, count in plan if name == "Rochester"), 0)
        self.assertEqual(rochester_need, _scaled_market_target("Rochester") - 3)
        self.assertEqual(sum(count for _, count in plan), MAX_DISCOVERY_LISTINGS - len(listings))

    def test_discover_global_topup_after_partial_combined(self):
        calls = {"count": 0}

        def fake_discovery_attempt(**kwargs):
            calls["count"] += 1
            if kwargs.get("split_region") == "Upstate NY":
                payload = [
                    {
                        "address": f"{idx} Park Ave, Rochester, NY 1460{idx}",
                        "city": "Rochester",
                        "list_price": 189000 + idx * 1000,
                        "listing_url": (
                            f"https://www.zillow.com/homedetails/rochester-{idx}/"
                        ),
                    }
                    for idx in range(3)
                ]
                return payload, json.dumps(payload)
            if kwargs.get("total_needed"):
                rows = [
                    {
                        "address": "1 Oak St, Syracuse, NY 13039",
                        "city": "Syracuse",
                        "list_price": 195000,
                        "listing_url": "https://www.zillow.com/homedetails/syracuse-1/",
                    },
                    {
                        "address": "2 Pine Rd, Orlando, FL 32801",
                        "city": "Orlando",
                        "list_price": 210000,
                        "listing_url": "https://www.zillow.com/homedetails/orlando-2/",
                    },
                ]
                return rows, json.dumps(rows)
            return [], "[]"

        with patch("engine._run_discovery_attempt", side_effect=fake_discovery_attempt):
            listings = discover_hot_market_listings(model=DISCOVERY_MODEL)

        rochester_count = sum(1 for item in listings if item["city"] == "Rochester")
        self.assertEqual(rochester_count, 3)
        self.assertGreaterEqual(calls["count"], 2)
        self.assertGreater(len(listings), 3)

    def test_plan_region_collapses_carolinas_markets(self):
        from engine import _plan_region_discovery_pass

        plan = _plan_region_discovery_pass([], set())
        carolinas = next(
            (needs for region, needs in plan if region == "Carolinas"),
            None,
        )
        self.assertIsNotNone(carolinas)
        self.assertEqual(
            {market for market, _ in carolinas},
            {"Charlotte", "Raleigh", "Charleston"},
        )
        from engine import _scaled_market_target

        self.assertEqual(
            sum(need for _, need in carolinas),
            _scaled_market_target("Charlotte")
            + _scaled_market_target("Raleigh")
            + _scaled_market_target("Charleston"),
        )

    def test_suburb_address_maps_to_parent_metro(self):
        from engine import _build_listings_from_raw

        raw = json.dumps(
            [
                {
                    "address": "22 Suburban Ln, Henrietta, NY 14623",
                    "city": "Rochester",
                    "list_price": 185000,
                    "listing_url": "https://www.realtor.com/realestateandhomes-detail/22-Suburban-Ln",
                }
            ]
        )
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")

    def test_rejects_hallucinated_rows_without_listing_url(self):
        from engine import _build_listings_from_raw

        raw = json.dumps(
            [
                {
                    "address": "999 Fake St, Rochester, NY 14607",
                    "city": "Rochester",
                    "list_price": 150000,
                }
            ]
        )
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(listings, [])

    def test_rejects_zero_list_price(self):
        from engine import _build_listings_from_raw

        raw = json.dumps([{**_VERIFIED_DISCOVERY_ROW, "list_price": 0}])
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(listings, [])

    def test_accepts_full_state_name_in_address(self):
        from engine import is_plausible_discovery_address

        address = "100 Pine St, Charlotte, North Carolina 28202"
        self.assertTrue(is_plausible_discovery_address(address))

    def test_repair_backslash_truncated_pittsburgh(self):
        raw = r"412 Oak Ave, \ittsburg, PA 15213"
        repaired = _repair_discovery_address(raw)
        self.assertIn("Pittsburgh", repaired)
        self.assertTrue(is_plausible_discovery_address(repaired))

    def test_repair_trailing_backslash_city(self):
        raw = r"412 Oak Ave, Pittsburg\, PA 15213"
        repaired = _repair_discovery_address(raw)
        self.assertIn("Pittsburgh", repaired)
        payload = json.dumps(
            [
                {
                    "address": raw,
                    "city": "Pittsburgh",
                    "list_price": 185000,
                    "listing_url": "https://www.zillow.com/homedetails/pittsburgh-oak/123_zpid/",
                }
            ]
        )
        listings = _build_listings_from_raw(payload, 250_000)
        self.assertEqual(len(listings), 1)
        self.assertIn("Pittsburgh", listings[0]["address"])

    def test_repair_misspelled_city_without_state(self):
        raw = "100 Main St, ittsburgh, 15213"
        repaired = _repair_discovery_address(raw)
        self.assertIn("Pittsburgh", repaired)
        self.assertIn("PA", repaired)
        self.assertTrue(is_plausible_discovery_address(repaired))

    def test_rejects_sold_discovery_row(self):
        from engine import _build_listings_from_raw

        raw = json.dumps(
            [
                {
                    **_VERIFIED_DISCOVERY_ROW,
                    "listing_status": "Sold",
                }
            ]
        )
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(listings, [])

    def test_discovery_regions_run_sequentially(self):
        from engine import DISCOVERY_MODEL, _execute_region_discovery_plan

        call_order: list[str] = []

        def fake_run_single_region_discovery(**kwargs: object) -> tuple:
            call_order.append(str(kwargs.get("region_key")))
            return (
                str(kwargs.get("region_key")),
                list(kwargs.get("market_needs") or []),
                [],
                "[]",
                0.0,
            )

        plan = [
            ("Upstate NY", [("Rochester", 2)]),
            ("Florida", [("Orlando", 1)]),
        ]
        with patch(
            "engine._run_single_region_discovery",
            side_effect=fake_run_single_region_discovery,
        ):
            _execute_region_discovery_plan(
                plan,
                model=DISCOVERY_MODEL,
                max_price=250_000,
                exclude_addresses=None,
                split_listings=[],
                rate_limiter=None,
            )
        self.assertEqual(call_order, ["Upstate NY", "Florida"])

    def test_accepts_grounded_row_without_explicit_listing_url(self):
        from engine import _build_listings_from_raw

        row = {
            "address": "15 Maple Dr, Rochester, NY 14609",
            "city": "Rochester",
            "list_price": 199000,
        }
        grounding_urls = [
            "https://www.zillow.com/homedetails/15-Maple-Dr-Rochester-NY-14609/999_zpid/",
        ]
        listings = _build_listings_from_raw(
            json.dumps([row]),
            250_000,
            grounding_urls=grounding_urls,
        )
        self.assertEqual(len(listings), 1)
        self.assertIn("zillow.com", listings[0]["listing_url"])


class TestOneYearROI(unittest.TestCase):
    def test_unreliable_roi_threshold(self):
        from finance import MAX_RELIABLE_ONE_YEAR_ROI_PCT, is_unreliable_one_year_roi

        self.assertFalse(is_unreliable_one_year_roi(100.0))
        self.assertTrue(is_unreliable_one_year_roi(100.01))
        self.assertFalse(is_unreliable_one_year_roi(MAX_RELIABLE_ONE_YEAR_ROI_PCT))

    def test_positive_appreciation_and_negative_cashflow(self):
        from finance import calculate_one_year_roi

        # $200k purchase, 4% annual growth, -$500/mo cash flow, 20% down
        roi = calculate_one_year_roi(
            current_price=200_000,
            predicted_value=210_000,
            forecast_rate_pct=4.0,
            monthly_net_cash_flow=-500,
            down_payment_pct=20.0,
            closing_costs_pct=3.0,
        )
        value_after_one_year = 200_000 * 1.04
        appreciation_gain = value_after_one_year - 200_000
        annual_cash_flow = -500 * 12
        down_payment = 200_000 * 0.20
        expected = ((appreciation_gain + annual_cash_flow) / down_payment) * 100.0
        self.assertAlmostEqual(roi, expected, places=2)
        self.assertLess(roi, appreciation_gain / down_payment * 100)

    def test_high_predicted_value_does_not_inflate_appreciation_gain(self):
        from finance import calculate_one_year_roi

        roi = calculate_one_year_roi(
            current_price=200_000,
            predicted_value=500_000,
            forecast_rate_pct=5.0,
            monthly_net_cash_flow=0.0,
            down_payment_pct=20.0,
        )
        expected_gain = 200_000 * 0.05
        expected = (expected_gain / (200_000 * 0.20)) * 100.0
        self.assertAlmostEqual(roi, expected, places=2)
        self.assertLess(roi, 50.0)

    def test_zero_price_returns_zero(self):
        from finance import calculate_one_year_roi

        self.assertEqual(
            calculate_one_year_roi(
                current_price=0,
                predicted_value=100_000,
                forecast_rate_pct=4.0,
                monthly_net_cash_flow=100,
            ),
            0.0,
        )

    def test_market_value_purchase_lowers_roi_when_list_below_market(self):
        from finance import calculate_one_year_roi_for_purchase

        list_roi = calculate_one_year_roi_for_purchase(
            purchase_price=180_000,
            predicted_value=200_000,
            forecast_rate_pct=4.0,
            monthly_rent=1_800,
            tax_rate=1.2,
            maint_percent=5.0,
        )
        market_roi = calculate_one_year_roi_for_purchase(
            purchase_price=200_000,
            predicted_value=200_000,
            forecast_rate_pct=4.0,
            monthly_rent=1_800,
            tax_rate=1.2,
            maint_percent=5.0,
        )
        self.assertLess(market_roi, list_roi)


class TestMarketCrashScenario(unittest.TestCase):
    _BASE_KWARGS = {
        "purchase_price": 200_000,
        "predicted_value": 210_000,
        "market_city": "Rochester",
        "location_score": 6.0,
        "down_payment_pct": 25.0,
        "interest_rate": 6.0,
        "loan_term": 30,
        "closing_costs_pct": 3.0,
        "tax_rate": 3.0,
        "monthly_insurance": 100.0,
        "monthly_hoa": 0.0,
        "maint_percent": 5.0,
        "monthly_rent": 1_800.0,
        "vacancy_reserve_pct": 6.0,
        "management_fee_pct": 10.0,
    }

    def test_severe_crash_lowers_value_and_equity(self):
        from finance import simulate_market_crash

        mild = simulate_market_crash(**self._BASE_KWARGS, price_drop_pct=10.0)
        severe = simulate_market_crash(**self._BASE_KWARGS, price_drop_pct=40.0)
        self.assertGreater(severe["crash_value"], 0.0)
        self.assertLess(severe["crash_value"], mild["crash_value"])
        self.assertLess(severe["equity_at_crash"], mild["equity_at_crash"])

    def test_stressed_cash_flow_worse_than_baseline(self):
        from finance import simulate_market_crash

        result = simulate_market_crash(
            **self._BASE_KWARGS,
            rent_decline_pct=20.0,
            vacancy_spike_pct=5.0,
        )
        self.assertLess(
            result["stressed_monthly_net_cash_flow"],
            result["baseline_monthly_net_cash_flow"],
        )
        self.assertLess(result["stressed_cash_on_cash"], result["baseline_cash_on_cash"])

    def test_crash_schedules_same_length_and_drop_at_year(self):
        from finance import simulate_market_crash

        crash_year = 3
        drop = 25.0
        result = simulate_market_crash(
            **self._BASE_KWARGS,
            crash_year=crash_year,
            price_drop_pct=drop,
        )
        baseline = result["baseline_value_schedule"]
        crash = result["crash_value_schedule"]
        self.assertEqual(len(baseline), len(crash))
        self.assertAlmostEqual(
            result["crash_value"],
            result["pre_crash_value"] * (1.0 - drop / 100.0),
            places=0,
        )
        self.assertLess(crash[crash_year], crash[crash_year - 1])

    def test_underwater_when_drop_exceeds_equity(self):
        from finance import simulate_market_crash

        kwargs = {
            **self._BASE_KWARGS,
            "purchase_price": 300_000,
            "predicted_value": 300_000,
            "down_payment_pct": 5.0,
            "price_drop_pct": 50.0,
            "crash_year": 1,
        }
        result = simulate_market_crash(**kwargs)
        self.assertTrue(result["is_underwater"])
        self.assertLess(result["equity_at_crash"], 0.0)

    def test_loan_balance_decreases_over_time(self):
        from finance import calculate_loan_balance

        bal_y1 = calculate_loan_balance(200_000, 25.0, 6.0, 30, 1)
        bal_y5 = calculate_loan_balance(200_000, 25.0, 6.0, 30, 5)
        bal_y0 = calculate_loan_balance(200_000, 25.0, 6.0, 30, 0)
        self.assertAlmostEqual(bal_y0, 150_000.0, places=0)
        self.assertLess(bal_y5, bal_y1)


class TestInsuranceNormalization(unittest.TestCase):
    def test_converts_likely_annual_premium_to_monthly(self):
        from finance import normalize_monthly_insurance

        self.assertAlmostEqual(normalize_monthly_insurance(960.0), 80.0)
        self.assertAlmostEqual(normalize_monthly_insurance(400.0), 400.0)
        self.assertAlmostEqual(normalize_monthly_insurance(120.0), 120.0)

    def test_sanitize_synthesis_insurance(self):
        from engine import _sanitize_synthesis_numerics

        data = {"insurance": 840}
        _sanitize_synthesis_numerics(data)
        self.assertAlmostEqual(data["insurance"], 70.0)


class TestRentResolution(unittest.TestCase):
    def test_resolve_monthly_rent_uses_one_percent_rule(self):
        from finance import resolve_monthly_rent

        self.assertAlmostEqual(
            resolve_monthly_rent({"price": 250_000, "rent": 0}),
            2_500.0,
        )

    def test_resolve_monthly_rent_prefers_listing_rent(self):
        from finance import resolve_monthly_rent

        self.assertAlmostEqual(
            resolve_monthly_rent(
                {"price": 250_000, "rent": 0},
                research={"stated_gross_monthly_rent": 1_850},
            ),
            1_850.0,
        )

    def test_resolve_monthly_rent_uses_rent_comps(self):
        from finance import resolve_monthly_rent

        self.assertAlmostEqual(
            resolve_monthly_rent(
                {
                    "price": 250_000,
                    "rent": 0,
                    "rent_comps_analysis": {"median_monthly_rent": 1_700},
                }
            ),
            1_700.0,
        )

    def test_backfill_property_rent_sets_ai_baseline(self):
        from knowledge_base import backfill_property_rent, get_ai_baseline_rent

        record = {"price": 200_000, "rent": 0, "original_ai_rent": 0}
        backfill_property_rent(record)
        self.assertAlmostEqual(record["rent"], 2_000.0)
        self.assertAlmostEqual(record["original_ai_rent"], 2_000.0)
        self.assertAlmostEqual(get_ai_baseline_rent(record), 2_000.0)

    def test_apply_rent_comps_fills_missing_rent(self):
        from rent_comps_analysis import apply_rent_comps_adjustment

        property_data = {"rent": 0, "square_footage": 1200}
        rent_comps = {
            "comp_suggested_rent": 1_650,
            "median_monthly_rent": 1_600,
            "is_underrented": False,
        }
        self.assertTrue(apply_rent_comps_adjustment(property_data, rent_comps))
        self.assertEqual(property_data["rent"], 1650)
        self.assertEqual(property_data["original_ai_rent"], 1650)


class TestTaxRateNormalization(unittest.TestCase):
    def test_converts_decimal_tax_rate_to_percent(self):
        from finance import normalize_tax_rate_percent

        self.assertAlmostEqual(normalize_tax_rate_percent(0.034), 3.4)
        self.assertAlmostEqual(normalize_tax_rate_percent(0.025), 2.5)
        self.assertAlmostEqual(normalize_tax_rate_percent(3.4), 3.4)
        self.assertAlmostEqual(normalize_tax_rate_percent(0.5), 0.5)

    def test_sanitize_synthesis_tax_rate(self):
        from engine import _sanitize_synthesis_numerics

        data = {"tax_rate": 0.034}
        _sanitize_synthesis_numerics(data)
        self.assertAlmostEqual(data["tax_rate"], 3.4)


class TestFeePercentNormalization(unittest.TestCase):
    def test_converts_decimal_vacancy_and_mgmt_to_percent(self):
        from finance import normalize_percent_rate

        self.assertAlmostEqual(normalize_percent_rate(0.06), 6.0)
        self.assertAlmostEqual(normalize_percent_rate(0.10), 10.0)
        self.assertAlmostEqual(normalize_percent_rate(6.0), 6.0)
        self.assertAlmostEqual(normalize_percent_rate(10.0), 10.0)

    def test_sanitize_synthesis_fee_rates(self):
        from engine import _sanitize_synthesis_numerics

        data = {"vacancy_rate": 0.06, "management_fee": 0.10}
        _sanitize_synthesis_numerics(data)
        self.assertAlmostEqual(data["vacancy_rate"], 6.0)
        self.assertAlmostEqual(data["management_fee"], 10.0)

    def test_enrich_preserves_stored_ai_fee_rates(self):
        from engine import enrich_with_forecast

        result = enrich_with_forecast(
            {"ai_vacancy_rate": 0.06, "ai_management_fee": 0.10, "predicted_value": 200000}
        )
        self.assertAlmostEqual(result["ai_vacancy_rate"], 6.0)
        self.assertAlmostEqual(result["ai_management_fee"], 10.0)

    def test_enrich_prefers_synthesis_fee_rates_when_present(self):
        from engine import enrich_with_forecast

        result = enrich_with_forecast(
            {
                "vacancy_rate": 0.05,
                "management_fee": 0.08,
                "ai_vacancy_rate": 99.0,
                "predicted_value": 200000,
            }
        )
        self.assertAlmostEqual(result["ai_vacancy_rate"], 5.0)
        self.assertAlmostEqual(result["ai_management_fee"], 8.0)


class TestUnreliableForeclosureROI(unittest.TestCase):
    def _foreclosure_like_listing(self) -> dict:
        return {
            "address": "99 Foreclosure Ln, Rochester, NY 14609",
            "price": 45_000,
            "predicted_value": 185_000,
            "forecast_rate": 4.0,
            "rent": 1_800,
            "tax_rate": 3.0,
            "insurance": 120,
            "hoa": 0,
            "maint_percent": 4.0,
            "ai_vacancy_rate": 5.0,
            "ai_management_fee": 10.0,
            "location_score": 6.0,
            "monthly_net_cash_flow": 900.0,
        }

    def test_foreclosure_like_listing_exceeds_roi_ceiling(self):
        from knowledge_base import (
            compute_one_year_roi_from_property,
            one_year_roi_unreliable_reason,
        )

        listing = self._foreclosure_like_listing()
        roi = compute_one_year_roi_from_property(listing)
        self.assertGreater(roi, 100.0)
        reason = one_year_roi_unreliable_reason(listing)
        self.assertIsNotNone(reason)
        self.assertIn("foreclosure", reason.lower())

    def test_save_harvest_skips_unreliable_listing(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_harvest_property

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        with patch("knowledge_base.get_client", return_value=mock_client):
            result = save_harvest_property(
                self._foreclosure_like_listing(),
                user_id="7f35bc1e-9de5-484d-8f73-27fd3da733eb",
            )

        self.assertIsNone(result)
        mock_table.upsert.assert_not_called()

    def test_save_canonical_unreliable_does_not_delete_existing(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_canonical_property

        listing = self._foreclosure_like_listing()
        listing["id"] = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        with patch("knowledge_base.delete_canonical_property_by_id") as mock_delete:
            result = save_canonical_property(
                listing,
                user_id="7f35bc1e-9de5-484d-8f73-27fd3da733eb",
                show_errors=False,
            )

        self.assertIsNone(result)
        mock_delete.assert_not_called()

    def test_purge_deletes_unreliable_rows(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import purge_unreliable_one_year_roi_properties

        bad_row = {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            **self._foreclosure_like_listing(),
        }
        good_row = {
            "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "address": "10 Main St, Rochester, NY 14609",
            "price": 200_000,
            "predicted_value": 205_000,
            "forecast_rate": 4.0,
            "original_ai_rent": 1_600,
            "tax_rate": 3.0,
            "insurance": 120,
            "hoa": 0,
            "original_ai_maint": 4.0,
            "ai_vacancy_rate": 5.0,
            "ai_management_fee": 10.0,
            "location_score": 6.0,
            "monthly_net_cash_flow": 250.0,
        }

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.delete.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )

        with (
            patch("knowledge_base.in_streamlit_app", return_value=False),
            patch(
                "knowledge_base._fetch_canonical_properties",
                return_value=[bad_row, good_row],
            ),
            patch("knowledge_base.get_client", return_value=mock_client),
        ):
            removed = purge_unreliable_one_year_roi_properties()

        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["address"], bad_row["address"])
        delete_calls = [
            call.args[0] for call in mock_client.table.call_args_list
        ]
        self.assertIn("user_saved_properties", delete_calls)
        self.assertIn("user_property_overrides", delete_calls)
        self.assertIn("properties", delete_calls)


class TestHarvestAiBaselines(unittest.TestCase):
    def test_save_harvest_moves_rent_to_original_ai_columns(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_harvest_property

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[{}])

        with patch("knowledge_base.get_client", return_value=mock_client):
            save_harvest_property(
                {
                    "address": "1 Test St, Rochester, NY",
                    "rent": 1500,
                    "maint_percent": 3.5,
                    "price": 200000,
                },
                user_id="7f35bc1e-9de5-484d-8f73-27fd3da733eb",
            )

        payload = mock_table.upsert.call_args.args[0]
        self.assertEqual(payload["original_ai_rent"], 1500.0)
        self.assertEqual(payload["original_ai_maint"], 3.5)
        self.assertNotIn("rent", payload)
        self.assertNotIn("maint_percent", payload)

    def test_display_rent_prefers_user_override_when_saved(self):
        from knowledge_base import get_effective_display_rent, get_official_rent

        record = {
            "original_ai_rent": 1400,
            "rent": 2100,
            "has_user_override": True,
        }
        self.assertEqual(get_effective_display_rent(record), 2100.0)
        self.assertEqual(get_official_rent(record), 2100.0)

    def test_merge_with_user_override(self):
        from knowledge_base import _merge_with_user_override

        canonical = {
            "id": "abc",
            "address": "1 Test St",
            "original_ai_rent": 1500,
            "ai_vacancy_rate": 5.0,
        }
        merged = _merge_with_user_override(
            canonical,
            {
                "rent": 1800,
                "vacancy_rate": 6.0,
                "management_fee": 9.0,
                "is_outlier": False,
                "override_notes": "",
            },
        )
        self.assertEqual(merged["rent"], 1800)
        self.assertEqual(merged["user_vacancy_rate"], 6.0)
        self.assertEqual(merged["original_ai_rent"], 1500)
        self.assertTrue(merged["has_user_override"])


class TestScannedAddressDetection(unittest.TestCase):
    def test_normalize_address_key(self):
        from knowledge_base import normalize_address_key

        self.assertEqual(
            normalize_address_key("  123 Main St,  Rochester, NY "),
            "123 main st, rochester, ny",
        )

    def test_is_property_already_scanned(self):
        from unittest.mock import patch

        from knowledge_base import is_property_already_scanned

        with patch(
            "knowledge_base._fetch_canonical_properties",
            return_value=[{"address": "10 Park Ave, Rochester, NY"}],
        ):
            self.assertTrue(is_property_already_scanned("10 Park Ave, Rochester, NY"))
            self.assertFalse(is_property_already_scanned("99 New Rd, Syracuse, NY"))

    def test_is_property_harvest_complete_requires_year_built(self):
        from unittest.mock import patch

        from knowledge_base import (
            get_harvest_complete_addresses,
            is_property_harvest_complete,
        )

        rows = {
            "10 park ave, rochester, ny": {
                "address": "10 Park Ave, Rochester, NY",
                "year_built": 1985,
            },
            "20 oak st, rochester, ny": {
                "address": "20 Oak St, Rochester, NY",
            },
        }
        with patch("knowledge_base.get_kb_raw_data", return_value=rows):
            self.assertTrue(is_property_harvest_complete("10 Park Ave, Rochester, NY"))
            self.assertFalse(is_property_harvest_complete("20 Oak St, Rochester, NY"))
            self.assertEqual(
                get_harvest_complete_addresses(),
                {"10 park ave, rochester, ny"},
            )

    def test_backfill_missing_year_built_catalog_upserts_when_found(self):
        from unittest.mock import patch

        from knowledge_base import backfill_missing_year_built_catalog

        row = {"address": "20 Oak St, Rochester, NY", "price": 200000}
        with (
            patch("knowledge_base.get_admin_uid", return_value="00000000-0000-0000-0000-000000000001"),
            patch("knowledge_base._fetch_canonical_properties", return_value=[row]),
            patch(
                "engine.backfill_year_built_if_needed",
                return_value={**row, "year_built": 1962, "year": 1962},
            ),
            patch("knowledge_base.save_canonical_property", return_value=object()) as save_mock,
            patch("knowledge_base.invalidate_kb_cache") as invalidate_mock,
        ):
            results = backfill_missing_year_built_catalog(
                user_id="00000000-0000-0000-0000-000000000001"
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "backfilled")
        self.assertEqual(results[0]["year_built"], 1962)
        save_mock.assert_called_once()
        invalidate_mock.assert_called_once()

    def test_lookup_property_uses_normalized_address(self):
        from unittest.mock import patch

        from knowledge_base import lookup_property

        row = {
            "id": "7f35bc1e-9de5-484d-8f73-27fd3da733eb",
            "address": "123 Main St, Rochester, NY 14607",
            "price": 200000,
            "rent": 1500,
        }
        with patch("knowledge_base._fetch_canonical_properties", return_value=[row]):
            with patch("knowledge_base._fetch_user_overrides_map", return_value={}):
                hit = lookup_property("123 main st, rochester, ny 14607")
        self.assertIsNotNone(hit)
        self.assertTrue(hit.get("from_kb"))
        self.assertEqual(hit["price"], 200000)

    def test_get_kb_address_options_sorted(self):
        from unittest.mock import patch

        from knowledge_base import get_kb_address_options

        rows = [
            {"address": "28 Grant Ave, Rochester, NY"},
            {"address": "10 Park Ave, Rochester, NY"},
            {"address": "28 Grant Ave, Rochester, NY"},
        ]
        with patch("knowledge_base._fetch_canonical_properties", return_value=rows):
            with patch("knowledge_base._fetch_user_overrides_map", return_value={}):
                options = get_kb_address_options()
        self.assertEqual(
            options,
            ["10 Park Ave, Rochester, NY", "28 Grant Ave, Rochester, NY"],
        )

    def test_search_kb_addresses_filters_by_tokens(self):
        from unittest.mock import patch

        from knowledge_base import search_kb_addresses

        rows = [
            {"address": "28 Grant Ave, Rochester, NY"},
            {"address": "128 Grant St, Syracuse, NY"},
            {"address": "10 Park Ave, Rochester, NY"},
        ]
        with patch("knowledge_base._fetch_canonical_properties", return_value=rows):
            with patch("knowledge_base._fetch_user_overrides_map", return_value={}):
                matches = search_kb_addresses("28 grant")
        self.assertEqual(matches, ["28 Grant Ave, Rochester, NY"])


class TestResolveCanonicalPropertyId(unittest.TestCase):
    def test_prefers_valid_property_id_over_stale_cache(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import resolve_canonical_property_id

        stale_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        fresh_id = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
        address = "10 Park Ave, Rochester, NY 14609"

        with patch(
            "knowledge_base._property_exists_in_db",
            side_effect=lambda pid: pid == fresh_id,
        ):
            with patch(
                "knowledge_base.get_property_id_by_address",
                return_value=stale_id,
            ) as mock_lookup:
                resolved = resolve_canonical_property_id(address, property_id=fresh_id)

        self.assertEqual(resolved, fresh_id)
        mock_lookup.assert_not_called()

    def test_refreshes_cache_when_cached_id_is_missing(self):
        from unittest.mock import patch

        from knowledge_base import resolve_canonical_property_id

        stale_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        fresh_id = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
        address = "10 Park Ave, Rochester, NY 14609"

        with patch(
            "knowledge_base._property_exists_in_db",
            side_effect=lambda pid: pid == fresh_id,
        ):
            with patch(
                "knowledge_base.get_property_id_by_address",
                side_effect=[stale_id, fresh_id],
            ):
                with patch("knowledge_base.invalidate_kb_cache") as mock_invalidate:
                    resolved = resolve_canonical_property_id(address)

        self.assertEqual(resolved, fresh_id)
        mock_invalidate.assert_called_once()

    def test_save_knowledge_base_uses_fresh_upsert_id(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_knowledge_base

        user_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        fresh_id = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
        stale_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        property_data = {
            "address": "10 Park Ave, Rochester, NY 14609",
            "price": 200000,
            "rent": 1500,
        }

        with patch(
            "knowledge_base.save_canonical_property",
            return_value=MagicMock(data=[{"id": fresh_id}]),
        ):
            with patch(
                "knowledge_base.save_user_property_override",
                return_value=MagicMock(),
            ) as mock_override:
                save_knowledge_base(property_data, user_id=user_id)

        mock_override.assert_called_once()
        self.assertEqual(mock_override.call_args.args[1], fresh_id)


class TestMaintPercentNormalization(unittest.TestCase):
    def test_sanitize_synthesis_maint_percent(self):
        from engine import _sanitize_synthesis_numerics

        data = {"maint_percent": 0.04}
        _sanitize_synthesis_numerics(data)
        self.assertAlmostEqual(data["maint_percent"], 4.0)


class TestZipcodeParsing(unittest.TestCase):
    def test_parse_zipcode_from_standard_address(self):
        from knowledge_base import parse_zipcode_from_address

        self.assertEqual(
            parse_zipcode_from_address("123 Main St, Rochester, NY 14607"),
            "14607",
        )
        self.assertEqual(
            parse_zipcode_from_address("456 Oak Ave, Syracuse, NY 13202-1234"),
            "13202",
        )

    def test_parse_zipcode_returns_none_when_missing(self):
        from knowledge_base import parse_zipcode_from_address

        self.assertIsNone(parse_zipcode_from_address("123 Main St, Rochester, NY"))
        self.assertIsNone(parse_zipcode_from_address(""))

    def test_parse_state_code_from_standard_address(self):
        from knowledge_base import parse_state_code_from_address

        self.assertEqual(
            parse_state_code_from_address("123 Main St, Rochester, NY 14607"),
            "NY",
        )
        self.assertEqual(
            parse_state_code_from_address("4838 Gearus Dr, Charlotte, NC 28269"),
            "NC",
        )
        self.assertEqual(
            parse_state_code_from_address("1304 Sylvan Dr, Garland, TX 75040"),
            "TX",
        )
        self.assertEqual(
            parse_state_code_from_address("4207 Deepwood Ln, Cincinnati, OH 45245"),
            "OH",
        )
        self.assertEqual(
            parse_state_code_from_address("7955 Timbercreek UNIT G, North Charleston, SC 29418"),
            "SC",
        )

    def test_parse_state_code_returns_none_when_missing(self):
        from knowledge_base import parse_state_code_from_address

        self.assertIsNone(parse_state_code_from_address("123 Main St, Rochester"))
        self.assertIsNone(parse_state_code_from_address(""))

    def test_save_knowledge_base_includes_parsed_zipcode(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_canonical_property

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[{}])

        with patch("knowledge_base.get_client", return_value=mock_client):
            save_canonical_property(
                {
                    "address": "10 Park Ave, Rochester, NY 14609",
                    "price": 200000,
                },
                user_id="7f35bc1e-9de5-484d-8f73-27fd3da733eb",
            )

        payload = mock_table.upsert.call_args.args[0]
        self.assertEqual(payload["zip_code"], "14609")
        self.assertEqual(payload["state_code"], "NY")
        self.assertNotIn("rent", payload)

    def test_save_canonical_property_parses_non_ny_state(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_canonical_property

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[{}])

        with patch("knowledge_base.get_client", return_value=mock_client):
            save_canonical_property(
                {
                    "address": "4838 Gearus Dr, Charlotte, NC 28269",
                    "price": 200000,
                },
                user_id="7f35bc1e-9de5-484d-8f73-27fd3da733eb",
            )

        payload = mock_table.upsert.call_args.args[0]
        self.assertEqual(payload["state_code"], "NC")
        self.assertEqual(payload["zip_code"], "28269")


class TestPropertyComparison(unittest.TestCase):
    def test_build_property_comparison_metrics(self):
        from property_compare_page import build_property_comparison_metrics

        prop = {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "address": "10 Main St, Rochester, NY 14609",
            "price": 200000,
            "tax_rate": 3.0,
            "insurance": 150,
            "hoa": 0,
            "original_ai_rent": 1800,
            "original_ai_maint": 5.0,
            "ai_vacancy_rate": 5.0,
            "ai_management_fee": 10.0,
            "location_score": 7.5,
            "predicted_value": 210000,
            "forecast_rate": 4.5,
            "appreciation_forecast": 320000,
            "property_category": "Balanced",
        }

        metrics = build_property_comparison_metrics(prop)

        self.assertEqual(metrics["address"], prop["address"])
        self.assertGreater(metrics["monthly_net_cash_flow"], -5000)
        self.assertGreater(metrics["cap_rate"], 0)
        self.assertGreater(metrics["one_year_roi"], -100)
        self.assertEqual(metrics["strategy"], "Balanced")
        self.assertIn("quantum_overall", metrics)
        self.assertGreaterEqual(metrics["quantum_overall"], 0.0)
        self.assertLessEqual(metrics["quantum_overall"], 100.0)


class TestUserSavedProperties(unittest.TestCase):
    def test_save_property_to_user_account_bookmarks_existing_property(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_property_to_user_account

        mock_client = MagicMock()
        mock_saved = MagicMock()
        mock_client.table.return_value = mock_saved
        mock_saved.upsert.return_value.execute.return_value = MagicMock(data=[{}])

        user_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        property_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        with patch("knowledge_base.get_client", return_value=mock_client):
            with patch(
                "knowledge_base.save_user_property_override",
                return_value=MagicMock(),
            ) as mock_override:
                result = save_property_to_user_account(
                    user_id,
                    property_id=property_id,
                    override_payload={"rent": 1500.0},
                )

        self.assertEqual(result, property_id)
        mock_override.assert_called_once()
        mock_client.table.assert_called_with("user_saved_properties")
        bookmark_payload = mock_saved.upsert.call_args.args[0]
        self.assertEqual(bookmark_payload["user_id"], user_id)
        self.assertEqual(bookmark_payload["property_id"], property_id)

    def test_is_property_saved_for_user(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import is_property_saved_for_user

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "bookmark-id"}]
        )

        user_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        property_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        with patch("knowledge_base.get_client", return_value=mock_client):
            self.assertTrue(is_property_saved_for_user(user_id, property_id))
            self.assertFalse(is_property_saved_for_user(user_id, None))

    def test_save_property_blocked_at_max_limit(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import MAX_SAVED_PROPERTIES, save_property_to_user_account

        user_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        property_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        saved_rows = [
            {"id": f"row-{i}", "property_id": f"p{i}", "user_id": user_id}
            for i in range(MAX_SAVED_PROPERTIES)
        ]

        with patch(
            "knowledge_base.is_property_saved_for_user", return_value=False
        ):
            with patch(
                "knowledge_base._fetch_user_saved_rows", return_value=saved_rows
            ):
                with patch("knowledge_base.get_client") as mock_get_client:
                    result = save_property_to_user_account(
                        user_id,
                        property_id=property_id,
                        show_errors=False,
                    )

        self.assertIsNone(result)
        mock_get_client.assert_not_called()

    def test_clear_all_saved_properties_from_user_account(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import clear_all_saved_properties_from_user_account

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.delete.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[])
        )

        user_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"

        with patch("knowledge_base.get_client", return_value=mock_client):
            self.assertTrue(
                clear_all_saved_properties_from_user_account(
                    user_id, show_errors=False
                )
            )

        mock_client.table.assert_called_with("user_saved_properties")
        mock_table.delete.return_value.eq.assert_called_with("user_id", user_id)


class TestUuidValidation(unittest.TestCase):
    def test_rejects_typo_uuid_with_letter_l(self):
        from knowledge_base import is_valid_uuid

        self.assertFalse(is_valid_uuid("7f35bcel-9de5-484d-8f73-27fd3da733eb"))

    def test_accepts_valid_uuid(self):
        from knowledge_base import is_valid_uuid

        self.assertTrue(is_valid_uuid("7f35bc1e-9de5-484d-8f73-27fd3da733eb"))


class TestHeadlessDbClient(unittest.TestCase):
    def test_headless_prefers_service_role_client(self):
        import os
        from unittest.mock import MagicMock, patch

        mock_service = MagicMock()
        env = {
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "anon-key",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("authenticate._headless_mode", return_value=True):
                with patch("authenticate.get_authenticated_client", return_value=None):
                    with patch(
                        "authenticate.create_client", return_value=mock_service
                    ) as create:
                        from authenticate import get_db_client

                        client = get_db_client()
                        self.assertIs(client, mock_service)
                        create.assert_called_once_with(
                            "https://example.supabase.co", "service-role-key"
                        )

    def test_streamlit_prefers_authenticated_client(self):
        from unittest.mock import MagicMock, patch

        mock_auth = MagicMock()
        with patch("authenticate._headless_mode", return_value=False):
            with patch(
                "authenticate.get_authenticated_client", return_value=mock_auth
            ):
                with patch("authenticate.create_client") as create:
                    from authenticate import get_db_client

                    client = get_db_client()
                    self.assertIs(client, mock_auth)
                    create.assert_not_called()


class TestOAuthRedirectUrl(unittest.TestCase):
    def test_current_app_url_survives_context_url_key_error(self):
        from unittest.mock import patch

        with patch("authenticate._headless_mode", return_value=False):
            with patch.object(
                type(__import__("streamlit").context),
                "url",
                property(lambda self: (_ for _ in ()).throw(KeyError("url_pathname"))),
            ):
                with patch(
                    "authenticate._origin_from_request_headers",
                    return_value="https://capeigen.streamlit.app",
                ):
                    from authenticate import _current_app_url

                    self.assertEqual(_current_app_url(), "https://capeigen.streamlit.app")

    def test_prefers_live_app_url_over_localhost_secret(self):
        from unittest.mock import patch

        with patch("authenticate._headless_mode", return_value=False):
            with patch(
                "authenticate._current_app_url",
                return_value="https://my-app.streamlit.app",
            ):
                with patch(
                    "authenticate._configured_redirect_url",
                    return_value="http://localhost:8501",
                ):
                    from authenticate import _get_redirect_url

                    self.assertEqual(
                        _get_redirect_url(), "https://my-app.streamlit.app"
                    )

    def test_prefers_live_app_url_over_stale_cloud_secret(self):
        from unittest.mock import patch

        with patch("authenticate._headless_mode", return_value=False):
            with patch(
                "authenticate._current_app_url",
                return_value="https://capeigen.streamlit.app",
            ):
                with patch(
                    "authenticate._configured_redirect_url",
                    return_value="https://q-scout.streamlit.app",
                ):
                    from authenticate import _get_redirect_url

                    self.assertEqual(
                        _get_redirect_url(), "https://capeigen.streamlit.app"
                    )

    def test_uses_localhost_when_app_is_local(self):
        from unittest.mock import patch

        with patch("authenticate._headless_mode", return_value=False):
            with patch(
                "authenticate._current_app_url",
                return_value="http://localhost:8501",
            ):
                with patch(
                    "authenticate._configured_redirect_url",
                    return_value="http://localhost:8501",
                ):
                    from authenticate import _get_redirect_url

                    self.assertEqual(_get_redirect_url(), "http://localhost:8501")


class TestHeadlessDetection(unittest.TestCase):
    def test_streamlit_script_context_is_not_headless(self):
        from unittest.mock import MagicMock, patch

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "streamlit.runtime.scriptrunner.get_script_run_ctx",
                return_value=MagicMock(),
            ):
                from authenticate import _headless_mode, in_streamlit_app

                self.assertFalse(_headless_mode())
                self.assertTrue(in_streamlit_app())

    def test_cli_without_streamlit_context_is_headless(self):
        from unittest.mock import patch

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "streamlit.runtime.scriptrunner.get_script_run_ctx",
                return_value=None,
            ):
                from authenticate import _headless_mode

                self.assertTrue(_headless_mode())


class TestPropertyAge(unittest.TestCase):
    def test_parse_year_built_ignores_small_values(self):
        from engine import parse_year_built

        self.assertIsNone(parse_year_built({"year": 2}))
        self.assertIsNone(parse_year_built({"year_built": 50}))

    def test_parse_year_built_accepts_valid_construction_year(self):
        from engine import parse_year_built

        self.assertEqual(parse_year_built({"year_built": 1920}), 1920)
        self.assertEqual(parse_year_built({"year": 1968}), 1968)

    def test_calculate_property_age_is_current_year_minus_year_built(self):
        from engine import calculate_property_age_years

        year_built = 1920
        expected = date.today().year - year_built
        self.assertEqual(
            calculate_property_age_years({"year_built": year_built}),
            expected,
        )

    def test_calculate_property_age_rejects_placeholder_year_built(self):
        from engine import calculate_property_age_years

        current = date.today().year
        self.assertIsNone(calculate_property_age_years({"year_built": current}))

    def test_normalize_record_strips_placeholder_year_built(self):
        from knowledge_base import _normalize_record_numerics

        current = date.today().year
        normalized = _normalize_record_numerics({"year_built": current, "price": 100000})
        self.assertNotIn("year_built", normalized)

    def test_prepare_canonical_payload_clears_placeholder_year_built(self):
        from knowledge_base import _prepare_canonical_payload

        current = date.today().year
        payload = _prepare_canonical_payload(
            {"address": "1 Main St", "year": current, "price": 100000},
            "00000000-0000-0000-0000-000000000001",
        )
        self.assertIsNone(payload.get("year_built"))

    def test_prepare_canonical_payload_persists_listing_media(self):
        from knowledge_base import _prepare_canonical_payload

        payload = _prepare_canonical_payload(
            {
                "address": "10 Park Ave, Rochester, NY 14607",
                "price": 210000,
                "primary_image_url": " https://cdn.example/hero.jpg ",
                "image_urls": (
                    "https://cdn.example/hero.jpg",
                    "https://cdn.example/2.jpg",
                ),
                "listing_url": "https://www.redfin.com/NY/Rochester/10-Park-Ave/home/1",
                "days_on_market": "45",
                "view_count": None,
                "listing_status": "For Sale",
            },
            "00000000-0000-0000-0000-000000000001",
        )
        self.assertEqual(payload["primary_image_url"], "https://cdn.example/hero.jpg")
        self.assertEqual(
            payload["image_urls"],
            ["https://cdn.example/hero.jpg", "https://cdn.example/2.jpg"],
        )
        self.assertEqual(payload["listing_url"], "https://www.redfin.com/NY/Rochester/10-Park-Ave/home/1")
        self.assertEqual(payload["days_on_market"], 45)
        self.assertNotIn("view_count", payload)
        self.assertEqual(payload["listing_status"], "For Sale")

    def test_normalize_record_numerics_parses_image_urls_json_string(self):
        from knowledge_base import _normalize_record_numerics

        normalized = _normalize_record_numerics(
            {
                "image_urls": '["https://cdn.example/a.jpg","https://cdn.example/b.jpg"]',
                "price": 200000,
            }
        )
        self.assertEqual(
            normalized["image_urls"],
            ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"],
        )

    def test_normalize_research_payload_rejects_placeholder_year_built(self):
        from engine import _normalize_research_payload

        current = date.today().year
        normalized = _normalize_research_payload(
            "1 Main St",
            {"year_built": current, "price": 100000},
        )
        self.assertIsNone(normalized.get("year_built"))


class TestDataProvenance(unittest.TestCase):
    def test_price_confidence_high_when_listed(self):
        from data_provenance import compute_field_confidence

        scores = compute_field_confidence({"price": 250000, "rent": 1800, "tax_rate": 2.8})
        self.assertGreaterEqual(scores["price"], 0.85)

    def test_rent_confidence_boost_when_stated_in_listing(self):
        from data_provenance import compute_field_confidence

        research = {
            "stated_gross_monthly_rent": 2200,
            "listing_rent_notes": "Tenant paying $2200/mo",
        }
        scores = compute_field_confidence(
            {"price": 200000, "rent": 2200, "tax_rate": 3.0},
            research,
        )
        self.assertGreaterEqual(scores["rent"], 0.80)

    def test_attach_provenance_adds_signal_chain(self):
        from data_provenance import attach_data_provenance

        record = {
            "price": 180000,
            "rent": 1500,
            "tax_rate": 3.4,
            "insurance": 95,
            "sources": ["https://www.zillow.com/homedetails/example"],
        }
        attach_data_provenance(record, pipeline="underwriter_ui")
        self.assertIn("confidence_score", record)
        self.assertIn("data_provenance", record)
        self.assertEqual(record["data_provenance"]["pipeline"], "underwriter_ui")
        self.assertEqual(record["data_provenance"]["signal_chain"][0], "source_urls")

    def test_get_final_analysis_attaches_provenance(self):
        from engine import get_final_analysis

        initial = {
            "price": 200000,
            "rent": 1600,
            "tax_rate": 3.0,
            "insurance": 100,
            "predicted_value": 205000,
            "location_score": 6.5,
            "year_built": 1998,
        }
        with patch("engine.run_geospatial_enrichment", return_value={}):
            result = get_final_analysis(
                initial,
                "123 Main St, Rochester, NY",
                skip_comps=True,
            )
        self.assertIn("confidence_score", result)
        self.assertIn("data_provenance", result)

    def test_confidence_labels(self):
        from data_provenance import confidence_label

        self.assertEqual(confidence_label(0.92), "High")
        self.assertEqual(confidence_label(0.65), "Medium")
        self.assertEqual(confidence_label(0.45), "Low")

    def test_total_confidence_varies_by_property_signals(self):
        from data_provenance import compute_total_confidence

        sparse = compute_total_confidence(
            {"price": 250000, "rent": 1800, "tax_rate": 2.8, "insurance": 0}
        )
        rich = compute_total_confidence(
            {
                "price": 250000,
                "rent": 1800,
                "tax_rate": 2.8,
                "insurance": 95,
                "hoa": 0,
                "predicted_value": 248000,
                "prediction_reasoning": "Comparable sales in the neighborhood support this valuation range.",
                "location_score": 7.5,
                "market_city": "Rochester",
                "year_built": 1998,
                "summary": "Well-maintained duplex with long-term tenant.",
                "sources": [
                    "https://www.zillow.com/homedetails/a",
                    "https://www.realtor.com/realestate/b",
                    "https://www.redfin.com/c",
                ],
            },
            {
                "stated_gross_monthly_rent": 1800,
                "taxes": 7000,
                "year_built": 1998,
                "square_footage": 1800,
                "property_type": "duplex",
            },
        )
        self.assertGreater(rich, sparse)
        self.assertGreaterEqual(sparse, 30)
        self.assertLessEqual(rich, 100)

    def test_attach_provenance_sets_total_confidence_pct(self):
        from data_provenance import attach_data_provenance

        record = {
            "price": 180000,
            "rent": 1500,
            "tax_rate": 3.4,
            "insurance": 95,
            "sources": ["https://www.zillow.com/homedetails/example"],
        }
        attach_data_provenance(record, pipeline="underwriter_ui")
        self.assertIn("total_confidence_pct", record)
        self.assertGreaterEqual(record["total_confidence_pct"], 40)
        self.assertLessEqual(record["total_confidence_pct"], 100)


class TestPortfolioMapGeocoding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        from unittest.mock import MagicMock

        sys.modules.setdefault("folium", MagicMock())
        sys.modules.setdefault("streamlit_folium", MagicMock())

    def test_new_market_zip_centroids(self):
        from portfolio_map_page import resolve_coordinates_local

        cases = [
            ("10 Main St, Orlando, FL 32801", "32801", "Orlando"),
            ("20 Oak Ave, Tampa, FL 33602", "33602", "Tampa"),
            ("30 Bay Rd, Miami, FL 33139", "33139", "Miami"),
            ("40 State St, Philadelphia, PA 19103", "19103", "Philadelphia"),
            ("50 Grant St, Pittsburgh, PA 15213", "15213", "Pittsburgh"),
            ("60 Maple Dr, Buffalo, NY 14221", "14221", "Buffalo"),
            ("70 Central Ave, Albany, NY 12203", "12203", "Albany"),
        ]
        for address, zip_code, market in cases:
            lat, lon = resolve_coordinates_local(address, zip_code, market)
            self.assertIsNotNone(lat, msg=address)
            self.assertIsNotNone(lon, msg=address)

    def test_new_market_suburb_keyword_fallback(self):
        from portfolio_map_page import resolve_coordinates_local

        lat, lon = resolve_coordinates_local(
            "100 Suburban Ln, Kissimmee, FL 34741",
            "34741",
            "Orlando",
        )
        self.assertIsNotNone(lat)
        self.assertIsNotNone(lon)
        self.assertLess(lat, 29.0)
        self.assertGreater(lat, 27.5)

    def test_dataframe_selected_rows_reads_dict_state(self):
        from portfolio_map_page import _dataframe_selected_rows

        rows = _dataframe_selected_rows({"selection": {"rows": [2], "columns": []}})
        self.assertEqual(rows, [2])


class TestPortfolioMapFilters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        from unittest.mock import MagicMock

        sys.modules.setdefault("folium", MagicMock())
        sys.modules.setdefault("streamlit_folium", MagicMock())

    def _sample_df(self):
        import pandas as pd

        return pd.DataFrame(
            [
                {
                    "address": "1 Main St, Rochester, NY 14607",
                    "state_code": "NY",
                    "market_city": "Rochester",
                    "price": 200_000,
                    "year_built": 1985,
                    "monthly_cash_flow": 400,
                    "one_year_roi": 12.5,
                    "location_score": 7.0,
                    "quantum_success": 82.0,
                },
                {
                    "address": "2 Oak Ave, Charlotte, NC 28269",
                    "state_code": "NC",
                    "market_city": "Charlotte",
                    "price": 350_000,
                    "year_built": 2010,
                    "monthly_cash_flow": -100,
                    "one_year_roi": 5.0,
                    "location_score": 5.5,
                    "quantum_success": 60.0,
                },
            ]
        )

    def test_filter_by_state_and_city(self):
        from portfolio_map_page import filter_portfolio_dataframe

        df = self._sample_df()
        filtered = filter_portfolio_dataframe(df, states=["NY"], cities=["Rochester"])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["state_code"], "NY")

    def test_filter_by_price_and_roi_ranges(self):
        from portfolio_map_page import filter_portfolio_dataframe

        df = self._sample_df()
        filtered = filter_portfolio_dataframe(
            df,
            price_range=(300_000, 400_000),
            price_bounds=(200_000, 350_000),
            roi_range=(4.0, 6.0),
            roi_bounds=(5.0, 12.5),
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["market_city"], "Charlotte")

    def test_build_portfolio_dataframe_includes_filter_fields(self):
        from portfolio_map_page import build_portfolio_dataframe

        props = [
            {
                "address": "10 State St, Rochester, NY 14607",
                "price": 180000,
                "year_built": 1992,
                "location_score": 6.5,
                "quantum_risk_score": 75.0,
                "market_city": "Rochester",
                "state_code": "NY",
            }
        ]
        df = build_portfolio_dataframe(props)
        self.assertEqual(df.iloc[0]["state_code"], "NY")
        self.assertEqual(int(df.iloc[0]["year_built"]), 1992)
        self.assertEqual(df.iloc[0]["location_score"], 6.5)

    def test_build_portfolio_dataframe_includes_added_at(self):
        from datetime import datetime, timezone

        from portfolio_map_page import build_portfolio_dataframe

        props = [
            {
                "address": "10 State St, Rochester, NY 14607",
                "price": 180000,
                "timestamp": "2025-06-11T22:53:00+00:00",
            }
        ]
        df = build_portfolio_dataframe(props)
        added_at = df.iloc[0]["added_at"]
        self.assertEqual(added_at, datetime(2025, 6, 11, 22, 53, tzinfo=timezone.utc))


class TestViewerTimezone(unittest.TestCase):
    def test_format_added_at_same_day(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        from viewer_timezone import format_added_at

        utc_dt = datetime(2025, 6, 11, 22, 53, tzinfo=timezone.utc)
        now = datetime(2025, 6, 11, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        formatted = format_added_at(
            utc_dt,
            ZoneInfo("America/New_York"),
            now=now,
        )
        self.assertEqual(formatted, "6:53 PM")

    def test_format_added_at_with_date(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        from viewer_timezone import format_added_at

        utc_dt = datetime(2025, 5, 10, 14, 30, tzinfo=timezone.utc)
        now = datetime(2025, 6, 11, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        formatted = format_added_at(
            utc_dt,
            ZoneInfo("America/New_York"),
            now=now,
        )
        self.assertEqual(formatted, "May 10, 10:30 AM")

    def test_sort_portfolio_newest_added(self):
        from datetime import datetime, timezone

        import pandas as pd

        from portfolio_map_page import sort_portfolio

        df = pd.DataFrame(
            {
                "address": ["older", "newer"],
                "added_at": [
                    datetime(2025, 1, 1, tzinfo=timezone.utc),
                    datetime(2025, 6, 1, tzinfo=timezone.utc),
                ],
                "price": [100000, 200000],
            }
        )
        sorted_df = sort_portfolio(df, "added_at")
        self.assertEqual(sorted_df.iloc[0]["address"], "newer")

    def test_parse_property_timestamp_postgres_format(self):
        from datetime import datetime, timezone

        from viewer_timezone import parse_property_timestamp

        parsed = parse_property_timestamp("2025-06-11 22:53:00+00:00")
        self.assertEqual(parsed, datetime(2025, 6, 11, 22, 53, tzinfo=timezone.utc))

    def test_timezone_from_offset_minutes(self):
        from datetime import datetime, timezone

        from viewer_timezone import format_added_at, timezone_from_offset_minutes

        utc_dt = datetime(2025, 6, 11, 22, 53, tzinfo=timezone.utc)
        eastern = timezone_from_offset_minutes(240)
        now = datetime(2025, 6, 11, 12, 0, tzinfo=eastern)
        self.assertEqual(format_added_at(utc_dt, eastern, now=now), "6:53 PM")

    def test_resolve_viewer_timezone_prefers_context(self):
        from zoneinfo import ZoneInfo

        from viewer_timezone import resolve_viewer_timezone

        tz = resolve_viewer_timezone(context_tz="America/Chicago")
        self.assertEqual(tz, ZoneInfo("America/Chicago"))

    def test_resolve_viewer_timezone_cookie_fallback(self):
        from zoneinfo import ZoneInfo

        from viewer_timezone import resolve_viewer_timezone

        tz = resolve_viewer_timezone(cookie_tz="America/Denver")
        self.assertEqual(tz, ZoneInfo("America/Denver"))


class TestDeferredAnalysis(unittest.TestCase):
    def test_build_deferred_task_queue_orders_work(self):
        from services.deferred_analysis import build_deferred_task_queue

        queue = build_deferred_task_queue(
            {"price": 200000, "predicted_value": 205000, "location_score": 6.0},
            guest_mode=False,
        )
        self.assertEqual(queue, ["comps", "quantum", "forecast_chart"])

    def test_build_deferred_task_queue_skips_existing(self):
        from services.deferred_analysis import build_deferred_task_queue

        queue = build_deferred_task_queue(
            {
                "comps_analysis": {"comparable_properties": [{"sale_price": 1}]},
                "quantum_risk": {"overall_success_pct": 70.0},
                "_forecast_display_cache": {"annual_rate": 4.0},
            },
            guest_mode=False,
        )
        self.assertEqual(queue, [])

    def test_build_deferred_task_queue_guest_skips_comps(self):
        from services.deferred_analysis import build_deferred_task_queue

        queue = build_deferred_task_queue({"price": 200000}, guest_mode=True)
        self.assertNotIn("comps", queue)
        self.assertIn("quantum", queue)

    def test_get_active_analysis_address_prefers_session_key(self):
        import streamlit as st

        from services.deferred_analysis import (
            INDIVIDUAL_SEARCH_ADDRESS_KEY,
            get_active_analysis_address,
        )

        st.session_state[INDIVIDUAL_SEARCH_ADDRESS_KEY] = "10 Park Ave"
        st.session_state["property_data"] = {"address": "Other St"}
        self.assertEqual(get_active_analysis_address(), "10 Park Ave")

    def test_ensure_deferred_task_queue_does_not_rebuild_existing_queue(self):
        import streamlit as st

        from services.deferred_analysis import DEFERRED_TASKS_KEY, ensure_deferred_task_queue

        st.session_state[DEFERRED_TASKS_KEY] = ["quantum"]
        ensure_deferred_task_queue({"price": 200000}, guest_mode=False)
        self.assertEqual(st.session_state[DEFERRED_TASKS_KEY], ["quantum"])


class TestPersistCompsToCanonical(unittest.TestCase):
    def test_persist_skips_without_comps(self):
        from knowledge_base import persist_comps_to_canonical

        self.assertFalse(persist_comps_to_canonical({"address": "1 Main St"}))

    def test_persist_skips_without_catalog_property(self):
        from unittest.mock import patch

        from knowledge_base import persist_comps_to_canonical

        with patch("knowledge_base.get_property_id_by_address", return_value=None):
            saved = persist_comps_to_canonical(
                {
                    "address": "1 Main St",
                    "comps_analysis": {"comparable_properties": [{"sale_price": 1}]},
                }
            )
        self.assertFalse(saved)

    def test_persist_upserts_comps_for_catalog_property(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import persist_comps_to_canonical

        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=True)
        property_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        comps = {
            "comparable_properties": [{"address": "2 Oak", "sale_price": 200000}],
            "comp_count": 1,
        }

        with (
            patch("authenticate.get_authenticated_client", return_value=mock_client),
            patch("knowledge_base.get_property_id_by_address", return_value=property_id),
            patch("knowledge_base.invalidate_kb_cache"),
        ):
            saved = persist_comps_to_canonical(
                {
                    "address": "1 Main St, Rochester, NY 14607",
                    "price": 180000,
                    "predicted_value": 190000,
                    "comps_analysis": comps,
                }
            )

        self.assertTrue(saved)
        mock_client.rpc.assert_called_once()
        rpc_name, rpc_params = mock_client.rpc.call_args.args
        self.assertEqual(rpc_name, "save_property_comps")
        self.assertEqual(rpc_params["p_property_id"], property_id)
        self.assertEqual(rpc_params["p_comps_analysis"], comps)
        self.assertEqual(rpc_params["p_predicted_value"], 190000)

    def test_save_harvest_property_persists_comps_with_service_client(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import save_harvest_property

        property_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        comps = {
            "comparable_properties": [{"address": "2 Oak", "sale_price": 200000}],
            "comp_count": 1,
        }
        listing = {
            "address": "1 Main St, Rochester, NY 14607",
            "price": 180000,
            "predicted_value": 190000,
            "rent": 1500,
            "tax_rate": 3.0,
            "insurance": 120,
            "hoa": 0,
            "maint_percent": 4,
            "location_score": 6,
            "forecast_rate": 4.0,
            "comps_analysis": comps,
        }

        mock_service = MagicMock()
        mock_service.rpc.return_value.execute.return_value = MagicMock(data=True)
        mock_client = MagicMock()
        mock_table = mock_client.table.return_value
        mock_table.upsert.return_value.select.return_value.execute.return_value = (
            MagicMock(data=[{"id": property_id}])
        )

        with (
            patch("knowledge_base.get_client", return_value=mock_client),
            patch("knowledge_base.get_admin_uid", return_value="7f35bc1e-9de5-484d-8f73-27fd3da733eb"),
            patch("authenticate.get_service_client", return_value=mock_service),
            patch("knowledge_base.invalidate_kb_cache"),
        ):
            result = save_harvest_property(listing)

        self.assertIsNotNone(result)
        mock_service.rpc.assert_called_once()
        rpc_name, rpc_params = mock_service.rpc.call_args.args
        self.assertEqual(rpc_name, "save_property_comps")
        self.assertEqual(rpc_params["p_property_id"], property_id)
        self.assertEqual(rpc_params["p_comps_analysis"], comps)


class TestPersistRentCompsToCanonical(unittest.TestCase):
    def test_persist_skips_without_rent_comps(self):
        from knowledge_base import persist_rent_comps_to_canonical

        self.assertFalse(persist_rent_comps_to_canonical({"address": "1 Main St"}))

    def test_persist_upserts_rent_comps_for_catalog_property(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import persist_rent_comps_to_canonical

        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=True)
        property_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        rent_comps = {
            "comparable_rentals": [{"address": "2 Oak", "monthly_rent": 1800}],
            "comp_count": 1,
        }

        with (
            patch("authenticate.get_authenticated_client", return_value=mock_client),
            patch("knowledge_base.get_property_id_by_address", return_value=property_id),
            patch("knowledge_base.invalidate_kb_cache"),
        ):
            saved = persist_rent_comps_to_canonical(
                {
                    "address": "1 Main St, Rochester, NY 14607",
                    "rent": 1650,
                    "rent_comps_analysis": rent_comps,
                }
            )

        self.assertTrue(saved)
        mock_client.rpc.assert_called_once()
        rpc_name, rpc_params = mock_client.rpc.call_args.args
        self.assertEqual(rpc_name, "save_property_rent_comps")
        self.assertEqual(rpc_params["p_property_id"], property_id)
        self.assertEqual(rpc_params["p_rent_comps_analysis"], rent_comps)
        self.assertEqual(rpc_params["p_rent"], 1650)


class TestCompsAnalysis(unittest.TestCase):
    def test_evaluate_flags_undervaluation(self):
        from comps_analysis import evaluate_comps_against_subject, normalize_comps_payload

        payload = normalize_comps_payload(
            {
                "comparable_properties": [
                    {
                        "address": "1 Maple St",
                        "sale_price": 220000,
                        "square_footage": 1500,
                        "sale_date": "2024-06",
                    },
                    {
                        "address": "2 Maple St",
                        "sale_price": 210000,
                        "square_footage": 1480,
                        "sale_date": "2024-03",
                    },
                    {
                        "address": "3 Maple St",
                        "sale_price": 215000,
                        "square_footage": 1520,
                        "sale_date": "2023-11",
                    },
                ],
                "market_summary": "Ranch comps cluster near $140/sqft.",
            }
        )
        subject = {
            "price": 175000,
            "predicted_value": 180000,
            "square_footage": 1500,
        }
        summary = evaluate_comps_against_subject(payload, subject)
        self.assertTrue(summary["is_undervalued"])
        self.assertGreater(summary["comp_suggested_value"], 200000)
        self.assertLess(summary["predicted_vs_comps_pct"], -8.0)

    def test_apply_comps_valuation_adjustment_raises_predicted_value(self):
        from comps_analysis import apply_comps_valuation_adjustment

        property_data = {
            "price": 175000,
            "predicted_value": 180000,
            "prediction_reasoning": "Initial AI estimate.",
        }
        comps_analysis = {
            "is_undervalued": True,
            "comp_suggested_value": 215000,
            "median_sale_price": 215000,
            "comp_count": 3,
        }
        changed = apply_comps_valuation_adjustment(property_data, comps_analysis)
        self.assertTrue(changed)
        self.assertEqual(property_data["predicted_value"], 215000)
        self.assertIn("Market value set", property_data["prediction_reasoning"])

    def test_evaluate_offer_success_favors_at_or_above_market(self):
        from comps_analysis import evaluate_offer_success

        at_market = evaluate_offer_success(200_000, 200_000, 175_000)
        below_market = evaluate_offer_success(180_000, 200_000, 175_000)
        above_market = evaluate_offer_success(220_000, 200_000, 175_000)

        self.assertGreater(above_market["success_pct"], at_market["success_pct"])
        self.assertGreater(at_market["success_pct"], below_market["success_pct"])

    def test_resolve_market_value_prefers_comps(self):
        from comps_analysis import resolve_market_value

        data = {
            "price": 175000,
            "predicted_value": 180000,
            "comps_analysis": {
                "comp_count": 3,
                "comp_suggested_value": 215000,
            },
        }
        self.assertEqual(resolve_market_value(data), 215000)

    def test_comps_analysis_needs_recompute_detects_stale_metrics(self):
        from comps_analysis import comps_analysis_needs_recompute

        stale = {
            "comparable_properties": [
                {"sale_price": 220000},
                {"sale_price": 210000},
            ],
            "median_sale_price": 0.0,
            "summary": "Stale summary.",
            "comp_count": 2,
        }
        fresh = {
            "comparable_properties": stale["comparable_properties"],
            "median_sale_price": 215000.0,
            "comp_suggested_value": 216000.0,
            "summary": "Median comp sale: $215,000.",
            "comp_count": 2,
        }
        self.assertTrue(comps_analysis_needs_recompute(stale))
        self.assertFalse(comps_analysis_needs_recompute(fresh))

    def test_ensure_comps_analysis_recomputes_stale_summary(self):
        from components.property_comps import ensure_comps_analysis
        from engine import safe_float

        property_info = {
            "price": 175000,
            "predicted_value": 180000,
            "square_footage": 1500,
            "comps_analysis": {
                "comparable_properties": [
                    {
                        "address": "1 Maple St",
                        "sale_price": 220000,
                        "square_footage": 1500,
                    },
                    {
                        "address": "2 Maple St",
                        "sale_price": 210000,
                        "square_footage": 1480,
                    },
                ],
                "median_sale_price": 0.0,
                "summary": "Stale summary from incomplete persistence.",
                "comp_count": 2,
            },
        }
        updated = ensure_comps_analysis(property_info)
        comps = updated["comps_analysis"]
        self.assertGreater(safe_float(comps.get("median_sale_price")), 200000)
        self.assertGreater(safe_float(comps.get("comp_suggested_value")), 200000)
        self.assertNotEqual(comps.get("summary"), "Stale summary from incomplete persistence.")
        self.assertEqual(updated.get("predicted_value"), int(comps["comp_suggested_value"]))

    def test_rent_comps_flags_underrented(self):
        from rent_comps_analysis import evaluate_rent_comps_against_subject, normalize_rent_comps_payload

        payload = normalize_rent_comps_payload(
            {
                "comparable_rentals": [
                    {"address": "1 A St", "monthly_rent": 1800, "square_footage": 1200},
                    {"address": "2 B St", "monthly_rent": 1750, "square_footage": 1180},
                ],
                "market_summary": "Rentals cluster near $1.45/sqft.",
            }
        )
        subject = {"rent": 1200, "square_footage": 1200}
        summary = evaluate_rent_comps_against_subject(payload, subject)
        self.assertTrue(summary["is_underrented"])
        self.assertGreater(summary["comp_suggested_rent"], 1200)

    def test_fetch_comparable_properties_attaches_summary(self):
        from engine import fetch_comparable_properties

        mock_json = json.dumps(
            {
                "comparable_properties": [
                    {
                        "address": "9 Oak Ave",
                        "sale_price": 205000,
                        "square_footage": 1400,
                        "sale_date": "2024-01",
                    },
                    {
                        "address": "11 Oak Ave",
                        "sale_price": 198000,
                        "square_footage": 1380,
                        "sale_date": "2023-09",
                    },
                ],
                "market_summary": "Stable pricing in the submarket.",
            }
        )
        subject = {
            "price": 170000,
            "predicted_value": 175000,
            "square_footage": 1400,
        }
        with patch("engine.comps_agent", return_value=mock_json):
            result = fetch_comparable_properties("123 Main St, Rochester, NY", subject)
        self.assertIn("comps_analysis", result)
        self.assertEqual(result["comps_analysis"]["comp_count"], 2)
        self.assertTrue(result.get("comps_adjusted_predicted_value"))

    def test_fetch_comparable_properties_skips_when_comps_exist(self):
        from engine import fetch_comparable_properties

        subject = {
            "price": 170000,
            "comps_analysis": {
                "comparable_properties": [
                    {"address": "9 Oak Ave", "sale_price": 205000},
                ],
                "comp_count": 1,
            },
        }
        with patch("engine.comps_agent") as mock_agent:
            result = fetch_comparable_properties("123 Main St, Rochester, NY", subject)
        mock_agent.assert_not_called()
        self.assertEqual(result["comps_analysis"]["comp_count"], 1)


class TestPdfGenerator(unittest.TestCase):
    def test_generate_property_pdf_includes_comps_and_forecast(self):
        from pdf_generator import generate_property_pdf

        property_info = {
            "summary": "Test property summary.",
            "comps_analysis": {
                "comparable_properties": [
                    {
                        "address": "1 Oak Ave",
                        "sale_price": 200000,
                        "square_footage": 1400,
                        "sale_date": "2024-01",
                        "distance_miles": 0.3,
                    }
                ],
                "comp_suggested_value": 200000,
                "median_sale_price": 200000,
                "list_price": 175000,
                "summary": "Aligned with area comps.",
            },
            "rent_comps_analysis": {
                "comparable_rentals": [
                    {
                        "address": "2 Oak Ave",
                        "monthly_rent": 1800,
                        "square_footage": 1200,
                        "lease_date": "2024-02",
                        "distance_miles": 0.4,
                    }
                ],
                "comp_suggested_rent": 1800,
                "median_monthly_rent": 1800,
                "subject_rent": 1600,
                "rent_vs_comps_pct": -11.1,
                "summary": "Rent slightly below comps.",
            },
        }
        forecast = {
            "future_value_p50": 250000,
            "future_value_p10": 220000,
            "future_value_p90": 280000,
            "annual_rate": 4.5,
            "value_schedule_p50": [200000 + i * 5000 for i in range(11)],
            "value_schedule_p10": [190000 + i * 4000 for i in range(11)],
            "value_schedule_p90": [210000 + i * 6000 for i in range(11)],
        }
        table_data = {
            "Description": ["Gross Monthly Rent", "Cash Flow Monthly"],
            "Amount": ["$1,600.00", "$200.00"],
        }
        params = {
            "Offer Amount": "$175,000",
            "Down Payment": "25.0% ($43,750)",
            "Interest Rate": "6.0%",
            "Loan Term": "30 Years",
        }
        pdf_bytes = generate_property_pdf(
            "123 Main St",
            property_info,
            {"Cap Rate": "7.0%"},
            table_data,
            params,
            location_score=7.5,
            quantum_risk={
                "cashflow_success_pct": 80.0,
                "appreciation_success_pct": 70.0,
                "combined_wealth_success_pct": 75.0,
                "overall_success_pct": 72.0,
            },
            forecast_display=forecast,
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 5000)


class TestShareAccess(unittest.TestCase):
    def test_save_share_comps_snapshot_includes_rent_comps(self):
        from unittest.mock import MagicMock, patch

        from share_access import save_share_comps_snapshot

        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=True)
        rent_comps = {
            "comparable_rentals": [{"address": "5 Elm", "monthly_rent": 2000}],
            "comp_count": 1,
        }

        with patch("authenticate.get_authenticated_client", return_value=mock_client):
            saved = save_share_comps_snapshot(
                "tok123",
                "11111111-1111-1111-1111-111111111111",
                {"rent_comps_analysis": rent_comps},
            )

        self.assertTrue(saved)
        rpc_name, rpc_params = mock_client.rpc.call_args.args
        self.assertEqual(rpc_name, "save_share_comps_snapshot")
        self.assertEqual(rpc_params["p_rent_comps_analysis"], rent_comps)
        self.assertNotIn("p_comps_analysis", rpc_params)

    def test_ensure_property_saved_for_share_uses_existing_catalog_id(self):
        from share_access import ensure_property_saved_for_share

        property_data = {"address": "123 Main St, Rochester, NY", "price": 200000}
        with (
            patch("authenticate.get_logged_in_user", return_value={"id": "u1", "email": "a@b.c"}),
            patch("share_access._property_exists", return_value=True),
            patch(
                "knowledge_base.get_property_id_by_address",
                return_value="11111111-1111-1111-1111-111111111111",
            ),
            patch("knowledge_base.save_canonical_property") as mock_save,
        ):
            resolved = ensure_property_saved_for_share(property_data, "123 Main St, Rochester, NY")
        self.assertEqual(resolved, "11111111-1111-1111-1111-111111111111")
        mock_save.assert_not_called()


class TestSecurityHardening(unittest.TestCase):
    def test_escape_html_neutralizes_script_tags(self):
        from security_utils import escape_html

        payload = '<img src=x onerror="alert(1)">'
        escaped = escape_html(payload)
        self.assertNotIn("<img", escaped)
        self.assertIn("&lt;img", escaped)

    def test_redact_log_context_masks_tokens(self):
        from security_utils import redact_log_context

        redacted = redact_log_context(
            {"share_token": "secret-token", "property_id": "abc"}
        )
        self.assertEqual(redacted["share_token"], "[redacted]")
        self.assertEqual(redacted["property_id"], "abc")

    def test_delete_canonical_denied_for_non_admin_in_streamlit(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import delete_canonical_property_by_id

        property_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        with (
            patch("knowledge_base.in_streamlit_app", return_value=True),
            patch("knowledge_base.get_logged_in_user", return_value={"id": "user-a"}),
            patch("knowledge_base.get_admin_uid", return_value="admin-b"),
            patch("knowledge_base.get_client") as mock_client,
            patch("knowledge_base.log", MagicMock()),
        ):
            self.assertFalse(delete_canonical_property_by_id(property_id))
            mock_client.assert_not_called()

    def test_delete_canonical_allowed_for_admin_in_streamlit(self):
        from unittest.mock import MagicMock, patch

        from knowledge_base import delete_canonical_property_by_id

        admin_id = "7f35bc1e-9de5-484d-8f73-27fd3da733eb"
        property_id = "11111111-1111-1111-1111-111111111111"
        mock_supabase = MagicMock()
        with (
            patch("knowledge_base.in_streamlit_app", return_value=True),
            patch(
                "knowledge_base.get_logged_in_user",
                return_value={"id": admin_id, "email": "admin@example.com"},
            ),
            patch("knowledge_base.get_admin_uid", return_value=admin_id),
            patch("knowledge_base.get_client", return_value=mock_supabase),
            patch("knowledge_base.invalidate_kb_cache"),
            patch("knowledge_base.log", MagicMock()),
        ):
            self.assertTrue(delete_canonical_property_by_id(property_id))

    def test_read_pkce_verifier_ignores_query_param(self):
        from unittest.mock import patch

        import authenticate

        with (
            patch.object(authenticate.st, "session_state", {}),
            patch.object(authenticate.st, "query_params", {"pkce_verifier": "leaked"}),
            patch("authenticate._load_pending_pkce", return_value=None),
        ):
            self.assertIsNone(authenticate._read_pkce_verifier())

    def test_oauth_redirect_rejects_untrusted_forwarded_host(self):
        import authenticate

        self.assertFalse(authenticate._is_trusted_app_host("evil.example.com"))
        self.assertTrue(authenticate._is_trusted_app_host("localhost"))
        self.assertTrue(authenticate._is_trusted_app_host("my-app.streamlit.app"))


class TestOutreachAppUrls(unittest.TestCase):
    def test_replace_legacy_app_urls(self):
        from targeted_outreach_pipeline import (
            DEFAULT_APP_URL,
            replace_legacy_app_urls,
        )

        body = (
            "See the analysis at https://realestateanalyzer.streamlit.app?share=abc123\n"
            "https://realestateanalyzer.streamlit.app"
        )
        updated, changed = replace_legacy_app_urls(body, app_url=DEFAULT_APP_URL)
        self.assertTrue(changed)
        self.assertNotIn("realestateanalyzer", updated)
        self.assertIn(DEFAULT_APP_URL, updated)
        self.assertIn(f"{DEFAULT_APP_URL}?share=abc123", updated)

    def test_replace_legacy_app_urls_noop_when_current(self):
        from targeted_outreach_pipeline import DEFAULT_APP_URL, replace_legacy_app_urls

        body = f"Open {DEFAULT_APP_URL}?share=token"
        updated, changed = replace_legacy_app_urls(body, app_url=DEFAULT_APP_URL)
        self.assertFalse(changed)
        self.assertEqual(updated, body)

    def test_ensure_signature_uses_current_app_url(self):
        from targeted_outreach_pipeline import DEFAULT_APP_URL, _ensure_signature

        body = "Hi — see https://realestateanalyzer.streamlit.app"
        signed = _ensure_signature(
            body,
            "Best regards",
            app_url=DEFAULT_APP_URL,
        )
        self.assertNotIn("realestateanalyzer", signed)
        self.assertIn(DEFAULT_APP_URL, signed)

    def test_replace_urls_in_multipart_draft(self):
        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from targeted_outreach_pipeline import (
            DEFAULT_APP_URL,
            _replace_urls_in_message,
        )

        message = MIMEMultipart()
        message["Subject"] = "Listing analysis"
        message.attach(
            MIMEText(
                "Full report: https://realestateanalyzer.streamlit.app?share=xyz",
                "plain",
                "utf-8",
            )
        )
        message.attach(MIMEApplication(b"%PDF", _subtype="pdf"))
        changed = _replace_urls_in_message(message, app_url=DEFAULT_APP_URL)
        self.assertTrue(changed)
        plain_part = message.get_payload()[0]
        payload = plain_part.get_payload(decode=True).decode("utf-8")
        self.assertIn(DEFAULT_APP_URL, payload)
        self.assertNotIn("realestateanalyzer", payload)


class TestDiscoveryScraper(unittest.TestCase):
    _GIS_FIXTURE = {
        "homes": [
            {
                "propertyId": 12345678,
                "url": "/NY/Rochester/10-Park-Ave-14607/home/12345678",
                "streetLine": {"value": "10 Park Ave"},
                "city": "Rochester",
                "state": "NY",
                "zip": "14607",
                "price": {"value": 210000},
                "photos": {"value": "https://ssl.cdn-redfin.com/photo/1.jpg"},
            }
        ]
    }

    _DETAIL_FIXTURE = {
        "payload": {
            "initialInfo": {
                "addressSectionInfo": {
                    "streetAddress": "10 Park Ave, Rochester, NY 14607",
                    "url": "/NY/Rochester/10-Park-Ave-14607/home/12345678",
                }
            },
            "aboveTheFold": {
                "addressSectionInfo": {
                    "price": {"value": 210000},
                    "status": {"value": "Active"},
                    "timeOnRedfin": {"value": 12},
                    "listingViewCount": {"value": 87},
                    "propertyType": {"value": "Single Family"},
                    "sqFt": {"value": 1450},
                    "yearBuilt": {"value": 1968},
                    "hoaDues": {"value": 0},
                    "latLong": {"value": {"latitude": 43.15, "longitude": -77.61}},
                    "mediaBrowserInfo": {
                        "photos": [
                            {"photoUrl": "https://ssl.cdn-redfin.com/photo/1.jpg"},
                            {"photoUrl": "https://ssl.cdn-redfin.com/photo/2.jpg"},
                        ]
                    },
                }
            },
            "belowTheFold": {
                "publicRemarks": "Turnkey rental rents for $1,850/mo with long-term tenant.",
                "taxAnnualAmount": {"value": 4200},
            },
        }
    }

    def test_parse_redfin_gis_seed(self):
        from discovery.parsers.redfin_gis import parse_redfin_gis_payload

        seeds = parse_redfin_gis_payload(
            self._GIS_FIXTURE,
            market_city="Rochester",
            max_price=250_000,
        )
        self.assertEqual(len(seeds), 1)
        seed = seeds[0]
        self.assertEqual(seed.city, "Rochester")
        self.assertEqual(seed.external_id, "12345678")
        self.assertIn("redfin.com", seed.listing_url)
        self.assertEqual(seed.list_price, 210000.0)

    def test_parse_redfin_detail_payload(self):
        from discovery.models import ListingSeed
        from discovery.parsers.redfin_detail import parse_redfin_detail_payload

        seed = ListingSeed(
            address="10 Park Ave, Rochester, NY 14607",
            city="Rochester",
            list_price=210000,
            listing_url="https://www.redfin.com/NY/Rochester/10-Park-Ave-14607/home/12345678",
            source="redfin",
            external_id="12345678",
        )
        scraped = parse_redfin_detail_payload(self._DETAIL_FIXTURE, seed=seed)
        self.assertEqual(scraped.listing_status, "For Sale")
        self.assertEqual(scraped.days_on_market, 12)
        self.assertEqual(scraped.view_count, 87)
        self.assertEqual(len(scraped.image_urls), 2)
        self.assertEqual(scraped.stated_gross_monthly_rent, 1850.0)
        self.assertIn("Turnkey rental", scraped.listing_description)

    def test_scraped_to_research_dict_shape(self):
        from discovery.models import ScrapedListing
        from discovery.normalize import scraped_to_research_dict

        scraped = ScrapedListing(
            address="10 Park Ave, Rochester, NY 14607",
            city="Rochester",
            list_price=210000,
            listing_url="https://www.redfin.com/NY/Rochester/10-Park-Ave-14607/home/12345678",
            source="redfin",
            external_id="12345678",
            listing_status="For Sale",
            days_on_market=12,
            view_count=87,
            listing_description="Charming bungalow near parks.",
            primary_image_url="https://ssl.cdn-redfin.com/photo/1.jpg",
            image_urls=("https://ssl.cdn-redfin.com/photo/1.jpg",),
            taxes_annual=4200.0,
            hoa_monthly=0.0,
            year_built=1968,
            square_footage=1450,
            property_type="Single Family",
            latitude=43.15,
            longitude=-77.61,
            stated_gross_monthly_rent=1850.0,
            listing_rent_notes="Monthly rent mentioned in listing: $1,850/mo",
            property_condition="Good",
            scraped_at="2026-06-13T12:00:00+00:00",
        )
        research = scraped_to_research_dict(scraped, market_city="Rochester")
        self.assertEqual(research["price"], 210000.0)
        self.assertEqual(research["taxes"], 4200.0)
        self.assertEqual(research["discovery_model"], "scraper")
        self.assertEqual(research["vacancy_rate"], 6.0)
        self.assertEqual(research["management_fee"], 10.0)
        self.assertEqual(research["primary_image_url"], scraped.primary_image_url)
        self.assertEqual(research["listing_description"], scraped.listing_description)

    def test_sqlite_repository_round_trip(self):
        from discovery.models import ListingSeed, ScrapedListing
        from discovery.repository import SqliteDiscoveryRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = SqliteDiscoveryRepository(Path(tmp) / "capigen.db")
            seed = ListingSeed(
                address="10 Park Ave, Rochester, NY 14607",
                city="Rochester",
                list_price=210000,
                listing_url="https://www.redfin.com/NY/Rochester/10-Park-Ave-14607/home/12345678",
                source="redfin",
                external_id="12345678",
            )
            row_id = repo.upsert_seed(seed)
            scraped = ScrapedListing(
                address=seed.address,
                city=seed.city,
                list_price=seed.list_price,
                listing_url=seed.listing_url,
                source=seed.source,
                external_id=seed.external_id,
                listing_status="For Sale",
                days_on_market=5,
                view_count=None,
                listing_description="Updated kitchen.",
                primary_image_url="https://ssl.cdn-redfin.com/photo/1.jpg",
                image_urls=("https://ssl.cdn-redfin.com/photo/1.jpg",),
                taxes_annual=4000.0,
                hoa_monthly=0.0,
                year_built=1970,
                square_footage=1400,
                property_type="Single Family",
                latitude=43.15,
                longitude=-77.61,
                stated_gross_monthly_rent=0.0,
                listing_rent_notes="",
                property_condition="Good",
                scraped_at="2026-06-13T12:00:00+00:00",
            )
            repo.mark_enriched(row_id, scraped)
            loaded = repo.get_enriched_by_external_id("redfin", "12345678")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.listing_description, "Updated kitchen.")
            self.assertIsNone(loaded.view_count)

    def test_orchestrator_run_with_mocked_http(self):
        import asyncio

        from discovery.models import ListingSeed
        from discovery.orchestrator import DiscoveryOrchestrator
        from discovery.repository import SqliteDiscoveryRepository

        seed = ListingSeed(
            address="10 Park Ave, Rochester, NY 14607",
            city="Rochester",
            list_price=210000,
            listing_url="https://www.redfin.com/NY/Rochester/10-Park-Ave-14607/home/12345678",
            source="redfin",
            external_id="12345678",
            thumbnail_url="https://ssl.cdn-redfin.com/photo/1.jpg",
        )

        class FakeSource:
            source_name = "redfin"

            async def search_market(self, market_city, *, max_price, limit):
                if market_city == "Rochester":
                    return [seed]
                return []

            async def fetch_detail(self, listing_seed):
                from discovery.parsers.redfin_detail import parse_redfin_detail_payload

                return parse_redfin_detail_payload(
                    TestDiscoveryScraper._DETAIL_FIXTURE,
                    seed=listing_seed,
                )

        with tempfile.TemporaryDirectory() as tmp:
            repo = SqliteDiscoveryRepository(Path(tmp) / "capigen.db")

            async def _run() -> list[dict]:
                orchestrator = DiscoveryOrchestrator(
                    repository=repo,
                    http_client=object(),
                    sources=[FakeSource()],
                )
                try:
                    return await orchestrator.run(
                        exclude_keys=set(),
                        max_price=250_000,
                        per_market_limit=5,
                        enrich=True,
                    )
                finally:
                    await orchestrator.close()

            listings = asyncio.run(_run())
            rochester = [item for item in listings if item.get("city") == "Rochester"]
            self.assertEqual(len(rochester), 1)
            self.assertEqual(rochester[0]["discovery_model"], "scraper")
            self.assertTrue(rochester[0].get("primary_image_url"))
            self.assertTrue(rochester[0].get("listing_description"))

    def test_synthesis_prompt_separates_listing_description(self):
        from engine import _synthesis_prompt

        research = {
            "price": 210000,
            "listing_description": "Gorgeous turnkey rental with granite counters.",
            "stated_gross_monthly_rent": 1850,
        }
        with patch("engine.get_kb_context", return_value=""):
            prompt = _synthesis_prompt(research, "Rochester")
        self.assertIn("LISTING DESCRIPTION", prompt)
        self.assertIn("Gorgeous turnkey rental", prompt)
        self.assertNotIn('"listing_description"', prompt)

    def test_synthesis_prompt_scraper_block_with_metadata_and_rules(self):
        from engine import _synthesis_prompt

        research = {
            "price": 210000,
            "discovery_model": "scraper",
            "listing_description": "Turnkey duplex with long-term tenants.",
            "days_on_market": 45,
            "view_count": None,
            "listing_status": "For Sale",
            "vacancy_rate": 6.0,
            "management_fee": 10.0,
        }
        with patch("engine.get_kb_context", return_value=""):
            prompt = _synthesis_prompt(research, "Rochester")
        self.assertIn("LISTING DESCRIPTION (scraper", prompt)
        self.assertIn("Turnkey duplex with long-term tenants.", prompt)
        self.assertIn("LISTING METADATA:", prompt)
        self.assertIn("days_on_market: 45", prompt)
        self.assertIn("view_count: None", prompt)
        self.assertIn("listing_status: For Sale", prompt)
        self.assertIn("SUMMARY RULES:", prompt)
        self.assertIn("Never paste sentences from the listing description.", prompt)
        self.assertNotIn('"listing_description"', prompt)


if __name__ == "__main__":
    unittest.main()
