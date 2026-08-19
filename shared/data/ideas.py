import json
import os
import sys
import time
from pathlib import Path
from contextlib import contextmanager
from shared.types import IdeaRecord

if sys.platform != "win32":
    import fcntl

LOCK_TIMEOUT = 5.0
LOCK_RETRY_INTERVAL = 0.025


@contextmanager
def _file_lock(lock_path: Path):
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


def _index_path(challenge_dir: Path) -> Path:
    return challenge_dir / "ideas" / "index.json"


def _lock_path(challenge_dir: Path) -> Path:
    return challenge_dir / "locks" / "ideas.lock"


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".{os.getpid()}.{time.time()}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _load_index(challenge_dir: Path) -> list[dict]:
    idx = _index_path(challenge_dir)
    if not idx.exists():
        return []
    try:
        return json.loads(idx.read_text(encoding="utf-8"))
    except Exception:
        return []


def add_idea(challenge_dir: Path, content: str, source: str = "solver") -> IdeaRecord:
    normalized = content.strip().lower()
    with _file_lock(_lock_path(challenge_dir)):
        ideas = _load_index(challenge_dir)
        for idea in ideas:
            if idea.get("content", "").strip().lower() == normalized:
                return IdeaRecord(**idea)
        now = time.time()
        idea = IdeaRecord(
            id=f"idea_{os.urandom(4).hex()}",
            content=content,
            status="pending",
            created_at=now,
            updated_at=now,
            source=source,
        )
        ideas.append(idea.__dict__)
        _atomic_write(_index_path(challenge_dir), ideas)
        return idea


def list_ideas(challenge_dir: Path, limit: int = None) -> list[IdeaRecord]:
    ideas = _load_index(challenge_dir)
    if limit:
        ideas = ideas[-limit:]
    return [IdeaRecord(**i) for i in ideas]


def update_idea(challenge_dir: Path, idea_id: str,
                status: str = None, result: str = None) -> bool:
    with _file_lock(_lock_path(challenge_dir)):
        ideas = _load_index(challenge_dir)
        for idea in ideas:
            if idea.get("id") == idea_id or idea.get("id", "").startswith(idea_id):
                if status:
                    idea["status"] = status
                if result is not None:
                    idea["result"] = result
                idea["updated_at"] = time.time()
                _atomic_write(_index_path(challenge_dir), ideas)
                return True
    return False


def delete_idea(challenge_dir: Path, idea_id: str) -> bool:
    with _file_lock(_lock_path(challenge_dir)):
        ideas = _load_index(challenge_dir)
        new_ideas = [i for i in ideas
                     if not (i.get("id") == idea_id or i.get("id", "").startswith(idea_id))]
        if len(new_ideas) == len(ideas):
            return False
        _atomic_write(_index_path(challenge_dir), new_ideas)
        return True
