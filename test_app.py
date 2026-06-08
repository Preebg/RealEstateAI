import json
import logging
import math
import unittest
from datetime import date
from unittest.mock import patch

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
    )
    from engine import (
        DISCOVERY_FALLBACK_MODEL,
        DISCOVERY_FALLBACK_MODELS,
        DISCOVERY_MODEL,
        DISCOVERY_MODEL_CHAIN,
        RESEARCH_FALLBACK_MODEL,
        RESEARCH_MODEL,
        discover_hot_market_listings,
        is_daily_quota_exhausted,
        research_property,
        is_disallowed_property_type,
        should_skip_synthesis,
        synthesis_skip_reason,
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
        self.assertEqual(DISCOVERY_MODEL_CHAIN, ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemma-4-21b-it"))
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
            market = kwargs.get("split_market")
            if market == "Rochester":
                return [_VERIFIED_DISCOVERY_ROW], "rochester"
            if market == "Syracuse":
                return [syracuse_row], "syracuse"
            return [], ""

        with patch("engine._run_discovery_attempt", side_effect=fake_attempt):
            listings = discover_hot_market_listings(
                model=DISCOVERY_FALLBACK_MODEL,
                on_listing_found=lambda item: found.append(item["address"]),
            )

        self.assertGreaterEqual(len(found), 2)
        self.assertIn(rochester_row["address"], found)
        self.assertIn(syracuse_row["address"], found)
        self.assertGreaterEqual(len(listings), 2)


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

    def test_research_fallback_resolves_to_gemma_a4b_slug(self):
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
            research_property("1 Main St, Rochester, NY", model=RESEARCH_FALLBACK_MODEL)
            self.assertEqual(mock_gen.call_args.args[0], "gemma-4-26b-a4b-it")


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


class TestDiscoveryParsing(unittest.TestCase):
    def test_extract_wrapped_listings_object(self):
        from engine import _build_listings_from_raw

        raw = json.dumps({"listings": [{**_VERIFIED_DISCOVERY_ROW, "price": 210000}]})
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")
        self.assertEqual(listings[0]["list_price"], 210000.0)

    def test_discover_uses_split_market_when_combined_empty(self):
        calls = {"count": 0}

        def fake_generate(model, prompt, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
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
        self.assertGreater(calls["count"], 1)

    def test_plan_redistributes_unfilled_rochester_slots(self):
        from engine import HOT_MARKETS, MAX_DISCOVERY_LISTINGS, _plan_market_discovery_pass

        listings: list[dict] = []
        for name, _, target in HOT_MARKETS:
            count = 3 if name == "Rochester" else target
            for idx in range(count):
                listings.append(
                    {
                        "address": f"{idx} Main St, {name} Metro",
                        "city": name,
                        "list_price": 180000.0,
                        "listing_url": f"https://www.zillow.com/homedetails/{name}-{idx}/",
                    }
                )

        self.assertEqual(len(listings), MAX_DISCOVERY_LISTINGS - 2)
        plan = _plan_market_discovery_pass(listings, {"Rochester"})
        planned_total = sum(count for _, count in plan)
        self.assertEqual(planned_total, 2)
        self.assertNotIn("Rochester", [market for market, _ in plan])
        self.assertEqual(plan[0][0], "Syracuse")
        self.assertEqual(plan[0][1], 1)
        self.assertEqual(plan[1][0], "Buffalo")
        self.assertEqual(plan[1][1], 1)

    def test_plan_keeps_trying_rochester_until_exhausted(self):
        from engine import _plan_market_discovery_pass

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
        self.assertEqual(rochester_need, 2)
        self.assertEqual(sum(count for _, count in plan), 25 - len(listings))

    def test_discover_redistributes_when_rochester_exhausted(self):
        rochester_calls = 0
        other_markets: list[str] = []

        def fake_discovery_attempt(**kwargs):
            nonlocal rochester_calls
            split_market = kwargs.get("split_market")
            if split_market == "Rochester":
                rochester_calls += 1
                if rochester_calls == 1:
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
                return [], "[]"
            if split_market:
                other_markets.append(split_market)
                row = {
                    "address": f"1 Oak St, {split_market}, ST 12345",
                    "city": split_market,
                    "list_price": 195000,
                    "listing_url": f"https://www.zillow.com/homedetails/{split_market}-1/",
                }
                return [row], json.dumps([row])
            return [], "[]"

        with patch("engine._run_discovery_attempt", side_effect=fake_discovery_attempt):
            listings = discover_hot_market_listings(model=DISCOVERY_MODEL)

        rochester_count = sum(1 for item in listings if item["city"] == "Rochester")
        self.assertEqual(rochester_count, 3)
        self.assertIn("Syracuse", other_markets)
        self.assertGreater(len(listings), 3)

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

        # $200k purchase, $210k predicted, 4% annual growth, -$500/mo cash flow
        roi = calculate_one_year_roi(
            current_price=200_000,
            predicted_value=210_000,
            forecast_rate_pct=4.0,
            monthly_net_cash_flow=-500,
            down_payment_pct=25.0,
            closing_costs_pct=3.0,
        )
        value_after_one_year = 210_000 * 1.04
        appreciation_gain = value_after_one_year - 200_000
        annual_cash_flow = -500 * 12
        investment = 200_000 * 0.25 + 200_000 * 0.03
        expected = ((appreciation_gain + annual_cash_flow) / investment) * 100.0
        self.assertAlmostEqual(roi, expected, places=2)
        self.assertLess(roi, appreciation_gain / investment * 100)

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

        result = get_final_analysis(
            {
                "price": 200000,
                "rent": 1600,
                "tax_rate": 3.0,
                "insurance": 100,
                "predicted_value": 205000,
                "location_score": 6.5,
            },
            "123 Main St, Rochester, NY",
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
        self.assertIn("Adjusted upward", property_data["prediction_reasoning"])

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


if __name__ == "__main__":
    unittest.main()
