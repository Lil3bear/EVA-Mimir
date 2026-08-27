import threading
import unittest
from unittest.mock import patch

from solver.ctfplatform.tsecbench_client import (
    DuplicateSubmit,
    InvalidState,
    TsecbenchClient,
    VpnCheckError,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses=None, vpn_response=None):
        self.responses = list(responses or [])
        self.vpn_response = vpn_response
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return self.vpn_response

    def close(self):
        self.closed = True


class TsecbenchClientTests(unittest.TestCase):
    def test_list_challenges_uses_exact_auth_header(self):
        session = FakeSession([
            FakeResponse(200, [{
                "unique_code": "web-01",
                "description": "SQL injection",
                "difficulty": "easy",
                "level": 1,
                "total_score": 100,
                "flag_count": 2,
                "correct_flag_count": 0,
                "is_completed": False,
                "container_status": "stopped",
                "container_addr": [],
            }])
        ])
        client = TsecbenchClient("https://bench.example", "token-1", session=session)

        challenges = client.list_challenges()

        self.assertEqual(challenges[0].unique_code, "web-01")
        method, url, kwargs = session.requests[0]
        self.assertEqual((method, url), ("GET", "https://bench.example/openapi/v1/challenges"))
        self.assertEqual(kwargs["headers"]["BENCHMARK_TOKEN"], "token-1")
        self.assertNotIn("Authorization", kwargs["headers"])

    def test_start_submit_and_close_use_query_and_json_shapes(self):
        session = FakeSession([
            FakeResponse(200, {"unique_code": "web-01", "container_addr": ["10.0.0.2:8080"]}),
            FakeResponse(200, {
                "correct": True,
                "awarded": 50,
                "cumulative_score": 50,
                "correct_flag_count": 1,
                "total_flag_count": 1,
                "matched_flag_index": 0,
            }),
            FakeResponse(200, {"unique_code": "web-01", "closed": True}),
        ])
        client = TsecbenchClient("https://bench.example/", "token", session=session)

        start = client.start_challenge("web-01")
        submit = client.submit_flag("web-01", "flag{ok}")
        close = client.close_challenge("web-01")

        self.assertEqual(start.container_addr, ("10.0.0.2:8080",))
        self.assertTrue(submit.is_completed)
        self.assertTrue(close.closed)
        self.assertEqual(session.requests[0][2]["params"], {"unique_code": "web-01"})
        self.assertEqual(session.requests[1][2]["json"], {"unique_code": "web-01", "flag": "flag{ok}"})
        self.assertEqual(session.requests[2][2]["params"], {"unique_code": "web-01"})

    def test_duplicate_and_invalid_state_map_to_specific_errors(self):
        session = FakeSession([
            FakeResponse(409, {"code": "duplicate", "message": "already submitted", "detail": {}}),
            FakeResponse(409, {"code": "invalid_state", "message": "task ended", "detail": {}}),
        ])
        client = TsecbenchClient("https://bench.example", "token", session=session)

        with self.assertRaises(DuplicateSubmit):
            client.submit_flag("web-01", "flag{same}")
        with self.assertRaises(InvalidState):
            client.close_challenge("web-01")

    def test_vpn_check_requires_status_ok(self):
        session = FakeSession(vpn_response=FakeResponse(200, {"status": "down"}))
        client = TsecbenchClient("https://bench.example", "token", session=session)

        with self.assertRaises(VpnCheckError) as caught:
            client.check_vpn()

        self.assertEqual(caught.exception.detail["reason"], "status_not_ok")
        self.assertEqual(session.requests[0][1], "http://10.0.100.58")

    def test_from_env_requires_both_values(self):
        self.assertTrue(TsecbenchClient.is_configured({
            "BENCHMARK_BASE_URL": "https://bench.example",
            "BENCHMARK_TOKEN": "token",
        }))
        self.assertFalse(TsecbenchClient.is_configured({"BENCHMARK_BASE_URL": ""}))
        with self.assertRaises(ValueError):
            TsecbenchClient.from_env({"BENCHMARK_BASE_URL": "https://bench.example"})

    def test_default_session_is_thread_local(self):
        sessions = []

        def make_session():
            session = FakeSession([FakeResponse(200, [])])
            sessions.append(session)
            return session

        errors = []
        with patch(
            "solver.ctfplatform.tsecbench_client.requests.Session",
            side_effect=make_session,
        ):
            client = TsecbenchClient("https://bench.example", "token")

            def request():
                try:
                    client.list_challenges()
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=request) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            client.close()

        self.assertEqual(errors, [])
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session.closed for session in sessions))


if __name__ == "__main__":
    unittest.main()
