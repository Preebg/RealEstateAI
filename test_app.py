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
        payload = json.dumps(
            [
                {
                    "address": "10 Park Ave, Rochester, NY",
                    "city": "Rochester",
                    "list_price": 210000,
                }
            ]
        )
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
            if model == DISCOVERY_MODEL:
                raise quota_err
            return payload

        with patch("engine.generate_with_retry", side_effect=fake_generate):
            listings = discover_hot_market_listings()
        self.assertEqual(len(listings), 1)
        self.assertEqual(calls[0], DISCOVERY_MODEL)
        self.assertEqual(calls[1], DISCOVERY_FALLBACK_MODEL)
        self.assertTrue(all(model == DISCOVERY_FALLBACK_MODEL for model in calls[1:]))


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


class TestDiscoveryParsing(unittest.TestCase):
    def test_extract_wrapped_listings_object(self):
        from engine import _build_listings_from_raw

        raw = json.dumps(
            {
                "listings": [
                    {
                        "address": "10 Park Ave, Rochester, NY",
                        "city": "Rochester",
                        "price": 210000,
                    }
                ]
            }
        )
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")
        self.assertEqual(listings[0]["list_price"], 210000.0)

    def test_discover_uses_split_market_when_combined_empty(self):
        calls = {"count": 0}

        def fake_generate(model, prompt, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return "No parseable listings in this response."
            return json.dumps(
                [
                    {
                        "address": "15 Maple Dr, Rochester, NY 14609",
                        "city": "Rochester",
                        "list_price": 199000,
                    }
                ]
            )

        with patch("engine.generate_with_retry", side_effect=fake_generate):
            listings = discover_hot_market_listings(model=DISCOVERY_MODEL)

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")
        self.assertGreater(calls["count"], 1)

    def test_suburb_address_maps_to_parent_metro(self):
        from engine import _build_listings_from_raw

        raw = json.dumps(
            [
                {
                    "address": "22 Suburban Ln, Henrietta, NY 14623",
                    "city": "Rochester",
                    "list_price": 185000,
                }
            ]
        )
        listings = _build_listings_from_raw(raw, 250_000)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["city"], "Rochester")


class TestOneYearROI(unittest.TestCase):
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
        self.assertNotIn("rent", payload)


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


if __name__ == "__main__":
    unittest.main()
