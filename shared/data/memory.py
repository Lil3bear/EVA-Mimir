import json
import os
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
    import re
    tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', text.lower()))
    # 过滤掉太短的 token（单字母/单汉字意义不大）
    return {t for t in tokens if len(t) > 1}


def _is_duplicate(existing: list[MemoryEntry], kind: str, content: str,
                  threshold: float = 0.7) -> MemoryEntry | None:
    """检查新内容是否与已有同 kind 条目高度重复。返回重复的条目或 None。"""
    new_tokens = _tokenize(content)
    if not new_tokens:
        return None
    for entry in existing:
        if entry.kind != kind:
            continue
        old_tokens = _tokenize(entry.content)
        if not old_tokens:
            continue
        overlap = len(new_tokens & old_tokens)
        similarity = overlap / min(len(new_tokens), len(old_tokens))
        if similarity >= threshold:
            return entry
    return None


def add_memory(challenge_dir: Path, kind: str, content: str,
               refs: list[str] = None, source: str = "solver") -> MemoryEntry:
    entries_dir = _entries_dir(challenge_dir)
    entries_dir.mkdir(parents=True, exist_ok=True)

    # 去重：同 kind 下关键词重叠度 >= 70% 视为重复，返回已有条目
    existing = list_memory(challenge_dir)
    dup = _is_duplicate(existing, kind, content)
    if dup:
        return dup

    entry = MemoryEntry(
        id=f"mem_{os.urandom(4).hex()}",
        kind=kind,
        content=content,
        created_at=time.time(),
        refs=refs or [],
        source=source,
    )
    filename = f"{int(entry.created_at * 1000)}-{entry.id}.json"
    _atomic_write(entries_dir / filename, entry.__dict__)
    return entry


def list_memory(challenge_dir: Path, limit: int = None) -> list[MemoryEntry]:
    entries_dir = _entries_dir(challenge_dir)
    if not entries_dir.exists():
        return []
    files = sorted(entries_dir.glob("*.json"), key=lambda f: f.name)
    if limit:
        files = files[-limit:]
    entries = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entries.append(MemoryEntry(**data))
        except Exception:
            continue
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
