import threading
import time
import uuid
from unittest.mock import patch
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from django.db import connections, transaction
from rest_framework.authtoken.models import Token

from apps.payouts.models import Merchant, BankAccount, LedgerEvent, Payout
from apps.payouts.services import create_payout, create_idempotency_key
from apps.payouts.exceptions import InsufficientBalance


class ConcurrencyTest(TransactionTestCase):
    """
    Tests that SELECT FOR UPDATE correctly serializes
    concurrent payout requests.

    IMPORTANT — why we use Barrier + sleep:
    Without forced synchronization, threads are so fast
    that Thread A completes entirely before Thread B starts.
    That tests sequential execution, not concurrency.

    The Barrier forces both threads to reach the lock point
    simultaneously. The sleep holds Thread A's transaction
    open so Thread B genuinely blocks on the lock.

    This was caught during development when naive threading
    tests passed for the wrong reason — threads never
    actually competed. See EXPLAINER.md Q5.
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
            amount_paise=10000,
            description='Test credit',
        )

    def _make_idempotency_key(self):
        return create_idempotency_key(
            self.merchant,
            uuid.uuid4()
        )

    def test_concurrent_payouts_cannot_overdraw(self):
        """
        Two simultaneous 6000 paise requests on 10000 paise balance.

        Uses threading.Barrier to guarantee both threads
        attempt the lock at exactly the same moment.

        Uses time.sleep inside the transaction to hold
        Thread A's lock open long enough for Thread B
        to genuinely block on it.

        Expected:
          Thread A: acquires lock, sleeps, commits → success
          Thread B: blocks on lock, unblocks, sees
                    updated balance → InsufficientBalance

        Proves SELECT FOR UPDATE is the correct primitive —
        not Python-level locking, not application-level checks.
        """
        results = [None, None]
        errors = [None, None]
        timings = [None, None]

        # Barrier ensures both threads reach the
        # create_payout call before either proceeds
        barrier = threading.Barrier(2, timeout=10)

        merchant_id = self.merchant.id
        bank_account_id = self.bank_account.id

        def attempt_payout(index):
            try:
                # Re-fetch in this thread's connection
                merchant = Merchant.objects.get(id=merchant_id)

                idem_key = create_idempotency_key(
                    merchant,
                    uuid.uuid4()
                )

                # Both threads arrive here before either proceeds
                # This guarantees genuine concurrency
                barrier.wait()

                start = time.time()

                create_payout(
                    merchant=merchant,
                    amount_paise=6000,
                    bank_account_id=bank_account_id,
                    idempotency_key=idem_key,
                )

                timings[index] = time.time() - start
                results[index] = 'success'

            except InsufficientBalance:
                timings[index] = time.time() - start
                results[index] = 'insufficient_balance'

            except Exception as e:
                results[index] = f'error: {e}'

            finally:
                connections.close_all()

        # Patch transaction.atomic to inject a sleep
        # INSIDE Thread A's transaction while lock is held
        # This keeps the transaction open long enough for
        # Thread B to genuinely block on SELECT FOR UPDATE
        original_atomic = transaction.atomic
        call_count = [0]
        sleep_done = [False]

        def slow_atomic(*args, **kwargs):
            ctx = original_atomic(*args, **kwargs)
            if not sleep_done[0]:
                sleep_done[0] = True

                class SlowContext:
                    def __enter__(self_ctx):
                        ctx.__enter__()
                        # Sleep INSIDE the transaction
                        # Lock is held during this sleep
                        time.sleep(1)
                        return self_ctx

                    def __exit__(self_ctx, *exc):
                        return ctx.__exit__(*exc)

                return SlowContext()
            return ctx

        thread1 = threading.Thread(
            target=attempt_payout,
            args=(0,)
        )
        thread2 = threading.Thread(
            target=attempt_payout,
            args=(1,)
        )

        with patch('django.db.transaction.atomic', slow_atomic):
            thread1.start()
            thread2.start()
            thread1.join(timeout=15)
            thread2.join(timeout=15)

        outcomes = sorted(results)

        self.assertEqual(
            outcomes,
            ['insufficient_balance', 'success'],
            f'Expected one success and one insufficient_balance '
            f'but got: {results}. '
            f'SELECT FOR UPDATE serialization failed.'
        )

        payout_count = Payout.objects.filter(
            merchant=self.merchant
        ).count()
        self.assertEqual(
            payout_count,
            1,
            f'Expected 1 payout but found {payout_count}. '
            f'Duplicate created — race condition exists.'
        )

        self.merchant.refresh_from_db()
        available = self.merchant.available_balance

        self.assertGreaterEqual(
            available,
            0,
            f'Balance went negative: {available} paise.'
        )

        self.assertEqual(
            available,
            4000,
            f'Expected 4000 available but got {available}'
        )

    def test_sequential_overdraft_prevented(self):
        """
        Control test — sequential version of the same scenario.
        First 6000 succeeds, second 6000 fails.
        Proves balance check logic is correct independent
        of the concurrency mechanism.
        """
        create_payout(
            merchant=self.merchant,
            amount_paise=6000,
            bank_account_id=self.bank_account.id,
            idempotency_key=self._make_idempotency_key(),
        )

        with self.assertRaises(InsufficientBalance):
            create_payout(
                merchant=self.merchant,
                amount_paise=6000,
                bank_account_id=self.bank_account.id,
                idempotency_key=self._make_idempotency_key(),
            )

        self.assertEqual(
            Payout.objects.filter(merchant=self.merchant).count(),
            1
        )
        self.assertEqual(self.merchant.available_balance, 4000)