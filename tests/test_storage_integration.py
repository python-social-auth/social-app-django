"""Integration tests for storage layer to catch breaking changes in social-core API

These tests are designed to catch breaking changes in the social-core storage API that could
go unnoticed without integration testing. The issue that prompted these tests was:

https://github.com/python-social-auth/social-core/pull/986 introduced a breaking change
in the OpenID storage API (specifically in get_association method) that went unnoticed
into release. The error manifested as:

    NotImplementedError: Implement in subclass
    File "social_core/storage.py", line 256, in get_association
        raise NotImplementedError("Implement in subclass")

The breaking change happened when:
1. social-core's OpenIdStore.getAssociation() calls self.assoc.oids()
2. AssociationMixin.oids() calls cls.get(**kwargs)
3. If get() is not properly implemented in the Django storage layer, it raises NotImplementedError

These integration tests ensure that:
- DjangoAssociationMixin.get() works correctly and returns a QuerySet
- DjangoAssociationMixin.oids() properly calls get() and converts results to OpenIdAssociation objects
- OpenIdStore.getAssociation() can successfully retrieve associations through the full call stack
- All OpenID association and nonce storage operations work end-to-end
"""

import time
from unittest import mock

from django.test import TestCase
from social_core.store import OpenIdStore
from social_core.strategy import BaseStrategy

from social_django.models import Association, DjangoStorage, Nonce


class TestStorageIntegration(TestCase):
    """Test integration between DjangoStorage and social-core's OpenIdStore"""

    def setUp(self):
        # Create a mock strategy with DjangoStorage
        self.strategy = mock.Mock(spec=BaseStrategy)
        self.strategy.storage = DjangoStorage
        self.store = OpenIdStore(self.strategy)

    def test_openid_store_association_workflow(self):
        """Test the full OpenID association workflow through OpenIdStore"""
        # Create a mock OpenID association (using string handle as in real openid library)
        mock_association = mock.Mock()
        mock_association.handle = "test_handle"
        mock_association.secret = b"test_secret"
        mock_association.issued = int(time.time())
        mock_association.lifetime = 3600
        mock_association.assoc_type = "HMAC-SHA1"

        server_url = "https://example.com/openid"

        # Test storeAssociation
        self.store.storeAssociation(server_url, mock_association)

        # Verify association was stored
        self.assertEqual(Association.objects.count(), 1)
        stored = Association.objects.first()
        self.assertEqual(stored.server_url, server_url)
        self.assertEqual(stored.handle, "test_handle")

        # Test getAssociation - this is the critical method that was breaking
        retrieved = self.store.getAssociation(server_url)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.handle, "test_handle")

        # Test getAssociation with handle
        retrieved_with_handle = self.store.getAssociation(server_url, "test_handle")
        self.assertIsNotNone(retrieved_with_handle)
        self.assertEqual(retrieved_with_handle.handle, "test_handle")

        # Test removeAssociation
        self.store.removeAssociation(server_url, "test_handle")
        self.assertEqual(Association.objects.count(), 0)

        # Test getAssociation returns None after removal
        self.assertIsNone(self.store.getAssociation(server_url))

    def test_openid_store_association_expiration(self):
        """Test that expired associations are handled correctly"""
        # Create an expired association
        mock_association = mock.Mock()
        mock_association.handle = "expired_handle"
        mock_association.secret = b"test_secret"
        mock_association.issued = int(time.time()) - 7200  # 2 hours ago
        mock_association.lifetime = 3600  # 1 hour lifetime, so expired
        mock_association.assoc_type = "HMAC-SHA1"

        server_url = "https://example.com/openid"

        self.store.storeAssociation(server_url, mock_association)
        self.assertEqual(Association.objects.count(), 1)

        # getAssociation should return None for expired associations and clean them up
        retrieved = self.store.getAssociation(server_url)
        self.assertIsNone(retrieved)
        self.assertEqual(Association.objects.count(), 0)

    def test_openid_store_multiple_associations(self):
        """Test handling multiple associations for the same server"""
        server_url = "https://example.com/openid"
        current_time = int(time.time())

        # Store multiple associations with different handles
        for i in range(3):
            mock_association = mock.Mock()
            mock_association.handle = f"handle_{i}"
            mock_association.secret = b"test_secret"
            mock_association.issued = current_time + i
            mock_association.lifetime = 3600
            mock_association.assoc_type = "HMAC-SHA1"

            self.store.storeAssociation(server_url, mock_association)

        self.assertEqual(Association.objects.count(), 3)

        # getAssociation should return the most recent one
        retrieved = self.store.getAssociation(server_url)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.handle, "handle_2")

        # Get specific association by handle
        retrieved_specific = self.store.getAssociation(server_url, "handle_1")
        self.assertIsNotNone(retrieved_specific)
        self.assertEqual(retrieved_specific.handle, "handle_1")

    def test_openid_store_nonce_workflow(self):
        """Test the OpenID nonce workflow through OpenIdStore"""
        server_url = "https://example.com/openid"
        timestamp = int(time.time())
        salt = "test_salt"

        # First use should succeed
        self.assertTrue(self.store.useNonce(server_url, timestamp, salt))
        self.assertEqual(Nonce.objects.count(), 1)

        # Second use with same parameters should fail (nonce already used)
        self.assertFalse(self.store.useNonce(server_url, timestamp, salt))
        self.assertEqual(Nonce.objects.count(), 1)

        # Different salt should succeed
        self.assertTrue(self.store.useNonce(server_url, timestamp, "different_salt"))
        self.assertEqual(Nonce.objects.count(), 2)

    def test_openid_store_nonce_timestamp_skew(self):
        """Test that nonces with excessive timestamp skew are rejected"""
        server_url = "https://example.com/openid"
        current_time = int(time.time())
        old_timestamp = current_time - 7 * 60 * 60  # 7 hours ago (exceeds 6 hour skew)
        salt = "test_salt"

        # Old timestamp should be rejected
        self.assertFalse(self.store.useNonce(server_url, old_timestamp, salt))
        self.assertEqual(Nonce.objects.count(), 0)


class TestAssociationMixinIntegration(TestCase):
    """Test DjangoAssociationMixin methods used by social-core"""

    def test_oids_method(self):
        """Test the oids method that is called by OpenIdStore.getAssociation"""
        # Create test associations
        mock_assoc1 = mock.Mock(handle="handle1", secret=b"secret1", issued=1000, lifetime=3600, assoc_type="HMAC-SHA1")
        mock_assoc2 = mock.Mock(handle="handle2", secret=b"secret2", issued=2000, lifetime=3600, assoc_type="HMAC-SHA1")

        server_url = "https://example.com/openid"
        Association.store(server_url, mock_assoc1)
        Association.store(server_url, mock_assoc2)

        # Test oids() method - returns sorted list of (id, association) tuples
        oids_result = list(Association.oids(server_url))
        self.assertEqual(len(oids_result), 2)

        # Should be sorted by issued timestamp (most recent first)
        self.assertEqual(oids_result[0][1].handle, "handle2")
        self.assertEqual(oids_result[1][1].handle, "handle1")

    def test_oids_method_with_handle(self):
        """Test oids method with specific handle filter"""
        mock_assoc1 = mock.Mock(handle="handle1", secret=b"secret1", issued=1000, lifetime=3600, assoc_type="HMAC-SHA1")
        mock_assoc2 = mock.Mock(handle="handle2", secret=b"secret2", issued=2000, lifetime=3600, assoc_type="HMAC-SHA1")

        server_url = "https://example.com/openid"
        Association.store(server_url, mock_assoc1)
        Association.store(server_url, mock_assoc2)

        # Test oids() with handle filter
        oids_result = list(Association.oids(server_url, "handle1"))
        self.assertEqual(len(oids_result), 1)
        self.assertEqual(oids_result[0][1].handle, "handle1")

    def test_get_method(self):
        """Test the get method that is called by oids"""
        mock_assoc = mock.Mock(
            handle="test_handle", secret=b"secret", issued=1000, lifetime=3600, assoc_type="HMAC-SHA1"
        )

        server_url = "https://example.com/openid"
        Association.store(server_url, mock_assoc)

        # Test get() method returns QuerySet
        result = Association.get(server_url=server_url)
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().handle, "test_handle")

        # Test get() with handle filter
        result_with_handle = Association.get(server_url=server_url, handle="test_handle")
        self.assertEqual(result_with_handle.count(), 1)

        # Test get() with non-existent handle
        result_none = Association.get(server_url=server_url, handle="nonexistent")
        self.assertEqual(result_none.count(), 0)


class TestNonceMixinIntegration(TestCase):
    """Test DjangoNonceMixin methods used by social-core"""

    def test_use_method(self):
        """Test the use method that is called by OpenIdStore.useNonce"""
        server_url = "https://example.com/openid"
        timestamp = 1234567890
        salt = "test_salt"

        # First use should return True (created)
        self.assertTrue(Nonce.use(server_url, timestamp, salt))
        self.assertEqual(Nonce.objects.count(), 1)

        # Second use should return False (already exists)
        self.assertFalse(Nonce.use(server_url, timestamp, salt))
        self.assertEqual(Nonce.objects.count(), 1)

    def test_get_method(self):
        """Test the get method for retrieving nonces"""
        server_url = "https://example.com/openid"
        timestamp = 1234567890
        salt = "test_salt"

        Nonce.use(server_url, timestamp, salt)

        # Test get() method
        nonce = Nonce.get(server_url, salt)
        self.assertIsNotNone(nonce)
        self.assertEqual(nonce.server_url, server_url)
        self.assertEqual(nonce.salt, salt)

    def test_delete_method(self):
        """Test the delete method for nonces"""
        server_url = "https://example.com/openid"
        timestamp = 1234567890
        salt = "test_salt"

        Nonce.use(server_url, timestamp, salt)
        nonce = Nonce.get(server_url, salt)

        # Test delete() method
        Nonce.delete(nonce)
        self.assertEqual(Nonce.objects.count(), 0)
