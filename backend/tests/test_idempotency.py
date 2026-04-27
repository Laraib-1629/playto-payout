from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta

from apps.payouts.models import (
    Merchant,
    BankAccount,
    LedgerEvent,
    Payout,
    IdempotencyKey,
)


class IdempotencyTest(TestCase):
    """
    Tests that duplicate requests with the same
    Idempotency-Key return identical responses
    without creating duplicate payouts.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='test_merchant',
            password='testpass123',
        )
        self.token = Token.objects.create(user=self.user)
        self.merchant = Merchant.objects.create(
            user=self.user,
            name='Test Merchant',
            email='test@merchant.com',
        )
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number='1234567890',
            ifsc_code='HDFC0001234',
            account_holder_name='Test User',
        )
        LedgerEvent.objects.create(
            merchant=self.merchant,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=100000,
            description='Test credit',
        )

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {self.token.key}'
        )
        self.idempotency_key = '550e8400-e29b-41d4-a716-446655440000'

    def _make_payout(self, key=None):
        return self.client.post(
            '/api/v1/payouts/',
            data={
                'amount_paise': 5000,
                'bank_account_id': self.bank_account.id,
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY=key or self.idempotency_key,
        )

    def test_same_key_returns_same_response(self):
        """
        First request creates payout and returns 201.
        Second request with same key returns identical
        201 response without creating a new payout.
        """
        response1 = self._make_payout()
        response2 = self._make_payout()

        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 201)

        self.assertEqual(
            response1.data['id'],
            response2.data['id'],
            'Second request returned different payout id'
        )
        self.assertEqual(
            response1.data['amount_paise'],
            response2.data['amount_paise'],
        )
        self.assertEqual(
            response1.data['status'],
            response2.data['status'],
        )

        payout_count = Payout.objects.filter(
            merchant=self.merchant
        ).count()
        self.assertEqual(
            payout_count,
            1,
            f'Expected 1 payout but found {payout_count}. '
            f'Idempotency failed — duplicate created.'
        )

    def test_different_keys_create_different_payouts(self):
        """
        Two requests with different keys should
        each create their own payout.
        """
        response1 = self._make_payout(
            key='550e8400-e29b-41d4-a716-446655440001'
        )
        response2 = self._make_payout(
            key='550e8400-e29b-41d4-a716-446655440002'
        )

        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 201)

        self.assertNotEqual(
            response1.data['id'],
            response2.data['id'],
        )

        payout_count = Payout.objects.filter(
            merchant=self.merchant
        ).count()
        self.assertEqual(payout_count, 2)

    def test_missing_idempotency_key_returns_400(self):
        """
        Request without Idempotency-Key header
        must be rejected with 400.
        """
        response = self.client.post(
            '/api/v1/payouts/',
            data={
                'amount_paise': 5000,
                'bank_account_id': self.bank_account.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['code'],
            'IDEMPOTENCY_KEY_MISSING'
        )

    def test_invalid_idempotency_key_returns_400(self):
        """
        Non-UUID idempotency key must be rejected with 400.
        """
        response = self.client.post(
            '/api/v1/payouts/',
            data={
                'amount_paise': 5000,
                'bank_account_id': self.bank_account.id,
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='not-a-valid-uuid',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['code'],
            'INVALID_IDEMPOTENCY_KEY'
        )

    def test_expired_key_creates_new_payout(self):
        """
        Keys older than 24 hours are treated as new.
        A request with an expired key should create
        a fresh payout, not return the old response.
        """
        response1 = self._make_payout()
        self.assertEqual(response1.status_code, 201)

        IdempotencyKey.objects.filter(
            merchant=self.merchant,
            key=self.idempotency_key,
        ).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        response2 = self._make_payout()
        self.assertEqual(response2.status_code, 201)

        self.assertNotEqual(
            response1.data['id'],
            response2.data['id'],
            'Expired key should have created a new payout'
        )