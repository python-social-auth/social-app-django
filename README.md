# Compliant Social App Django

This is a Google compliant fork of the [Django](https://www.djangoproject.com/) component of the
[python-social-auth ecosystem](https://github.com/python-social-auth/social-core),
it implements the needed functionality to integrate
[social-auth-core](https://github.com/python-social-auth/social-core)
in a Django based project.

## Python Social Auth - Django

Python Social Auth is an easy to setup social authentication/registration
mechanism with support for several frameworks and auth providers.

## Django version

This project will focus on the currently supported Django releases as
stated on the [Django Project Supported Versions table](https://www.djangoproject.com/download/#supported-versions).

Backward compatibility with unsupported versions won't be enforced.

## Documentation

Compliant Social App Django provides three key features required to comply with Google's standards for applications that
ask for restricted scopes such as the ability to read gmail inboxes:

1. Storing the access and refresh tokens encrypted in the database.
2. The encryption of those tokens being backed by KMS.
3. Audit logs that register the access to and revocation of those same tokens.

An Audit Logger object must be provided to the app, and must inherit from the abstract base audit logger provided. We
also provide an alternative Google backend that uses the audit logger.

KMS must be set up independently, and you must specify a KMS_FIELD_KEY in settings; typically the alias of your KMS key.

If moving to this package from the main social-app-django package the db migrations will also handle the migration of
tokens, with encryption, into their appropriate fields.

Core project documentation is available at http://python-social-auth.readthedocs.org/.

## Setup

```shell
$ pip install compliant-social-app-django
```

## Versioning

This project follows [Semantic Versioning 2.0.0](http://semver.org/spec/v2.0.0.html).

This fork's versioning will match the major version of the original package version upon which it is based

## License

This project follows the BSD license. See the [LICENSE](LICENSE) for details.
