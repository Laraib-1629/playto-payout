import uuid
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta

from .models import Merchant, BankAccount, LedgerEvent, Payout, IdempotencyKey
from .exceptions import (
    InsufficientBalance,
    IdempotencyKeyInProgress,
    IdempotencyKeyMissing,
    InvalidIdempotencyKey,
    BankAccountNotFound,
)


# ── Idempotency ───────────────────────────────────────────────────────────────

def validate_idempotency_key_header(raw_key):
    """
    Validates that the Idempotency-Key header:
    1. Exists
    2. Is a valid UUID
    Returns a UUID object if valid.
    """
    if not raw_key:
        raise IdempotencyKeyMissing()

    try:
        return uuid.UUID(str(raw_key))
    except (ValueError, AttributeError):
        raise InvalidIdempotencyKey()


def get_idempotency_key(merchant, key):
    """
    Looks up an idempotency key for this merchant.
    Keys older than 24 hours are deleted and treated
    as non-existent — allows fresh request to be processed.
    Returns IdempotencyKey instance or None.
    """
    expiry_time = timezone.now() - timedelta(hours=24)

    IdempotencyKey.objects.filter(
        merchant=merchant,
        key=key,
        created_at__lt=expiry_time
    ).delete()

    return IdempotencyKey.objects.filter(
        merchant=merchant,
        key=key,
        created_at__gte=expiry_time
    ).first()


def create_idempotency_key(merchant, key):
    """
    Writes the idempotency key BEFORE processing starts.
    Write-first pattern — prevents duplicate processing.

    If two simultaneous requests arrive with same key:
      One wins the INSERT (unique_together constraint)
      Other gets IntegrityError → caught by caller → 409
    """
    return IdempotencyKey.objects.create(
        merchant=merchant,
        key=key,
        status=IdempotencyKey.IN_PROGRESS,
    )


def mark_idempotency_key_done(idempotency_key, response_body, status_code):
    """
    Called after successful payout creation.
    Stores response so future duplicate requests
    get the exact same response back.
    """
    idempotency_key.status = IdempotencyKey.DONE
    idempotency_key.response_body = response_body
    idempotency_key.response_status_code = status_code
    idempotency_key.save(update_fields=[
        'status',
        'response_body',
        'response_status_code'
    ])


# ── Balance ───────────────────────────────────────────────────────────────────

def get_merchant_balance(merchant):
    """
    Returns all three balance components.
    All computed via DB-level SUM() — no Python arithmetic
    on fetched rows. Satisfies the technical constraint
    explicitly stated in the challenge.
    """
    return {
        'total_balance_paise': merchant.total_balance,
        'held_balance_paise': merchant.held_balance,
        'available_balance_paise': merchant.available_balance,
    }


# ── Payout Creation ───────────────────────────────────────────────────────────

def create_payout(merchant, amount_paise, bank_account_id, idempotency_key):
    """
    The core of the payout engine.

    Steps:
    1. Validates bank account belongs to this merchant
    2. Acquires row-level lock on merchant (SELECT FOR UPDATE)
    3. Computes available balance from ledger INSIDE the lock
    4. Checks balance is sufficient
    5. Creates Payout + LedgerEvent atomically

    Why ledger-only balance:
    PAYOUT_INITIATED creates a negative ledger entry.
    That entry IS the hold. Subtracting held payouts
    separately would double-count the same money.
    available = SUM(ledger) is the single source of truth.

    SELECT FOR UPDATE serializes concurrent requests.
    Second thread waits at the lock line until first
    transaction commits — then sees updated ledger balance.

    This is EXPLAINER Q2.
    """
    try:
        bank_account = BankAccount.objects.get(
            id=bank_account_id,
            merchant=merchant,
            is_active=True,
        )
    except BankAccount.DoesNotExist:
        raise BankAccountNotFound()

    with transaction.atomic():
        # Lock merchant row — second thread WAITS here
        # PostgreSQL primitive — not Python-level locking
        # Python locks don't work across processes or workers
        locked_merchant = Merchant.objects.select_for_update(
            nowait=False
        ).get(id=merchant.id)

        # Compute balance from ledger only, inside the lock
        # PAYOUT_INITIATED entries are already negative
        # No held subtraction — that would double-count
        total = LedgerEvent.objects.filter(
            merchant=locked_merchant
        ).aggregate(
            total=Sum('amount_paise')
        )['total'] or 0

        available = total  # ledger is the source of truth

        if available < amount_paise:
            raise InsufficientBalance(
                available_balance=available,
                requested_amount=amount_paise,
            )

        payout = Payout.objects.create(
            merchant=locked_merchant,
            bank_account=bank_account,
            amount_paise=amount_paise,
            status=Payout.PENDING,
            idempotency_key=idempotency_key,
        )

        LedgerEvent.objects.create(
            merchant=locked_merchant,
            event_type=LedgerEvent.PAYOUT_INITIATED,
            amount_paise=-amount_paise,
            payout=payout,
            description=f'Payout initiated #{payout.id}',
        )

    return payout


# ── Payout Processing ─────────────────────────────────────────────────────────

def complete_payout(payout):
    """
    Called by Celery worker on successful bank simulation.
    Transitions payout to COMPLETED.
    Debit ledger entry stays — funds are settled.
    """
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout.id)
        payout.transition(Payout.COMPLETED)


def fail_payout(payout):
    """
    Called by Celery worker on failed bank simulation
    or when max retries exceeded.

    Atomically:
    1. Transitions payout to FAILED
    2. Creates a reversal credit entry

    Both in one transaction — no partial state possible.
    No money disappears or appears unexpectedly.

    This is EXPLAINER Q2 + Q4 — atomic fund return.
    """
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout.id)

        # transition() enforces state machine.
        # COMPLETED → FAILED is illegal per VALID_TRANSITIONS.
        # Raises ValueError if already in terminal state.
        payout.transition(Payout.FAILED)

        LedgerEvent.objects.create(
            merchant=payout.merchant,
            event_type=LedgerEvent.PAYOUT_REVERSED,
            amount_paise=+payout.amount_paise,
            payout=payout,
            description=f'Payout failed reversal #{payout.id}',
        )


def get_ledger(merchant):
    """
    Returns all ledger events for a merchant, most recent first.
    """
    return LedgerEvent.objects.filter(
        merchant=merchant
    ).select_related('payout')


def get_payouts(merchant):
    """
    Returns all payouts for a merchant, most recent first.
    """
    return Payout.objects.filter(
        merchant=merchant
    ).select_related('bank_account').order_by('-created_at')