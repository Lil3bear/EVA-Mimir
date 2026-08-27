import json
import os
import re
import sys
import time
from pathlib import Path
from contextlib import contextmanager
from shared.types import MemoryEntry

if sys.platform != "win32":
    import fcntl

LOCK_TIMEOUT = 5.0
LOCK_RETRY_INTERVAL = 0.025


@contextmanager
def _file_lock(lock_path: Path):
    # Windows 宿主机不加锁（只有 Host 读，不并发写）
    # Linux 容器内加 fcntl 文件锁（Solver + Observer 并发写）
    if sys.platform == "win32":
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + LOCK_TIMEOUT
    lock_file = None
    try:
        while True:
            try:
                lock_file = open(lock_path, "w")
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (IOError, OSError):
                if lock_file:
                    lock_file.close()
                    lock_file = None
                if time.time() > deadline:
                    raise TimeoutError(f"无法获取锁：{lock_path}")
                time.sleep(LOCK_RETRY_INTERVAL)
        yield
    finally:
        if lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".{os.getpid()}.{time.time()}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _entries_dir(challenge_dir: Path) -> Path:
    return challenge_dir / "memory" / "entries"


def _lock_path(challenge_dir: Path) -> Path:
    return challenge_dir / "locks" / "memory.lock"


def _tokenize(text: str) -> set[str]:
    """将文本拆为关键词集合，用于模糊去重。"""
    # 去标点、转小写、按空格和常见分隔符拆分
    normalized = text.lower()
    tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', normalized))
    tokens.update(re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', normalized))
    # 过滤掉太短的 token（单字母/单汉字意义不大）
    return {t for t in tokens if len(t) > 1 or t.isdigit()}


def _structured_values(text: str) -> set[str]:
    """提取不能被模糊去重吞掉的目标、凭据和标识值。"""
    normalized = text.lower()
    values = {
        f"ip:{value}"
        for value in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', normalized)
    }
    values.update(
        f"url:{value}"
        for value in re.findall(r'https?://[^\s\]\[<>{}"\']+', normalized)
    )
    values.update(
        f"endpoint:{value}"
        for value in re.findall(
            r'\b(?:[a-z0-9.-]+|\[[0-9a-f:]+\]):\d{1,5}\b', normalized
        )
    )
    values.update(
        f"port:{value}"
        for value in re.findall(
            r'(?:\bport\b|端口)\s*(?:=|:|：|is|为|是)?\s*(\d{1,5})',
            normalized,
        )
    )
    values.update(
        f"path:{value}"
        for value in re.findall(r'(?<![\w])/[a-z0-9._~!$&()*+,;=:@%/-]+', normalized)
    )

    credential_pattern = re.compile(
        r'(?=(?:\b(?:password|passwd|pwd|token|api[_ -]?key|secret|user(?:name)?)\b|'
        r'密码|口令|用户名|账号)'
        r'\s*(?:value|值)?\s*(?:=|:|：|is|为|是)?\s*'
        r'["\']?([^\s,，;；。"\'\]\[<>{}]+))',
        re.IGNORECASE,
    )
    ignored_values = {
        "password", "passwd", "pwd", "token", "key", "secret", "user", "username",
    }
    values.update(
        f"credential:{value.lower()}"
        for value in credential_pattern.findall(text)
        if value.lower() not in ignored_values
    )

    # 数字或混合标识通常承载端口、版本、ID、哈希等精确信息。
    values.update(
        f"identifier:{value}"
        for value in re.findall(r'\b[a-z0-9._-]*\d[a-z0-9._-]*\b', normalized)
    )
    return values


def _is_duplicate(existing: list[MemoryEntry], kind: str, content: str,
                  threshold: float = 0.7) -> MemoryEntry | None:
    """检查新内容是否与已有同 kind 条目高度重复。返回重复的条目或 None。"""
    new_tokens = _tokenize(content)
    if not new_tokens:
        return None
    new_values = _structured_values(content)
    for entry in existing:
        if entry.kind != kind:
            continue
        old_tokens = _tokenize(entry.content)
        if not old_tokens:
            continue
        old_values = _structured_values(entry.content)
        if (new_values or old_values) and new_values != old_values:
            continue
        overlap = len(new_tokens & old_tokens)
        similarity = overlap / len(new_tokens | old_tokens)
        if similarity >= threshold:
            return entry
    return None


def add_memory_with_status(challenge_dir: Path, kind: str, content: str,
                           refs: list[str] = None, source: str = "solver",
                           attempt_id: str = "primary") -> tuple[MemoryEntry, bool]:
    """添加记忆，返回 ``(entry, created)``。"""
    entries_dir = _entries_dir(challenge_dir)
    entries_dir.mkdir(parents=True, exist_ok=True)

    with _file_lock(_lock_path(challenge_dir)):
        existing = list_memory(challenge_dir)
        dup = _is_duplicate(existing, kind, content)
        if dup:
            return dup, False

        entry = MemoryEntry(
            id=f"mem_{os.urandom(4).hex()}",
            kind=kind,
            content=content,
            created_at=time.time(),
            refs=refs or [],
            source=source,
            attempt_id=attempt_id,
        )
        filename = f"{int(entry.created_at * 1000)}-{entry.id}.json"
        _atomic_write(entries_dir / filename, entry.__dict__)
        return entry, True


def add_memory(challenge_dir: Path, kind: str, content: str,
               refs: list[str] = None, source: str = "solver",
               attempt_id: str = "primary") -> MemoryEntry:
    """向后兼容的添加接口；需要判断是否新增时使用 add_memory_with_status。"""
    entry, _ = add_memory_with_status(
        challenge_dir,
        kind,
        content,
        refs=refs,
        source=source,
        attempt_id=attempt_id,
    )
    return entry


def list_memory(challenge_dir: Path, limit: int = None) -> list[MemoryEntry]:
    entries_dir = _entries_dir(challenge_dir)
    if not entries_dir.exists():
        return []
    entries = []
    for f in entries_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entries.append(MemoryEntry(**data))
        except Exception:
            continue
    entries.sort(key=lambda entry: (entry.created_at, entry.id))
    if limit:
        entries = entries[-limit:]
    return entries


def delete_memory(challenge_dir: Path, memory_id: str) -> bool:
    entries_dir = _entries_dir(challenge_dir)
    with _file_lock(_lock_path(challenge_dir)):
        for f in entries_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("id") == memory_id or data.get("id", "").startswith(memory_id):
                    f.unlink()
                    return True
            except Exception:
                continue
    return False


def update_memory(challenge_dir: Path, memory_id: str, content: str) -> bool:
    entries_dir = _entries_dir(challenge_dir)
    with _file_lock(_lock_path(challenge_dir)):
        for f in entries_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("id") == memory_id or data.get("id", "").startswith(memory_id):
                    data["content"] = content
                    _atomic_write(f, data)
                    return True
            except Exception:
                continue
    return False
