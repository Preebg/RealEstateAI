import unittest
from unittest.mock import patch

# Mock streamlit before importing engine to avoid secrets errors
with patch('streamlit.secrets', {"GEMINI_API_KEY": "fake_key"}):
    from engine import calculate_quantum_probability, calculate_quantum_risk
    from finance import calculate_10yr_appreciation

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
        # Score 0 -> 0%
        self.assertAlmostEqual(calculate_quantum_probability(0), 0.0)
        
        # Score 10 -> 100%
        self.assertAlmostEqual(calculate_quantum_probability(10), 100.0)
        
        # Score 5 -> 50%
        self.assertAlmostEqual(calculate_quantum_probability(5), 50.0)

    def test_calculate_quantum_probability_qaoa_three_args(self):
        """
        Verify that calculate_quantum_probability runs the QAOA circuit
        properly when 3 arguments are provided.
        """
        # Perfect property: high cash flow, high forecast, high location score
        score_perfect = calculate_quantum_probability(1000.0, 10.0, 10.0)
        self.assertTrue(0.0 <= score_perfect <= 100.0)
        
        # Poor property: 0 cash flow, 0 forecast, 0 location score
        score_poor = calculate_quantum_probability(0.0, 0.0, 0.0)
        self.assertEqual(score_poor, 0.0)

        # Average property: check that it returns a valid probability
        score_avg = calculate_quantum_probability(500.0, 5.0, 5.0)
        self.assertTrue(0.0 < score_avg < 100.0)

    def test_calculate_quantum_risk_breakdown(self):
        """Breakdown includes cash-flow and appreciation success probabilities."""
        risk = calculate_quantum_risk(1000.0, 10.0, 10.0)
        for key in (
            "cashflow_success_pct",
            "appreciation_success_pct",
            "combined_wealth_success_pct",
            "overall_success_pct",
        ):
            self.assertIn(key, risk)
            self.assertTrue(0.0 <= risk[key] <= 100.0)

        risk_poor = calculate_quantum_risk(0.0, 0.0, 0.0)
        self.assertEqual(risk_poor["combined_wealth_success_pct"], 0.0)

    def test_calculate_quantum_risk_legacy_location_only(self):
        """Legacy shortcut: zero cash flow + zero forecast maps location score to all fields."""
        breakdown_keys = (
            "cashflow_success_pct",
            "appreciation_success_pct",
            "location_success_pct",
            "combined_wealth_success_pct",
            "overall_success_pct",
        )
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

if __name__ == '__main__':
    unittest.main()

