# SLOP Documentation Map

Single index for every documentation file in this repo. New docs land here or
they don't ship.

## Onboarding (read first)
- README.md — project pitch, install one-liner, basic operation
- CONTRIBUTING.md — local setup, branch & PR norms
- INSTALL.md — quick-start install reference (root-level)
- docs/INSTALL.md — full install walkthrough
- docs/DOCKER_INSTALL.md — Docker-only install path
- CLAUDE.md — agent/contributor conventions

## Architecture & decisions
- docs/adr/ — Architecture Decision Records (one file each, numbered 0001–0017)
- docs/GLOSSARY.md — domain vocabulary

## Operations
- MIGRATION.md — version-to-version upgrade notes (root-level)
- docs/MIGRATION.md — version-to-version upgrade notes
- docs/observability.md — metrics, logs, dashboards
- docs/RELEASE_NOTES_v5_0_0.md — current release notes
- installer/DEPENDENCIES.md — dep policy + transitive notes
- installer/SUPPORTED_DISTROS.md — supported install targets

## Wave / project state
- .claude/waves/ — active wave prompt files
- CHANGELOG.md — release-tagged change history
- docs/BACKLOG.md — broader project work queue
- docs/ACCESS-REQUESTS.md — tracked install/upgrade/allow-list requests (queue file, processed by tools/process_access_requests.py per S-59; see ROBOT.md doctrine integration)
- docs/RULES-TO-TESTS-AUDIT.md — CLAUDE.md rules audited for testability (S-50 Stream C output, S-55 Stream B consumer)
- docs/SANCTIONED-CHANNELS.md — deny-rule registry: every deny maps to a sanctioned tool (tools/sanctioned/) OR a no-exceptions-period rationale (S-68-E)

## Catalog
- catalog/MANIFEST_SPEC.md — app manifest format
