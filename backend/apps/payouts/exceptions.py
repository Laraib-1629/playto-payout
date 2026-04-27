from rest_framework.exceptions import APIException
from rest_framework import status


class InsufficientBalance(APIException):
    """
    Raised when a payout request exceeds available balance.
    Returns 422 Unprocessable Entity.
    """
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = 'insufficient_balance'

    def __init__(self, available_balance, requested_amount):
        self.detail = {
            'error': 'Insufficient balance',
            'code': 'INSUFFICIENT_BALANCE',
            'available_balance_paise': available_balance,
            'requested_amount_paise': requested_amount,
        }


class IdempotencyKeyInProgress(APIException):
    """
    Raised when a second request arrives with the same
    idempotency key while the first is still processing.
    Returns 409 Conflict.
    """
    status_code = status.HTTP_409_CONFLICT
    default_code = 'idempotency_key_in_progress'

    def __init__(self):
        self.detail = {
            'error': 'A request with this idempotency key is already being processed',
            'code': 'IDEMPOTENCY_KEY_IN_PROGRESS',
        }


class IdempotencyKeyMissing(APIException):
    """
    Raised when the Idempotency-Key header is absent.
    Returns 400 Bad Request.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'idempotency_key_missing'

    def __init__(self):
        self.detail = {
            'error': 'Idempotency-Key header is required',
            'code': 'IDEMPOTENCY_KEY_MISSING',
        }


class InvalidIdempotencyKey(APIException):
    """
    Raised when the Idempotency-Key header is not a valid UUID.
    Returns 400 Bad Request.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'invalid_idempotency_key'

    def __init__(self):
        self.detail = {
            'error': 'Idempotency-Key must be a valid UUID',
            'code': 'INVALID_IDEMPOTENCY_KEY',
        }


class InvalidStateTransition(APIException):
    """
    Raised when code attempts an illegal payout state transition.
    Returns 400 Bad Request.
    This should never reach the API in normal flow —
    it exists as a safety net.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'invalid_state_transition'

    def __init__(self, from_status, to_status):
        self.detail = {
            'error': f'Invalid state transition: {from_status} → {to_status}',
            'code': 'INVALID_STATE_TRANSITION',
        }


class BankAccountNotFound(APIException):
    """
    Raised when bank_account_id doesn't belong to the merchant.
    Returns 404 Not Found.
    """
    status_code = status.HTTP_404_NOT_FOUND
    default_code = 'bank_account_not_found'

    def __init__(self):
        self.detail = {
            'error': 'Bank account not found or does not belong to this merchant',
            'code': 'BANK_ACCOUNT_NOT_FOUND',
        }