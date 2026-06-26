The changelog format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

This project uses [Semantic Versioning](https://semver.org/) - MAJOR.MINOR.PATCH

# Changelog

## 0.1.1 (2026-06-26)


### Fixed

- `ldap.managed` now correctly handles `replace:` directives against OpenLDAP `cn=config` attributes (e.g. `olcSyncRepl`). User-supplied attribute names are matched case-insensitively against the server's canonical case, an opportunistic `{N}` X-ORDERED prefix normalization makes the state idempotent on those attributes, and the backend emits an atomic `MOD_REPLACE` for `replace:`-directed attributes instead of routing through an add/delete diff. References saltstack/salt#54444, saltstack/salt#33786, saltstack/salt#68626. [#9](https://github.com/salt-extensions/saltext-ldap/issues/9)

## 0.1.0 (2026-05-18)


### Added

- Update saltext-ldap to latest 3006.x code

## 0.0.3 (2024-09-10)

No significant changes.

## 0.0.2 (2024-09-10)

Initial release of `saltext-ldap`.
