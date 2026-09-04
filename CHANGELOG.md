# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-04

First versioned release of the standalone Agent Skill Suite.

### Added

- Four installable Agent Skills: `using-kokorox`, `authoring-character-packs`,
  `researching-characters`, and `testing-character-packs`.
- The `kokorox` CLI covering the pack lifecycle (compile, validate, test,
  soft-eval, promote, publication-check, export, compatibility, migrate,
  install, list, remove), research, sessions, runtime render planning, scoped
  configuration, consent, state, and memory references.
- Per-agent interface profiles for ten hosts (`openai`, `claude`, `codex`,
  `cursor`, `gemini`, `copilot`, `kimi`, `deepseek`, `qwen`, `generic`), shipped
  with every Skill so a host can present the suite in its own idiom.
- Suite installation into the vendor-neutral `.agents/skills` root, a
  repository scope, or any explicit `--skills-root`.
- Open, shape-validated locales: any well-formed BCP-47 language tag is
  accepted. Task content follows the user's language; character expression
  falls back to a locale the pack actually authors; protected channels
  (commands, file paths, exact errors, code identifiers) are always preserved.
- Coverage measurement with a minimum threshold, and a `py.typed` marker so
  consumers receive the package's type information.
- MIT license.

### Changed

- The product is named KokoroX and is delivered as a standalone Agent Skill
  Suite; Lumora integration is not pursued.
- Locales are no longer restricted to `zh-CN`, `en-US`, and `ja-JP`. Those
  remain the repository's reference profiles, not a required set.

### Fixed

- An installed `kokorox` could not find its Skill sources: the resolver only
  searched beside the package in `site-packages`, while a wheel places the
  Skill data files under the environment prefix. `pip install` followed by
  `kokorox suite install` previously failed with `SKILL_SUITE_SOURCE_INVALID`.

[Unreleased]: https://github.com/HAYASAKA7/KokoroX/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/HAYASAKA7/KokoroX/releases/tag/v0.1.0
