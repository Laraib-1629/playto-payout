from rest_framework import serializers
from .models import Merchant, BankAccount, LedgerEvent, Payout


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = [
            'id',
            'account_number',
            'ifsc_code',
            'account_holder_name',
            'is_active',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class LedgerEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEvent
        fields = [
            'id',
            'event_type',
            'amount_paise',
            'description',
            'payout',
            'created_at',
        ]
        read_only_fields = fields


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = [
            'id',
            'amount_paise',
            'status',
            'bank_account',
            'attempts',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'attempts',
            'created_at',
            'updated_at',
        ]


class PayoutCreateSerializer(serializers.Serializer):
    """
    Used only for validating POST /api/v1/payouts/ request body.
    Separate from PayoutSerializer because creation input
    is different from what we return.
    """
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.IntegerField()

    def validate_amount_paise(self, value):
        # Minimum payout: 100 paise = ₹1
        if value < 100:
            raise serializers.ValidationError(
                'Minimum payout amount is 100 paise (₹1)'
            )
        return value


class MerchantBalanceSerializer(serializers.Serializer):
    """
    Read-only. Returned by GET /api/v1/balance/
    All three values computed from DB aggregations
    in Merchant model properties.
    """
    total_balance_paise = serializers.IntegerField()
    held_balance_paise = serializers.IntegerField()
    available_balance_paise = serializers.IntegerField()
    # Also return rupee equivalents for frontend display
    total_balance_inr = serializers.SerializerMethodField()
    held_balance_inr = serializers.SerializerMethodField()
    available_balance_inr = serializers.SerializerMethodField()

    def get_total_balance_inr(self, obj):
        return obj['total_balance_paise'] / 100

    def get_held_balance_inr(self, obj):
        return obj['held_balance_paise'] / 100

    def get_available_balance_inr(self, obj):
        return obj['available_balance_paise'] / 100