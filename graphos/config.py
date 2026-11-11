"""Configuration fails closed when role credentials are missing or shared."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    artifact_root: Path
    operator_token: str = field(repr=False)
    builder_token: str = field(repr=False)
    verifier_token: str = field(repr=False)
    allow_fixture: bool = False
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]", "testserver")
    max_body_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        tokens = (self.operator_token, self.builder_token, self.verifier_token)
        if any(len(t) < 32 or t.isspace() for t in tokens):
            raise ValueError("Configure three distinct role tokens of at least 32 characters")
        if len(set(tokens)) != 3:
            raise ValueError("Operator, builder and verifier tokens must be distinct")
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("GRAPHOS_DATABASE_URL must reference PostgreSQL")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("Explicit allowed hosts are required")
        object.__setattr__(self, "artifact_root", Path(self.artifact_root).resolve())

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("GRAPHOS_DATABASE_URL", ""),
            artifact_root=Path(os.environ.get("GRAPHOS_ARTIFACT_ROOT", ".state/artifacts")),
            operator_token=os.environ.get("GRAPHOS_OPERATOR_TOKEN", ""),
            builder_token=os.environ.get("GRAPHOS_BUILDER_TOKEN", ""),
            verifier_token=os.environ.get("GRAPHOS_VERIFIER_TOKEN", ""),
            allow_fixture=os.environ.get("GRAPHOS_ALLOW_FIXTURE", "0") == "1",
            allowed_hosts=tuple(x.strip() for x in os.environ.get(
                "GRAPHOS_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver"
            ).split(",") if x.strip()),
        )
