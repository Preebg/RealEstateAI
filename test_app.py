import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import math

# Mock streamlit before importing engine to avoid secrets errors
with patch('streamlit.secrets', {"GEMINI_API_KEY": "fake_key"}):
    from engine import (
        run_search_with_failover, 
        calculate_10yr_appreciation, 
        calculate_quantum_probability, 
        run_monte_carlo
    )
    from google.genai import errors

class TestAIUnderwriterEngine(unittest.TestCase):

    @patch('engine.client.models.generate_content')
    def test_run_search_with_failover(self, mock_generate):
        """
        Test that the system fails over to the secondary model 
        after the primary model returns a 500 error.
        """
        # Setup: First 3 calls raise a 500 ClientError, 4th call (fallback) succeeds
        mock_error = errors.ClientError(code=500, response_json={})
        
        mock_success = MagicMock()
        mock_success.text = "Success from fallback"
        
        mock_generate.side_effect = [mock_error, mock_error, mock_error, mock_success]

        # We mock time.sleep to make the test run instantly
        with patch('time.sleep', return_value=None):
            result = run_search_with_failover("Test Address")

        self.assertEqual(result.text, "Success from fallback")
        # Verify it was called 4 times (3 primary attempts + 1 fallback)
        self.assertEqual(mock_generate.call_count, 4)

    def test_calculate_10yr_appreciation_zero_value(self):
        """
        Test that passing a current_value of 0 returns the guard-clause 
        dictionary instead of raising a ZeroDivisionError.
        """
        result = calculate_10yr_appreciation(0, 10)
        expected = {"future_value": 0, "annual_rate": 0, "total_growth": 0}
        self.assertEqual(result, expected)

    def test_calculate_quantum_probability(self):
        """
        Verify that calculate_quantum_probability correctly maps 
        location_score 0 to 0% and 10 to 100%.
        """
        # Score 0 -> theta 0 -> sin(0)^2 = 0
        self.assertAlmostEqual(calculate_quantum_probability(0), 0.0)
        
        # Score 10 -> theta pi/2 -> sin(pi/2)^2 = 1^2 = 100%
        self.assertAlmostEqual(calculate_quantum_probability(10), 100.0)
        
        # Score 5 -> theta pi/4 -> sin(pi/4)^2 = (sqrt(2)/2)^2 = 0.5 = 50%
        self.assertAlmostEqual(calculate_quantum_probability(5), 50.0)

    def test_run_monte_carlo_stability(self):
        """
        Ensure run_monte_carlo returns exactly 1,000 results 
        and handles various forecast rates.
        """
        current_value = 300000
        forecast_rate = 4.5
        vacancy_rate = 5.0
        
        results = run_monte_carlo(current_value, forecast_rate, vacancy_rate)
        
        # Check length
        self.assertEqual(len(results), 1000)
        
        # Check that results are numeric and reasonable (not all zeros or NaNs)
        self.assertTrue(all(isinstance(x, (int, float)) for x in results))
        self.assertTrue(any(x > 0 for x in results))

    def test_run_monte_carlo_negative_growth(self):
        """
        Ensure Monte Carlo handles negative growth rates without crashing.
        """
        results = run_monte_carlo(300000, -2.0, 5.0)
        self.assertEqual(len(results), 1000)
        # With negative growth, the average should be lower than the starting value
        self.assertTrue(np.mean(results) < 300000)

if __name__ == '__main__':
    unittest.main()
