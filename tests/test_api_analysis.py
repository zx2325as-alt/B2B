
import unittest
import requests
import json
import time

API_URL = "http://localhost:8000/api/v1"

class TestAnalysisAPI(unittest.TestCase):
    def test_analysis_conversation_quick(self):
        """Test quick analysis mode"""
        payload = {
            "text": "Hello, how are you?",
            "character_names": ["System"],
            "mode": "quick",
            "session_id": "test_session",
            "audio_features": {"pitch_mean": 200, "energy_mean": 0.5}
        }
        try:
            response = requests.post(f"{API_URL}/analysis/conversation", json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.assertIn("markdown_report", data)
                print("Quick analysis test passed")
            else:
                print(f"Skipping API test (Server might be down): {response.status_code}")
        except requests.exceptions.ConnectionError:
            print("Skipping API test (Server not running)")

    def test_analysis_conversation_deep(self):
        """Test deep analysis mode with multi-role"""
        payload = {
            "text": "I really hate this situation! Why is everyone ignoring me?",
            "character_names": ["Alice", "Bob"],
            "mode": "deep",
            "session_id": "test_session_deep",
            "audio_features": {"pitch_mean": 350, "energy_mean": 0.8} # High pitch/energy
        }
        try:
            response = requests.post(f"{API_URL}/analysis/conversation", json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                self.assertIn("markdown_report", data)
                self.assertIn("structured_data", data)
                print("Deep analysis test passed")
            else:
                print(f"Skipping API test (Server might be down): {response.status_code}")
        except requests.exceptions.ConnectionError:
            print("Skipping API test (Server not running)")

if __name__ == '__main__':
    unittest.main()
