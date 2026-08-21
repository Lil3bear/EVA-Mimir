import os
import threading
from dataclasses import dataclass
from typing import Any, Mapping

import requests


DEFAULT_VPN_CHECK_URL = "http://10.0.100.58"


class TsecbenchError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        detail: Any = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail if detail is not None else {}
        self.status_code = status_code

    def __str__(self) -> str:
        return f"{self.code}: {self.message}" if self.code else self.message


class VpnCheckError(TsecbenchError):
    pass


class TaskNotFound(TsecbenchError):
    pass


class ChallengeNotFound(TsecbenchError):
    pass


class InvalidState(TsecbenchError):
    pass


class DuplicateSubmit(TsecbenchError):
    pass


class ResourceUnavailable(TsecbenchError):
    pass


class InternalError(TsecbenchError):
    pass


class ValidationError(TsecbenchError):
    pass


class TsecbenchConnectionError(TsecbenchError):
    pass


ERROR_TYPES: dict[str, type[TsecbenchError]] = {
    "task_not_found": TaskNotFound,
    "challenge_not_found": ChallengeNotFound,
    "invalid_state": InvalidState,
    "duplicate": DuplicateSubmit,
    "resource_unavailable": ResourceUnavailable,
    "internal_error": InternalError,
}


@dataclass(frozen=True)
class Challenge:
    unique_code: str
    description: str | None
    difficulty: str
    level: int
    total_score: int
    flag_count: int
    correct_flag_count: int
    is_completed: bool
    container_status: str
    container_addr: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Challenge":
        return cls(
            unique_code=str(data["unique_code"]),
            description=data.get("description"),
            difficulty=str(data.get("difficulty", "")),
            level=int(data.get("level", 0)),
            total_score=int(data.get("total_score", 0)),
            flag_count=int(data.get("flag_count", 0)),
            correct_flag_count=int(data.get("correct_flag_count", 0)),
            is_completed=bool(data.get("is_completed", False)),
            container_status=str(data.get("container_status", "stopped")),
            container_addr=tuple(str(item) for item in data.get("container_addr", [])),
        )


@dataclass(frozen=True)
class StartResult:
    unique_code: str
    container_addr: tuple[str, ...]


@dataclass(frozen=True)
class HintResult:
    unique_code: str
    hint: str | None


@dataclass(frozen=True)
class SubmitResult:
    correct: bool
    awarded: int
    cumulative_score: int
    correct_flag_count: int
    total_flag_count: int
    matched_flag_index: int | None

    @property
    def is_completed(self) -> bool:
        return self.correct_flag_count >= self.total_flag_count


@dataclass(frozen=True)
class CloseResult:
    unique_code: str
    closed: bool


@dataclass(frozen=True)
class VpnCheckResult:
    status: str
    client_ip: str
    time: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class TsecbenchClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 15.0,
        vpn_check_url: str = DEFAULT_VPN_CHECK_URL,
        session: requests.Session | None = None,
    ) -> None:
        base_url = base_url.strip().rstrip("/")
        token = token.strip()
        if not base_url:
            raise ValueError("BENCHMARK_BASE_URL 不能为空")
        if not token:
            raise ValueError("BENCHMARK_TOKEN 不能为空")
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")

        self.base_url = base_url
        self.token = token
        self.timeout = timeout
        self.start_timeout = 90.0  # start_challenge 启动容器
        self.vpn_check_url = vpn_check_url
        # 并发安全：未显式传入 session 时，每线程独立 Session，
        # 避免 start_challenge 的 90s 长请求阻塞其他并发的平台请求。
        self._shared_session = session
        self._local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

    def _get_session(self) -> requests.Session:
        if self._shared_session is not None:
            return self._shared_session
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> "TsecbenchClient":
        source = os.environ if env is None else env
        return cls(
            base_url=source.get("BENCHMARK_BASE_URL", ""),
            token=source.get("BENCHMARK_TOKEN", ""),
            **kwargs,
        )

    @staticmethod
    def is_configured(env: Mapping[str, str] | None = None) -> bool:
        source = os.environ if env is None else env
        return bool(
            source.get("BENCHMARK_BASE_URL", "").strip()
            and source.get("BENCHMARK_TOKEN", "").strip()
        )

    def close(self) -> None:
        with self._sessions_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            session.close()

    def __enter__(self) -> "TsecbenchClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def check_vpn(self) -> VpnCheckResult:
        try:
            response = self._get_session().get(
                self.vpn_check_url, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise VpnCheckError(
                "vpn_check_failed",
                "VPN检测未通过,请检查靶场VPN网络配置",
                detail={"reason": "network_error", "error": str(exc)},
            ) from exc

        if response.status_code != 200:
            raise VpnCheckError(
                "vpn_check_failed",
                "VPN检测未通过,请检查靶场VPN网络配置",
                detail={"reason": "bad_status"},
                status_code=response.status_code,
            )

        data = self._decode_json(response, vpn_check=True)
        result = VpnCheckResult(
            status=str(data.get("status", "")),
            client_ip=str(data.get("client_ip", "")),
            time=str(data.get("time", "")),
        )
        if not result.ok:
            raise VpnCheckError(
                "vpn_check_failed",
                "VPN检测未通过,请检查靶场VPN网络配置",
                detail={"reason": "status_not_ok", "response": data},
                status_code=response.status_code,
            )
        return result

    def list_challenges(self) -> list[Challenge]:
        data = self._request("GET", "/openapi/v1/challenges")
        if not isinstance(data, list):
            raise TsecbenchError("invalid_response", "题目列表响应不是数组")
        return [Challenge.from_dict(item) for item in data]

    def start_challenge(self, unique_code: str) -> StartResult:
        code = self._require_code(unique_code)
        data = self._request(
            "POST",
            "/openapi/v1/challenges/start",
            params={"unique_code": code},
            timeout=self.start_timeout,
        )
        return StartResult(
            unique_code=str(data["unique_code"]),
            container_addr=tuple(str(item) for item in data.get("container_addr", [])),
        )

    def get_hint(self, unique_code: str) -> HintResult:
        code = self._require_code(unique_code)
        data = self._request(
            "GET",
            "/openapi/v1/challenges/hint",
            params={"unique_code": code},
        )
        return HintResult(
            unique_code=str(data["unique_code"]),
            hint=data.get("hint"),
        )

    def submit_flag(self, unique_code: str, flag: str) -> SubmitResult:
        code = self._require_code(unique_code)
        flag = flag.strip()
        if not 1 <= len(flag) <= 4096:
            raise ValueError("flag 长度必须在 1 到 4096 之间")

        data = self._request(
            "POST",
            "/openapi/v1/challenges/submit",
            json={"unique_code": code, "flag": flag},
        )
        matched = data.get("matched_flag_index")
        return SubmitResult(
            correct=bool(data.get("correct", False)),
            awarded=int(data.get("awarded", 0)),
            cumulative_score=int(data.get("cumulative_score", 0)),
            correct_flag_count=int(data.get("correct_flag_count", 0)),
            total_flag_count=int(data.get("total_flag_count", 0)),
            matched_flag_index=int(matched) if matched is not None else None,
        )

    def close_challenge(self, unique_code: str) -> CloseResult:
        code = self._require_code(unique_code)
        data = self._request(
            "POST",
            "/openapi/v1/challenges/close",
            params={"unique_code": code},
        )
        return CloseResult(
            unique_code=str(data["unique_code"]),
            closed=bool(data.get("closed", False)),
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = dict(kwargs.pop("headers", {}))
        headers["BENCHMARK_TOKEN"] = self.token
        req_timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self._get_session().request(
                method,
                url,
                headers=headers,
                timeout=req_timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise TsecbenchConnectionError(
                "connection_error",
                f"连接 Tsecbench 失败：{exc}",
            ) from exc

        if 200 <= response.status_code < 300:
            return self._decode_json(response)
        self._raise_for_response(response)

    @staticmethod
    def _require_code(unique_code: str) -> str:
        code = unique_code.strip()
        if not code:
            raise ValueError("unique_code 不能为空")
        return code

    @staticmethod
    def _decode_json(response: requests.Response, *, vpn_check: bool = False) -> Any:
        try:
            data = response.json()
        except ValueError as exc:
            if vpn_check:
                raise VpnCheckError(
                    "vpn_check_failed",
                    "VPN检测未通过,请检查靶场VPN网络配置",
                    detail={"reason": "bad_body"},
                    status_code=response.status_code,
                ) from exc
            raise TsecbenchError(
                "invalid_response",
                "Tsecbench 返回了非 JSON 响应",
                status_code=response.status_code,
            ) from exc
        if not isinstance(data, (dict, list)):
            raise TsecbenchError(
                "invalid_response",
                "Tsecbench 返回了无效 JSON 数据",
                status_code=response.status_code,
            )
        return data

    @staticmethod
    def _raise_for_response(response: requests.Response) -> None:
        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code == 422:
            raise ValidationError(
                "validation_error",
                "请求参数校验失败",
                detail=data.get("detail", data) if isinstance(data, dict) else data,
                status_code=422,
            )

        if isinstance(data, dict):
            code = str(data.get("code", "http_error"))
            message = str(data.get("message", f"HTTP {response.status_code}"))
            detail = data.get("detail", {})
        else:
            code = "http_error"
            message = f"HTTP {response.status_code}"
            detail = {}

        error_type = ERROR_TYPES.get(code, TsecbenchError)
        raise error_type(
            code,
            message,
            detail=detail,
            status_code=response.status_code,
        )
