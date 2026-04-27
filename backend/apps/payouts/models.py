from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum


class Merchant(models.Model):
    """
    Linked 1-to-1 with Django's built-in User model.
    User handles authentication (token, password).
    Merchant holds business-specific data.
    No balance field — ever.
    Balance is always computed from LedgerEvent.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='merchant'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def total_balance(self):
        """
        Raw sum of all ledger events.
        PAYOUT_INITIATED entries are already negative.
        This IS the available balance.
        """
        return LedgerEvent.objects.filter(
            merchant=self
        ).aggregate(
            total=Sum('amount_paise')
        )['total'] or 0

    @property
    def held_balance(self):
        """
        Funds in PENDING or PROCESSING payouts.
        Already reflected as negative entries in ledger.
        Informational only — shown on dashboard.
        Do NOT subtract from total — that would double count.
        """
        return Payout.objects.filter(
            merchant=self,
            status__in=[Payout.PENDING, Payout.PROCESSING]
        ).aggregate(
            held=Sum('amount_paise')
        )['held'] or 0

    @property
    def available_balance(self):
        """
        Available = total ledger sum.
        Ledger already accounts for everything:
          CREDIT_RECEIVED  → positive
          PAYOUT_INITIATED → negative (already deducted)
          PAYOUT_REVERSED  → positive (already returned)

        held_balance is for display only.
        Subtracting it here would double-count.
        """
        return self.total_balance

class BankAccount(models.Model):
    """
    A merchant can have multiple bank accounts.
    Payout request specifies which one to settle to.
    on_delete=PROTECT on payouts side means
    you cannot delete a bank account that has
    payouts attached — prevents silent data loss.
    """
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        related_name='bank_accounts'
    )
    account_number = models.CharField(max_length=50)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account_holder_name} - {self.account_number[-4:]}"


class LedgerEvent(models.Model):
    """
    Source of truth for all money movement.
    Append-only — nothing is ever updated or deleted.
    Enforced at DB level via Postgres trigger in migration 0003.

    Signed amount convention:
      CREDIT_RECEIVED  → positive  e.g. +150000
      PAYOUT_INITIATED → negative  e.g. -150000
      PAYOUT_REVERSED  → positive  e.g. +150000

    SUM(amount_paise) = balance directly.
    No conditional logic needed anywhere.
    """
    CREDIT_RECEIVED = 'CREDIT_RECEIVED'
    PAYOUT_INITIATED = 'PAYOUT_INITIATED'
    PAYOUT_REVERSED = 'PAYOUT_REVERSED'

    EVENT_TYPE_CHOICES = [
        (CREDIT_RECEIVED, 'Credit Received'),
        (PAYOUT_INITIATED, 'Payout Initiated'),
        (PAYOUT_REVERSED, 'Payout Reversed'),
    ]

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='ledger_events'
    )
    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES
    )
    amount_paise = models.BigIntegerField()
    # CREDIT_RECEIVED   → positive value
    # PAYOUT_INITIATED  → negative value (funds held)
    # PAYOUT_REVERSED   → positive value (funds returned)

    payout = models.ForeignKey(
        'Payout',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='ledger_events'
    )
    # null     → seeded credit, no payout associated
    # not null → this event was born from a payout

    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant', 'created_at']),
        ]

    def __str__(self):
        return (
            f"{self.event_type} | "
            f"{self.amount_paise} paise | "
            f"{self.merchant.name}"
        )


class Payout(models.Model):
    """
    A merchant's request to withdraw funds to their bank.

    State machine — enforced in transition() method.
    Legal paths:
      PENDING → PROCESSING → COMPLETED
      PENDING → PROCESSING → FAILED

    Terminal states: COMPLETED, FAILED
    Nothing moves out of a terminal state. Ever.
    VALID_TRANSITIONS enforces this — terminal states
    map to empty lists, so any transition raises ValueError.
    """
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PROCESSING, 'Processing'),
        (COMPLETED, 'Completed'),
        (FAILED, 'Failed'),
    ]

    VALID_TRANSITIONS = {
        PENDING:    [PROCESSING],
        PROCESSING: [COMPLETED, FAILED],
        COMPLETED:  [],  # terminal — no exit
        FAILED:     [],  # terminal — no exit
    }

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='payouts'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name='payouts'
    )
    amount_paise = models.BigIntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING
    )
    attempts = models.IntegerField(default=0)
    # How many times Celery has attempted this payout.
    # Max 3 → then FAILED + funds reversed.

    idempotency_key = models.ForeignKey(
        'IdempotencyKey',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payouts'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['status', 'updated_at']),
            # Second index is for stuck payout detection:
            # WHERE status='PROCESSING' AND updated_at < now-30s
        ]

    def __str__(self):
        return f"Payout {self.id} | {self.merchant.name} | {self.status}"

    def transition(self, new_status):
        """
        The ONLY way to change payout status.
        Raises ValueError on any illegal transition.

        EXPLAINER Q4 answer lives here:
        failed-to-completed is blocked because
        VALID_TRANSITIONS[FAILED] = []
        new_status not in [] → always raises ValueError.

        Same for completed-to-anything.
        No special case needed — the data structure
        handles it automatically.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, [])

        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {self.status} → {new_status}. "
                f"Allowed from '{self.status}': {allowed}"
            )

        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])


class IdempotencyKey(models.Model):
    """
    Every unique (merchant, key) pair we have ever seen.
    Prevents duplicate payout creation on retried requests.

    Write-first pattern:
      1. INSERT with status=IN_PROGRESS  ← before processing
      2. Process the payout
      3. UPDATE to DONE + store response

    Simultaneous duplicate requests:
      - unique_together means only one INSERT wins
      - Loser gets IntegrityError → caught → 409 returned

    Key expiry:
      Keys older than 24 hours are treated as new.
      Checked via created_at in the service layer.
    """
    IN_PROGRESS = 'IN_PROGRESS'
    DONE = 'DONE'

    STATUS_CHOICES = [
        (IN_PROGRESS, 'In Progress'),
        (DONE, 'Done'),
    ]

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        related_name='idempotency_keys'
    )
    key = models.UUIDField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=IN_PROGRESS
    )
    response_body = models.JSONField(null=True, blank=True)
    response_status_code = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('merchant', 'key')]
        # DB-level guarantee — not application-level hope.
        # Even two simultaneous requests: only one wins.

    def __str__(self):
        return f"{self.merchant.name} | {self.key} | {self.status}"
