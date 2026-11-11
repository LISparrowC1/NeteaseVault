"""Strict candidate matching.

A candidate may be downloaded automatically only when every rule passes and it is
the single passing candidate. Anything else goes to manual review -- that rule
lives at the call site, this module only answers "does this candidate pass".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .normalize import duration_seconds, normalize


@dataclass
class RuleResult:
    name: str
    passed: bool
    expected: str
    actual: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.name, "passed": self.passed, "expected": self.expected, "actual": self.actual}


@dataclass
class MatchResult:
    passed: bool
    rules: list[RuleResult] = field(default_factory=list)

    def failed_rules(self) -> list[str]:
        return [r.name for r in self.rules if not r.passed]

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "rules": [r.as_dict() for r in self.rules]}


def _cmp(name: str, expected: str, actual: str) -> RuleResult:
    return RuleResult(name=name, passed=expected == actual, expected=expected, actual=actual)


def match_candidate(track: dict[str, Any], candidate: dict[str, Any]) -> MatchResult:
    """Compare one search candidate against the cloud track metadata.

    `track` uses the fields stored in the database (title/artist/album/duration_ms).
    `candidate` uses the same names; duration is in milliseconds.
    """
    title = _cmp("title", normalize(track.get("title")), normalize(candidate.get("title")))
    artist = _cmp("artist", normalize(track.get("artist")), normalize(candidate.get("artist")))
    album = _cmp("album", normalize(track.get("album")), normalize(candidate.get("album")))

    expected_s = duration_seconds(track.get("duration_ms"))
    actual_s = duration_seconds(candidate.get("duration_ms"))
    duration = RuleResult(
        name="duration",
        passed=expected_s is not None and expected_s == actual_s,
        expected=str(expected_s),
        actual=str(actual_s),
    )

    rules = [title, artist, album, duration]
    return MatchResult(passed=all(r.passed for r in rules), rules=rules)


def select_unique(track: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[MatchResult]]:
    """Return (auto_candidate, results).

    `auto_candidate` is set only when exactly one candidate passes every rule.
    """
    results = [match_candidate(track, c) for c in candidates]
    passing = [c for c, r in zip(candidates, results) if r.passed]
    if len(passing) == 1:
        return passing[0], results
    return None, results
