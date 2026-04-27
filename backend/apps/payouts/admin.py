from django.contrib import admin
from .models import Merchant, BankAccount, LedgerEvent, Payout, IdempotencyKey


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'email',
        'get_available_balance',
        'get_held_balance',
        'get_total_balance',
        'created_at',
    ]
    readonly_fields = [
        'get_available_balance',
        'get_held_balance',
        'get_total_balance',
        'created_at',
    ]
    search_fields = ['name', 'email']

    @admin.display(description='Available Balance (paise)')
    def get_available_balance(self, obj):
        return obj.available_balance

    @admin.display(description='Held Balance (paise)')
    def get_held_balance(self, obj):
        return obj.held_balance

    @admin.display(description='Total Balance (paise)')
    def get_total_balance(self, obj):
        return obj.total_balance


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = [
        'account_holder_name',
        'merchant',
        'account_number',
        'ifsc_code',
        'is_active',
    ]
    list_filter = ['is_active']
    search_fields = ['account_holder_name', 'account_number']


@admin.register(LedgerEvent)
class LedgerEventAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'merchant',
        'event_type',
        'amount_paise',
        'description',
        'payout',
        'created_at',
    ]
    list_filter = ['event_type', 'merchant']
    search_fields = ['description', 'merchant__name']
    readonly_fields = [
        'merchant',
        'event_type',
        'amount_paise',
        'description',
        'payout',
        'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'merchant',
        'amount_paise',
        'status',
        'attempts',
        'bank_account',
        'created_at',
        'updated_at',
    ]
    list_filter = ['status', 'merchant']
    search_fields = ['merchant__name']
    readonly_fields = [
        'merchant',
        'amount_paise',
        'bank_account',
        'idempotency_key',
        'created_at',
        'updated_at',
    ]


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = [
        'key',
        'merchant',
        'status',
        'response_status_code',
        'created_at',
    ]
    list_filter = ['status', 'merchant']
    readonly_fields = [
        'merchant',
        'key',
        'status',
        'response_body',
        'response_status_code',
        'created_at',
    ]