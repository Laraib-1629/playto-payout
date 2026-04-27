import random
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from .models import Payout
from .services import complete_payout, fail_payout

logger = logging.getLogger(__name__)


def simulate_bank_response():
    """
    Simulates bank settlement response.
    70% success, 20% failure, 10% hang (timeout).
    Uses random to pick outcome.
    """
    roll = random.random()  # 0.0 to 1.0

    if roll < 0.70:
        return 'success'
    elif roll < 0.90:      # 0.70 to 0.90 = 20%
        return 'failure'
    else:                  # 0.90 to 1.00 = 10%
        return 'hang'


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name='payouts.process_payout',
)
def process_payout(self, payout_id):
    """
    Celery task that processes a single payout.

    Lifecycle:
      PENDING → PROCESSING → COMPLETED (70%)
      PENDING → PROCESSING → FAILED + reversal (20%)
      PENDING → PROCESSING → stays (10%, retried up to 3 times)

    Retry logic:
      On hang: exponential backoff
        attempt 1 → wait 30s
        attempt 2 → wait 60s
        attempt 3 → wait 120s
      After 3 retries → FAILED + funds returned
    """
    logger.info(f'Processing payout {payout_id}, attempt {self.request.retries + 1}')

    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        logger.error(f'Payout {payout_id} not found')
        return

    # Skip terminal states
    if payout.status in [Payout.COMPLETED, Payout.FAILED]:
        logger.info(f'Payout {payout_id} already in terminal state {payout.status}, skipping')
        return

    # Max attempts exceeded
    if payout.attempts >= 3:
        logger.warning(f'Payout {payout_id} exceeded max attempts, marking failed')
        try:
            fail_payout(payout)
        except ValueError as e:
            logger.error(f'State transition error for payout {payout_id}: {e}')
        return

    # ── Transition to PROCESSING only if PENDING ──────────────
    # If already PROCESSING (retry scenario from detect_stuck_payouts
    # or Celery retry), skip the transition — just re-attempt the bank
    if payout.status == Payout.PENDING:
        try:
            payout.transition(Payout.PROCESSING)
        except ValueError as e:
            logger.warning(f'Could not transition payout {payout_id} to PROCESSING: {e}')
            return
    elif payout.status == Payout.PROCESSING:
        # Already PROCESSING — this is a retry
        # Don't transition, just re-attempt the bank simulation
        logger.info(f'Payout {payout_id} already PROCESSING, re-attempting bank simulation')

    # Increment attempt counter
    payout.attempts += 1
    payout.save(update_fields=['attempts', 'updated_at'])

    # Simulate bank
    result = simulate_bank_response()
    logger.info(f'Payout {payout_id} bank simulation result: {result}')

    if result == 'success':
        try:
            complete_payout(payout)
            logger.info(f'Payout {payout_id} completed successfully')
        except ValueError as e:
            logger.error(f'Could not complete payout {payout_id}: {e}')

    elif result == 'failure':
        try:
            fail_payout(payout)
            logger.info(f'Payout {payout_id} failed, funds reversed')
        except ValueError as e:
            logger.error(f'Could not fail payout {payout_id}: {e}')

    elif result == 'hang':
        countdown = 30 * (2 ** self.request.retries)
        logger.warning(
            f'Payout {payout_id} hung, retrying in {countdown}s '
            f'(attempt {self.request.retries + 1}/3)'
        )
        try:
            raise self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f'Payout {payout_id} max retries exceeded, failing')
            try:
                fail_payout(payout)
            except ValueError as e:
                logger.error(f'Could not fail payout {payout_id} after max retries: {e}')

@shared_task(name='payouts.dispatch_pending_payouts')
def dispatch_pending_payouts():
    """
    Periodic task — runs every 30 seconds via Celery Beat.
    Finds all PENDING payouts and dispatches them
    to the process_payout worker.

    This is the entry point of the payout lifecycle.
    """
    pending_payouts = Payout.objects.filter(
        status=Payout.PENDING
    ).values_list('id', flat=True)

    count = len(pending_payouts)
    if count:
        logger.info(f'Dispatching {count} pending payouts')

    for payout_id in pending_payouts:
        process_payout.delay(payout_id)

    return f'Dispatched {count} pending payouts'


@shared_task(name='payouts.detect_stuck_payouts')
def detect_stuck_payouts():
    """
    Periodic task — runs every 60 seconds via Celery Beat.
    Finds payouts stuck in PROCESSING for more than 30 seconds
    and retries them.

    A payout is "stuck" when:
    - Status is PROCESSING
    - updated_at is older than 30 seconds
    - attempts < 3 (still has retries left)

    This handles the 10% hang scenario where the
    process_payout task itself hung or crashed
    before completing.
    """
    stuck_cutoff = timezone.now() - timedelta(seconds=30)

    stuck_payouts = Payout.objects.filter(
        status=Payout.PROCESSING,
        updated_at__lt=stuck_cutoff,
        attempts__lt=3,
    ).values_list('id', flat=True)

    count = len(stuck_payouts)
    if count:
        logger.warning(f'Found {count} stuck payouts, retrying')

    for payout_id in stuck_payouts:
        process_payout.delay(payout_id)

    return f'Retried {count} stuck payouts'