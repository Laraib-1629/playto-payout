# EXPLAINER.md

---

## Q1. The Ledger

**Balance calculation query:**

```python
LedgerEvent.objects.filter(
    merchant=locked_merchant
).aggregate(
    total=Sum('amount_paise')
)['total'] or 0
```

**Why this model:**

Every money movement is stored as a signed integer in `LedgerEvent.amount_paise`:

- `CREDIT_RECEIVED` → positive value (e.g. +150000)
- `PAYOUT_INITIATED` → negative value (e.g. -150000)
- `PAYOUT_REVERSED` → positive value (e.g. +150000)

This means `SUM(amount_paise)` directly equals the available balance. No conditional logic, no Python arithmetic on fetched rows.

Balance is never stored as a field on `Merchant`. Storing it separately would create two sources of truth that can drift apart — a bug in any code path and they diverge. The ledger IS the balance.

We went further than the constraint required: two Postgres triggers enforce integrity at the DB level.

1. **Immutability trigger** — `BEFORE UPDATE OR DELETE ON payouts_ledgerevent` raises an exception. Ledger rows cannot be modified or deleted even by application bugs.

2. **Balance check trigger** — `BEFORE INSERT ON payouts_ledgerevent` rejects any debit that would cause negative balance. This is a third layer of overdraft protection after the Python check and the SELECT FOR UPDATE lock.

---

## Q2. The Lock

**Exact code that prevents concurrent overdraft:**

```python
with transaction.atomic():
    # Row-level lock — second request WAITS here
    locked_merchant = Merchant.objects.select_for_update(
        nowait=False
    ).get(id=merchant.id)

    # Balance computed INSIDE the lock
    # This is critical — computing before acquiring the lock
    # would reintroduce the race condition
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

    payout = Payout.objects.create(...)

    LedgerEvent.objects.create(
        amount_paise=-amount_paise,  # negative = debit
        ...
    )
```

**DB primitive it relies on:**

`SELECT FOR UPDATE` — a PostgreSQL row-level lock. When Thread A acquires the lock, Thread B's `select_for_update()` call blocks at the database level until Thread A's transaction commits. Thread B then wakes up with fresh data, sees the already-reduced balance, and fails the balance check cleanly with a 422.

This is NOT Python-level locking (`threading.Lock`). Python locks only work within a single process. `SELECT FOR UPDATE` works across multiple server processes and Celery workers because it lives in the database.

---

## Q3. The Idempotency

**How the system knows it has seen a key before:**

Every `(merchant_id, idempotency_key)` pair is stored in the `IdempotencyKey` table with a `unique_together` constraint at the DB level. On each request:

1. Extract and validate `Idempotency-Key` UUID header
2. Delete any expired keys (older than 24 hours)
3. Check for existing non-expired record
4. If `DONE` → return stored `response_body` and `response_status_code` directly
5. If `IN_PROGRESS` → return 409 Conflict
6. If not found → INSERT with `status=IN_PROGRESS` **before** processing

**What happens if the first request is in flight when the second arrives:**

The write-first pattern handles this. The key is written as `IN_PROGRESS` before any processing begins. If a second request arrives:

- Finds `IN_PROGRESS` → returns 409 Conflict immediately

If two requests arrive simultaneously before either has written the key:

- Both attempt `INSERT` into `IdempotencyKey`
- `unique_together` constraint means only one INSERT succeeds
- The other gets `IntegrityError` which is caught and returns 409

Keys expire after 24 hours — expired keys are deleted before lookup so the `unique_together` constraint does not block fresh requests using the same key value.

---

## Q4. The State Machine

**Where failed-to-completed is blocked:**

In `apps/payouts/models.py`, the `Payout.transition()` method:

```python
VALID_TRANSITIONS = {
    PENDING:    [PROCESSING],
    PROCESSING: [COMPLETED, FAILED],
    COMPLETED:  [],   # terminal — no exit
    FAILED:     [],   # terminal — no exit
}

def transition(self, new_status):
    allowed = self.VALID_TRANSITIONS.get(self.status, [])

    if new_status not in allowed:
        raise ValueError(
            f"Illegal transition: {self.status} → {new_status}. "
            f"Allowed from '{self.status}': {allowed}"
        )

    self.status = new_status
    self.save(update_fields=['status', 'updated_at'])
```

`VALID_TRANSITIONS[FAILED] = []` — an empty list. `new_status not in []` is always `True`. So any transition out of `FAILED` always raises `ValueError`.

Same for `COMPLETED`. No special case needed — the data structure handles it automatically.

`transition()` is the ONLY way to change payout status in the codebase. Direct `payout.status = X` is never used.

---

## Q5. The AI Audit

**What AI initially wrote:**

A threading test using Django's `TestCase`:

```python
class ConcurrencyTest(TestCase):
    def test_concurrent_payouts(self):
        thread1 = threading.Thread(target=self._make_payout_request, ...)
        thread2 = threading.Thread(target=self._make_payout_request, ...)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()
```

Result: `[401, 401]` — both threads returned Unauthorized.

**Why it was wrong:**

Django's `TestCase` wraps `setUp` in a transaction that never commits. Threads cannot see uncommitted data — token lookup fails because the `User` doesn't exist in the DB from the thread's perspective.

**What AI tried next:**

Switched to `TransactionTestCase`. Result: balance went to -2000 paise. Both threads succeeded. Test reported race condition exists.

**Why that was also wrong:**

The threads were so fast that Thread A completed entirely before Thread B started. We were testing sequential execution and calling it concurrent. The `SELECT FOR UPDATE` lock was never actually contested. The test was passing for the wrong reason.

**What I (the developer) caught:**

> "Threads are genuinely fast so in most cases Thread A will complete before Thread B. To guarantee they collide we need to induce a `threading.Barrier` or mock induced delay. Thread A acquires the lock, Thread A hits a `time.sleep(1)` via a mock, Thread B attempts to acquire the lock while Thread A is sleeping but still holds the transaction. Thread B should block until Thread A finishes."

**What we replaced it with:**

```python
barrier = threading.Barrier(2, timeout=10)

def attempt_payout(index):
    merchant = Merchant.objects.get(id=merchant_id)
    idem_key = create_idempotency_key(merchant, uuid.uuid4())

    # Forces both threads to reach this point before either proceeds
    # Guarantees genuine simultaneous lock contention
    barrier.wait()

    create_payout(
        merchant=merchant,
        amount_paise=6000,
        bank_account_id=bank_account_id,
        idempotency_key=idem_key,
    )
```

Combined with a mock `time.sleep(1)` inside `transaction.atomic()` to hold Thread A's lock open while Thread B genuinely blocks.

**Why this matters:**

Without the Barrier + sleep, the test proves nothing about concurrency. It only proves sequential logic works. With them, we prove the DB primitive itself is correct — `SELECT FOR UPDATE` genuinely serializes concurrent access.

This distinction is exactly what separates a test that gives confidence from a test that gives false confidence.