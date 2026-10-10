"""Which rules run, at what severity, over which resources.

A configuration is a profile plus per-rule overrides. Settings resolve in three
layers: the rule's own default, then the profile's, then the configuration's.
The configuration is plain data, validated here and stored as JSON. No YAML or
Pydantic dependency: the shape is small enough to check by hand, and every error
names the field it is about.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .models import SEVERITIES, Severity
from .registry import RULES


class QualityConfigError(ValueError):
    """A configuration that names an unknown rule, profile or severity."""


@dataclass(frozen=True)
class RuleSettings:
    """An override for one rule. None leaves the layer below in force."""

    enabled: bool | None = None
    severity: Severity | None = None


#: Profiles: named sets of overrides. More arrive with the rules they tune
#: (``skos_vocabulary`` with the SKOS rules, ``strict_documentation`` with the
#: definition rules), because a profile may only name rules that exist.
PROFILES: dict[str, dict[str, RuleSettings]] = {
    "general_ontology": {},
}

DEFAULT_PROFILE = "general_ontology"


@dataclass(frozen=True)
class QualityConfig:
    profile: str = DEFAULT_PROFILE
    #: Check merged-in vocabularies too, not only the ontology's own resources.
    include_imports: bool = False
    rules: dict[str, RuleSettings] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.profile not in PROFILES:
            raise QualityConfigError(
                f"profile: unknown profile {self.profile!r}; "
                f"expected one of {', '.join(PROFILES)}"
            )
        for rule_id, settings in self.rules.items():
            if rule_id not in RULES:
                raise QualityConfigError(f"rules.{rule_id}: unknown rule ID")
            if settings.severity is not None and settings.severity not in SEVERITIES:
                raise QualityConfigError(
                    f"rules.{rule_id}.severity: {settings.severity!r} is not one of "
                    f"{', '.join(SEVERITIES)}"
                )

    def enabled(self, rule_id: str) -> bool:
        return self._resolve(rule_id)[0]

    def severity(self, rule_id: str) -> Severity:
        return self._resolve(rule_id)[1]

    def _resolve(self, rule_id: str) -> tuple[bool, Severity]:
        rule = RULES[rule_id]
        enabled, severity = rule.default_enabled, rule.default_severity
        for layer in (PROFILES[self.profile].get(rule_id), self.rules.get(rule_id)):
            if layer is not None:
                if layer.enabled is not None:
                    enabled = layer.enabled
                if layer.severity is not None:
                    severity = layer.severity
        return enabled, severity

    def enabled_rules(self) -> list[str]:
        return [rule_id for rule_id in RULES if self.enabled(rule_id)]

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "include_imports": self.include_imports,
            "rules": {
                rule_id: {
                    key: value
                    for key, value in (
                        ("enabled", s.enabled),
                        ("severity", s.severity),
                    )
                    if value is not None
                }
                for rule_id, s in sorted(self.rules.items())
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)

    @property
    def fingerprint(self) -> str:
        """Changes whenever the effective configuration does."""
        effective = {
            "include_imports": self.include_imports,
            "rules": {
                rule_id: [self.enabled(rule_id), self.severity(rule_id)]
                for rule_id in RULES
            },
        }
        digest = hashlib.sha256(json.dumps(effective, sort_keys=True).encode())
        return digest.hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: Any) -> QualityConfig:
        if not isinstance(data, dict):
            raise QualityConfigError("config: expected an object")
        unknown = set(data) - {"profile", "include_imports", "rules"}
        if unknown:
            raise QualityConfigError(
                f"config: unknown keys {', '.join(sorted(unknown))}"
            )
        profile = data.get("profile", DEFAULT_PROFILE)
        if not isinstance(profile, str):
            raise QualityConfigError("profile: expected a string")
        include_imports = data.get("include_imports", False)
        if not isinstance(include_imports, bool):
            raise QualityConfigError("include_imports: expected true or false")
        raw_rules = data.get("rules", {})
        if not isinstance(raw_rules, dict):
            raise QualityConfigError("rules: expected an object")
        rules: dict[str, RuleSettings] = {}
        for rule_id, raw in raw_rules.items():
            if not isinstance(raw, dict):
                raise QualityConfigError(f"rules.{rule_id}: expected an object")
            unknown = set(raw) - {"enabled", "severity"}
            if unknown:
                raise QualityConfigError(
                    f"rules.{rule_id}: unknown keys {', '.join(sorted(unknown))}"
                )
            enabled = raw.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                raise QualityConfigError(
                    f"rules.{rule_id}.enabled: expected true or false"
                )
            rules[rule_id] = RuleSettings(enabled, raw.get("severity"))
        return cls(profile=profile, include_imports=include_imports, rules=rules)

    @classmethod
    def from_json(cls, text: str) -> QualityConfig:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QualityConfigError(f"config: not valid JSON ({exc.msg})") from exc
        return cls.from_dict(data)
