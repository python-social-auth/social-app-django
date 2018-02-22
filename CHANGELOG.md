# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased](https://github.com/python-social-auth/social-app-django/commits/master)

### Changed
- Reduce log level of exceptions to `INFO` if messages app is installed

## [2.1.0](https://github.com/python-social-auth/social-app-django/releases/tag/2.1.0) - 2017-12-22

### Changed
- Use Django `urlquote` since it handles unicode
- Remove version check in favor of import error catch
- Remove call to deprecated method `_get_val_from_obj()`

## [2.0.0](https://github.com/python-social-auth/social-app-django/releases/tag/2.0.0) - 2017-10-28

### Changed
- Better default when checking if the middleware should raise the exception
- Update `JSONField` default value to `dict` callable
- Updated `authenticate()` parameters cleanup to avoid double arguments errors
- Fix imports to bring Django 2.0 support
- Admin friendly label
- Old Django versions (1.8 and below) compatibility dropped
- Python 3.6 and Django 2.0 tests
- Management command to clean stale data (partial sessions and codes)

### Added
- Added `JSONField` support PostgreSQL builtin option if configured
- Added strategy / models / views tests
- Added timestamps to Partial and Code models

## [1.2.0](https://github.com/python-social-auth/social-app-django/releases/tag/1.2.0) - 2017-05-06

### Added
- Check for a `MAX_SESSION_LENGTH` setting when logging in and setting session expiry.

### Changed
- Addded `on_cascade` clauses to migrations.
- Restrict association URL to just integer ids

## [1.1.0](https://github.com/python-social-auth/social-app-django/releases/tag/1.1.0) - 2017-02-10

### Added
- Authenticate cleanup method override to discard request parameter
  getting passed starting from Django 1.11

## [1.0.1](https://github.com/python-social-auth/social-app-django/releases/tag/1.0.1) - 2017-01-29

### Changed
- Remove migration replacement to nonexistent reference
- Ensure atomic transaction if active

## [1.0.0](https://github.com/python-social-auth/social-app-django/releases/tag/1.0.0) - 2017-01-22

### Added
- Partial pipeline DB storage implementation
- Explicit app_label definition in model classes

### Changed
- Monkey patch BaseAuth to load the current strategy to workaround django load_backend() call
- Remove usage of set/get current strategy methods
- Remove usage of `social_auth` related name since it should be consider a simple helper.

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

### Changed
- Split from the monolitic [python-social-auth](https://github.com/omab/python-social-auth)
  codebase
