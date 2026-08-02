from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
import yaml

from kokoroarc.schemas import SchemaRegistry


PACK = Path("characters/original/rin-aster")


def test_rin_pack_declares_three_locales_and_debugging_scenario() -> None:
    manifest = yaml.safe_load((PACK / "character.yaml").read_text(encoding="utf-8"))
    assert manifest["locale_files"] == {
        "zh-CN": "locales/zh-CN.yaml",
        "en-US": "locales/en-US.yaml",
        "ja-JP": "locales/ja-JP.yaml",
    }
    assert manifest["scenario_files"] == {"debugging": "scenarios/debugging.yaml"}


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("identity.yaml", True),
        ("locales/zh-CN.yaml", True),
        ("/outside.yaml", False),
        ("../escape.yaml", False),
        (r"C:\outside.yaml", False),
        (r"\outside.yaml", False),
        (r"locales\zh-CN.yaml", False),
    ],
)
def test_rin_pack_manifest_reference_path_examples(
    reference: str, expected: bool
) -> None:
    assert _is_relative_posix_manifest_reference(reference) is expected


EXPECTED_MANIFEST = {
    "schema_version": "1.0",
    "artifact_id": "original/rin-aster/source",
    "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
    "character_id": "rin-aster",
    "character_version": "1.0.0",
    "namespace": "original",
    "files": {
        "identity": "identity.yaml",
        "evidence": "evidence.yaml",
        "derived_profile": "derived-profile.yaml",
        "overrides": "overrides.yaml",
        "behavior": "behavior.yaml",
        "growth": "growth.yaml",
        "expressions": "expressions.yaml",
    },
    "locale_files": {
        "zh-CN": "locales/zh-CN.yaml",
        "en-US": "locales/en-US.yaml",
        "ja-JP": "locales/ja-JP.yaml",
    },
    "scenario_files": {"debugging": "scenarios/debugging.yaml"},
}

EXPECTED_COMPONENTS = {
    "identity": {
        "display_name": "Rin Aster",
        "declared_age": "adult",
        "role": "systems architect",
        "worldview": ["evidence_before_confidence", "promises_matter"],
        "non_negotiables": [
            "never_humiliate_a_learner",
            "never_fabricate_certainty",
        ],
    },
    "evidence": {"authored_original": True, "claims": []},
    "derived_profile": {
        "method_version": "original-authoring-v1",
        "traits": {
            "composure": 0.90,
            "warmth": 0.38,
            "directness": 0.82,
            "curiosity": 0.77,
            "patience": 0.79,
        },
    },
    "overrides": {"values": {}},
    "behavior": {
        "default_intensity": "balanced",
        "catchphrase_frequency": "very_low",
        "correction_style": "direct",
        "reassurance_style": "practical",
    },
    "growth": {
        "dimensions": ["familiarity", "trust", "collaboration", "tension"],
        "max_delta_per_event": 4.0,
        "repetition_window_turns": 3,
        "stages": {
            "unknown": {"enter_familiarity": 0},
            "acquainted": {"enter_familiarity": 10, "exit_familiarity": 7},
            "familiar": {
                "enter_familiarity": 30,
                "enter_trust": 20,
                "exit_familiarity": 25,
                "exit_trust": 15,
            },
            "trusted": {"enter_trust": 50, "max_tension": 35, "exit_trust": 42},
        },
    },
    "expressions": {
        "restrained_diagnosis": {
            "zh-CN": ["原因已经明确。"],
            "en-US": ["The cause is clear."],
            "ja-JP": ["原因は明確です。"],
        },
        "understated_encouragement": {
            "zh-CN": ["方向没错，还差最后一步。"],
            "en-US": ["The direction is sound; it is one step short."],
            "ja-JP": ["方向は合っています。あと一歩です。"],
        },
    },
}

EXPECTED_LOCALES = {
    "zh-CN": {
        "register": "contemporary_standard",
        "sentence_length": "short_to_medium",
        "technical_terms": "industry_standard",
        "addressing": {
            "unknown": None,
            "acquainted": None,
            "familiar": "Cyan",
            "trusted": "Cyan",
        },
    },
    "en-US": {
        "register": "modern_professional",
        "sentence_length": "short_to_medium",
        "technical_terms": "preserve_canonical_english",
        "addressing": {
            "unknown": None,
            "acquainted": None,
            "familiar": "Cyan",
            "trusted": "Cyan",
        },
    },
    "ja-JP": {
        "register": "relationship_aware",
        "sentence_length": "short_to_medium",
        "technical_terms": "preserve_canonical_english",
        "politeness": {
            "unknown": "teineigo",
            "acquainted": "teineigo",
            "familiar": "mixed_teineigo_plain",
            "trusted": "plain",
        },
        "addressing": {
            "unknown": "Cyanさん",
            "acquainted": "Cyanさん",
            "familiar": "Cyan",
            "trusted": "Cyan",
        },
    },
}

EXPECTED_SCENARIO = {
    "first_action": "inspect_evidence",
    "hypothesis_style": "ranked",
    "correction_style": "direct",
    "reassurance": "subtle",
    "intensity_cap": "balanced",
}

EXPECTED_FIXTURES = {
    "tests/multilingual.yaml": {
        "intent": "restrained_diagnosis",
        "semantic_key": "conclusion",
        "expected_locales": ["zh-CN", "en-US", "ja-JP"],
    },
    "tests/protected-spans.yaml": {
        "immutable_spans": ["go test -race ./...", "CacheEntry", "D:\\src\\app"],
        "required_warning_id": "concurrent-test-is-required",
    },
}

ALL_YAML_FILES = [
    "character.yaml",
    "identity.yaml",
    "evidence.yaml",
    "derived-profile.yaml",
    "overrides.yaml",
    "behavior.yaml",
    "growth.yaml",
    "expressions.yaml",
    "locales/zh-CN.yaml",
    "locales/en-US.yaml",
    "locales/ja-JP.yaml",
    "scenarios/debugging.yaml",
    *EXPECTED_FIXTURES,
]


def load_yaml(relative_path: str) -> dict:
    document = yaml.safe_load((PACK / relative_path).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _is_relative_posix_manifest_reference(reference: str) -> bool:
    posix_path = PurePosixPath(reference)
    windows_path = PureWindowsPath(reference)
    return (
        reference == posix_path.as_posix()
        and reference == windows_path.as_posix()
        and not posix_path.is_absolute()
        and not windows_path.drive
        and not windows_path.root
        and ".." not in posix_path.parts
    )


def test_rin_pack_yaml_files_are_mappings() -> None:
    for relative_path in ALL_YAML_FILES:
        load_yaml(relative_path)


def test_rin_pack_manifest_matches_source_layout() -> None:
    assert load_yaml("character.yaml") == EXPECTED_MANIFEST


def test_rin_pack_assembles_to_a_valid_character_source() -> None:
    manifest = load_yaml("character.yaml")
    source = {
        key: manifest[key]
        for key in (
            "schema_version",
            "artifact_id",
            "created_by",
            "character_id",
            "character_version",
            "namespace",
        )
    }
    source.update(
        {
            component: load_yaml(relative_path)
            for component, relative_path in manifest["files"].items()
        }
    )
    source["locales"] = {
        locale: load_yaml(relative_path)
        for locale, relative_path in manifest["locale_files"].items()
    }
    source["scenarios"] = {
        scenario: load_yaml(relative_path)
        for scenario, relative_path in manifest["scenario_files"].items()
    }

    SchemaRegistry(Path("schemas/v1")).validate("character-source", source)


def test_rin_pack_components_match_exact_payloads() -> None:
    manifest = load_yaml("character.yaml")
    actual = {
        component: load_yaml(relative_path)
        for component, relative_path in manifest["files"].items()
    }
    assert actual == EXPECTED_COMPONENTS


def test_rin_pack_locales_and_debugging_scenario_match_exact_payloads() -> None:
    manifest = load_yaml("character.yaml")
    locales = {
        locale: load_yaml(relative_path)
        for locale, relative_path in manifest["locale_files"].items()
    }
    scenarios = {
        scenario: load_yaml(relative_path)
        for scenario, relative_path in manifest["scenario_files"].items()
    }

    assert locales == EXPECTED_LOCALES
    assert scenarios == {"debugging": EXPECTED_SCENARIO}


def test_rin_pack_behavioral_fixtures_match_exact_payloads() -> None:
    assert {
        relative_path: load_yaml(relative_path)
        for relative_path in EXPECTED_FIXTURES
    } == EXPECTED_FIXTURES


def test_rin_pack_manifest_references_are_relative_posix_paths() -> None:
    manifest = load_yaml("character.yaml")
    references = [
        *manifest["files"].values(),
        *manifest["locale_files"].values(),
        *manifest["scenario_files"].values(),
    ]

    for reference in references:
        assert _is_relative_posix_manifest_reference(reference)
