# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-10-28

### Added
- Redaction preview request and response models, including the exact approved request on the response, staff cover regions, free labels and justified whitelist values.
- `RunConfig.redaction_preview_id`, so a run can use an approved redaction.

## [0.1.1] - 2026-10-23

### Added
- Decision image, bounded hosted-job, customer-scope and tool-authorization contracts.
- Optional `permissions` and `destructive` tool safety labels, and the `decision_run` run kind.

### Fixed
- Include canonical JSON schemas, taxonomy and projections in installed wheels; schema loaders retain the canonical checkout data during source development.
- PII whitelist patterns that match an empty or single-character letter, digit or punctuation probe are refused. Narrow these patterns before converting SDK messages to contracts.
- Customer `user_id` values are limited to 256 characters and refuse control/format characters or surrounding whitespace. The `sdk-user` and whitespace-only cases continue to disable private memory.

## [0.1.0] - 2026-09-28

First public release, published for the maivn 2.0.0 SDK.

### Added
- The canonical schema contracts of mAIvn Platform v2 as pydantic models and JSON schemas, for Python 3.10 and later.
