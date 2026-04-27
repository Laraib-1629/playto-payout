from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import IntegrityError

from .models import Merchant, Payout
from .serializers import (
    PayoutSerializer,
    PayoutCreateSerializer,
    MerchantBalanceSerializer,
    LedgerEventSerializer,
    BankAccountSerializer,
)
from .services import (
    validate_idempotency_key_header,
    get_idempotency_key,
    create_idempotency_key,
    mark_idempotency_key_done,
    get_merchant_balance,
    create_payout,
    get_ledger,
    get_payouts,
)
from .exceptions import (
    IdempotencyKeyInProgress,
    InsufficientBalance,
    BankAccountNotFound,
)


class MerchantMixin:
    """
    Reusable mixin that fetches the Merchant instance
    from the authenticated User.
    All views that need merchant context inherit this.
    """
    def get_merchant(self, request):
        return request.user.merchant


# ── Balance ───────────────────────────────────────────────────────────────────

class BalanceView(MerchantMixin, APIView):
    """
    GET /api/v1/balance/
    Returns available, held, and total balance for the
    authenticated merchant.
    All values in paise and INR.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        merchant = self.get_merchant(request)
        balance_data = get_merchant_balance(merchant)
        serializer = MerchantBalanceSerializer(balance_data)
        return Response(serializer.data)


# ── Ledger ────────────────────────────────────────────────────────────────────

class LedgerView(MerchantMixin, APIView):
    """
    GET /api/v1/ledger/
    Returns all ledger events for the authenticated merchant.
    Most recent first.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        merchant = self.get_merchant(request)
        events = get_ledger(merchant)
        serializer = LedgerEventSerializer(events, many=True)
        return Response(serializer.data)


# ── Bank Accounts ─────────────────────────────────────────────────────────────

class BankAccountListView(MerchantMixin, APIView):
    """
    GET /api/v1/bank-accounts/
    Returns all active bank accounts for the merchant.
    Frontend uses this to populate the payout form dropdown.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        merchant = self.get_merchant(request)
        accounts = merchant.bank_accounts.filter(is_active=True)
        serializer = BankAccountSerializer(accounts, many=True)
        return Response(serializer.data)


# ── Payouts ───────────────────────────────────────────────────────────────────

class PayoutListCreateView(MerchantMixin, APIView):
    """
    GET  /api/v1/payouts/  → list all payouts
    POST /api/v1/payouts/  → create a new payout

    POST requires Idempotency-Key header.
    Full idempotency flow handled here.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        merchant = self.get_merchant(request)
        payouts = get_payouts(merchant)
        serializer = PayoutSerializer(payouts, many=True)
        return Response(serializer.data)

    def post(self, request):
        merchant = self.get_merchant(request)

        # ── Step 1: Validate Idempotency-Key header ───────────
        raw_key = request.headers.get('Idempotency-Key')
        idempotency_key_uuid = validate_idempotency_key_header(raw_key)

        # ── Step 2: Check if we have seen this key before ─────
        existing_key = get_idempotency_key(merchant, idempotency_key_uuid)

        if existing_key:
            if existing_key.status == existing_key.DONE:
                # Exact same response as the first request.
                # This is the idempotency guarantee.
                return Response(
                    existing_key.response_body,
                    status=existing_key.response_status_code,
                )
            if existing_key.status == existing_key.IN_PROGRESS:
                # First request is still being processed.
                # Return 409 — do not process again.
                raise IdempotencyKeyInProgress()

        # ── Step 3: Write key BEFORE processing ───────────────
        # Write-first pattern. If two simultaneous requests
        # arrive with the same key, unique_together ensures
        # only one INSERT succeeds. The other gets
        # IntegrityError which we catch below.
        try:
            idempotency_key = create_idempotency_key(
                merchant,
                idempotency_key_uuid
            )
        except IntegrityError:
            # Lost the race — another request is processing
            # this key right now.
            raise IdempotencyKeyInProgress()

        # ── Step 4: Validate request body ────────────────────
        serializer = PayoutCreateSerializer(data=request.data)
        if not serializer.is_valid():
            # Clean up the IN_PROGRESS key we just created
            # so the merchant can retry with a new key
            idempotency_key.delete()
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        amount_paise = serializer.validated_data['amount_paise']
        bank_account_id = serializer.validated_data['bank_account_id']

        # ── Step 5: Create payout ─────────────────────────────
        # create_payout handles:
        #   - Bank account validation
        #   - SELECT FOR UPDATE lock
        #   - Balance check inside lock
        #   - Payout + LedgerEvent creation atomically
        try:
            payout = create_payout(
                merchant=merchant,
                amount_paise=amount_paise,
                bank_account_id=bank_account_id,
                idempotency_key=idempotency_key,
            )
        except (InsufficientBalance, BankAccountNotFound) as e:
            # Clean up IN_PROGRESS key on failure
            # so merchant can retry with corrected amount
            idempotency_key.delete()
            raise e

        # ── Step 6: Build response ────────────────────────────
        response_data = PayoutSerializer(payout).data
        response_status = status.HTTP_201_CREATED

        # ── Step 7: Mark key as DONE, store response ──────────
        # Future duplicate requests will get this exact
        # response_data and response_status returned directly.
        mark_idempotency_key_done(
            idempotency_key,
            response_data,
            response_status,
        )

        return Response(response_data, status=response_status)


class PayoutDetailView(MerchantMixin, APIView):
    """
    GET /api/v1/payouts/<id>/
    Returns a single payout with current status.
    Frontend polls this every 5s for live status updates.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, payout_id):
        merchant = self.get_merchant(request)

        try:
            payout = Payout.objects.get(
                id=payout_id,
                merchant=merchant,
            )
        except Payout.DoesNotExist:
            return Response(
                {'error': 'Payout not found', 'code': 'PAYOUT_NOT_FOUND'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PayoutSerializer(payout)
        return Response(serializer.data)