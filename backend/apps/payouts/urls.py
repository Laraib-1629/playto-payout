from django.urls import path
from .views import (
    BalanceView,
    LedgerView,
    BankAccountListView,
    PayoutListCreateView,
    PayoutDetailView,
)

urlpatterns = [
    path('balance/', BalanceView.as_view(), name='balance'),
    path('ledger/', LedgerView.as_view(), name='ledger'),
    path('bank-accounts/', BankAccountListView.as_view(), name='bank-accounts'),
    path('payouts/', PayoutListCreateView.as_view(), name='payouts'),
    path('payouts/<int:payout_id>/', PayoutDetailView.as_view(), name='payout-detail'),
]