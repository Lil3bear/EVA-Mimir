from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum


class ChallengeCategory(str, Enum):
    WEB = "web"
    PWN = "pwn"
    CRYPTO = "crypto"
    REVERSE = "reverse"
    MISC = "misc"


class MemoryKind(str, Enum):
    FACT = "fact"
    EVIDENCE = "evidence"
    FAILURE = "failure"
    NOTE = "note"
    HINT = "hint"


class IdeaStatus(str, Enum):
    PENDING = "pending"
    TESTING = "testing"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass
class ChallengeConfig:
    id: str
    name: str
    category: str
    difficulty: str
    description: str
    url: str
    flag_format: str = "flag{...}"
    attachments: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    submit_url: str = ""
    api_key: str = ""


@dataclass
class MemoryEntry:
    id: str
    kind: str
    content: str
    created_at: float
    refs: list[str] = field(default_factory=list)
    source: str = "solver"


@dataclass
class IdeaRecord:
    id: str
    content: str
    status: str
    created_at: float
    updated_at: float
    result: str = ""
    source: str = "solver"


@dataclass
class SubmissionRecord:
    id: str
    flag: str
    correct: bool
    submitted_at: float
    writeup: str = ""
    solver_id: str = ""
