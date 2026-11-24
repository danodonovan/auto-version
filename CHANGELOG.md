# Changelog

<!--next-version-placeholder-->

## v0.2.1 (2026-11-24)
### Fix
* commit only the release's own files, not the whole index (#9) ([`924d0f8`](https://github.com/danodonovan/auto-version/commit/924d0f81c6e1bb5ad2edad32381123bd0efa11a3))
* catch build-command leaks before the first push (#10) ([`4f3e3db`](https://github.com/danodonovan/auto-version/commit/4f3e3db5a03fc13050421cd670dc3b312f3018c7))
### Other
* add has_commits() and drop the stderr-matched unborn-HEAD check (#8) ([`f6b1fdf`](https://github.com/danodonovan/auto-version/commit/f6b1fdfe8213e60d11a77524b580a7af0210d4ba))
* have auto-version release itself with release --push (#11) ([`2964856`](https://github.com/danodonovan/auto-version/commit/29648561abb575b23e6a2c3a749c8763b093a0d0))


## v0.2.0 (2026-09-16)
### Feature
* publish releases atomically with --push, recomputing on a rejected push (#2) ([`607ccd7`](https://github.com/danodonovan/auto-version/commit/607ccd789a1234210484fd49bb91f84b5f4ff531))


## v0.1.0 (2026-06-23)
### Feature
* initial implementation of auto-version ([`32f1c60`](https://github.com/danodonovan/auto-version/commit/32f1c601a845e120b44c7d4f88cea16432705dcf))
* add show-version command and fix semantic version sorting ([`b763565`](https://github.com/danodonovan/auto-version/commit/b76356506ab1a6d41414d8a189ded79b232eff64))
* add PEP 440 pre-release support ([`4303a84`](https://github.com/danodonovan/auto-version/commit/4303a84bdf045e9ea6f9ae51f14e67782a75dfe3))
### Fix
* address code review findings ([`7bfe83f`](https://github.com/danodonovan/auto-version/commit/7bfe83f59acb032cc2e2dfe2616cd5fc3238db70))
### Documentation
* add CLAUDE.md ([`c654fec`](https://github.com/danodonovan/auto-version/commit/c654fec4e3aba2041c275842c3405336252fa0d0))
### Other
* Merge pull request #1 from danodonovan/DOD-974-auto-version-beta-releases ([`c056177`](https://github.com/danodonovan/auto-version/commit/c056177d5e958736cd58ffc356174dd7682de535))

