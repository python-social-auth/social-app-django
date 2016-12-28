# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased](https://github.com/python-social-auth/social-app-django/commits/master)

## [0.1.0](https://github.com/python-social-auth/social-app-django/releases/tag/0.1.0) - 2016-12-28

### Added
- Let Django resolve URL when getting from settings (port of [#905](https://github.com/omab/python-social-auth/pull/905)
  by webjunkie)
- Add setting to fine-tune admin search fields (port of [#1035](https://github.com/omab/python-social-auth/pull/1035)
  by atugushev)

### Changed
- Fixed `REDIRECT_URL_VALUE` value to be quoted by default.
  Refs [#875](https://github.com/omab/python-social-auth/issues/875)
- Django strategy should respect X-Forwarded-Port (port of [#841](https://github.com/omab/python-social-auth/pull/841)
  by omarkhan)
- Fixed use of old private API (port of [#822](https://github.com/omab/python-social-auth/pull/822)
  by eranmarom)
- Add ON DELETE CASCADE for user fk (port of [#1015](https://github.com/omab/python-social-auth/pull/1015)
  by artofhuman)
- Avoid usage of SubfieldBase on 1.8 and 1.9 versions (port of [#1008](https://github.com/omab/python-social-auth/pull/1008)
  by tom-dalton-fanduel)

## [0.0.1](https://github.com/python-social-auth/social-app-django/releases/tag/0.0.1) - 2016-11-27

### Chaged
- Split from the monolitic [python-social-auth](https://github.com/omab/python-social-auth)
  codebase
