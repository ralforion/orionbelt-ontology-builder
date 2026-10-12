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
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from .models import SEVERITIES, QualityFinding, Severity, Suppression
from .registry import RULES


class QualityConfigError(ValueError):
    """A configuration that names an unknown rule, profile or severity."""


@dataclass(frozen=True)
class RuleSettings:
    """An override for one rule. None leaves the layer below in force."""

    enabled: bool | None = None
    severity: Severity | None = None


#: Profiles: named sets of overrides on the rules' own defaults. A profile
#: may only name rules that exist.
PROFILES: dict[str, dict[str, RuleSettings]] = {
    "general_ontology": {},
    # A thesaurus lives by its definitions; class naming rules do not apply.
    "skos_vocabulary": {
        "Q002": RuleSettings(severity="warning"),
        "Q005": RuleSettings(enabled=False),
        "Q017": RuleSettings(enabled=True),
    },
    # Every class and property documented, nothing left as a placeholder.
    "strict_documentation": {
        "Q002": RuleSettings(severity="warning"),
        "Q004": RuleSettings(severity="error"),
        "Q012": RuleSettings(enabled=True),
        "Q013": RuleSettings(enabled=True),
        "Q022": RuleSettings(enabled=True),
    },
}

DEFAULT_PROFILE = "general_ontology"

_SUPPRESSION_FIELDS = ("rule_id", "resource", "justification", "author", "date")


def _suppressions_from(raw: Any) -> tuple[Suppression, ...]:
    if not isinstance(raw, list):
        raise QualityConfigError("suppressions: expected a list")
    result = []
    for i, item in enumerate(raw):
        where = f"suppressions[{i}]"
        if not isinstance(item, dict):
            raise QualityConfigError(f"{where}: expected an object")
        unknown = set(item) - set(_SUPPRESSION_FIELDS)
        if unknown:
            raise QualityConfigError(
                f"{where}: unknown keys {', '.join(sorted(unknown))}"
            )
        for name in _SUPPRESSION_FIELDS:
            if not isinstance(item.get(name, ""), str):
                raise QualityConfigError(f"{where}.{name}: expected a string")
        result.append(Suppression(**{k: item.get(k, "") for k in _SUPPRESSION_FIELDS}))
    return tuple(result)


@dataclass(frozen=True)
class QualityConfig:
    profile: str = DEFAULT_PROFILE
    #: Check merged-in vocabularies too, not only the ontology's own resources.
    include_imports: bool = False
    rules: dict[str, RuleSettings] = field(default_factory=dict)
    #: Findings marked as deliberate. Kept with the settings, not in the
    #: ontology: an exported file must not carry editor settings.
    suppressions: tuple[Suppression, ...] = ()

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
        for i, suppression in enumerate(self.suppressions):
            where = f"suppressions[{i}]"
            if suppression.rule_id not in RULES:
                raise QualityConfigError(f"{where}.rule_id: unknown rule ID")
            if not suppression.resource.strip():
                raise QualityConfigError(f"{where}.resource: must not be empty")
            if not suppression.justification.strip():
                raise QualityConfigError(
                    f"{where}.justification: say why the finding is fine"
                )

    def suppression_for(self, finding: QualityFinding) -> Suppression | None:
        return next((s for s in self.suppressions if s.matches(finding)), None)

    def with_suppression(self, suppression: Suppression) -> QualityConfig:
        """This configuration with ``suppression`` added, replacing any for
        the same rule and resource."""
        kept = tuple(
            s
            for s in self.suppressions
            if (s.rule_id, s.resource) != (suppression.rule_id, suppression.resource)
        )
        return replace(self, suppressions=(*kept, suppression))

    def without_suppression(self, rule_id: str, resource: str) -> QualityConfig:
        return replace(
            self,
            suppressions=tuple(
                s
                for s in self.suppressions
                if (s.rule_id, s.resource) != (rule_id, resource)
            ),
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
        data: dict[str, Any] = {
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
        if self.suppressions:
            data["suppressions"] = [asdict(s) for s in self.suppressions]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)

    @property
    def fingerprint(self) -> str:
        """Changes whenever the effective rule configuration does.

        Suppressions are left out: they decide what is shown, not what a run
        finds, so marking a finding as fine does not make the run stale.
        """
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
        unknown = set(data) - {"profile", "include_imports", "rules", "suppressions"}
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
        return cls(
            profile=profile,
            include_imports=include_imports,
            rules=rules,
            suppressions=_suppressions_from(data.get("suppressions", [])),
        )

    @classmethod
    def from_json(cls, text: str) -> QualityConfig:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QualityConfigError(f"config: not valid JSON ({exc.msg})") from exc
        return cls.from_dict(data)
