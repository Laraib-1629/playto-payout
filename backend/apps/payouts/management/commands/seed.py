from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from django.db import transaction

from apps.payouts.models import (
    Merchant,
    BankAccount,
    LedgerEvent,
    Payout,
)


class Command(BaseCommand):
    help = 'Seed database with merchants, bank accounts, and credit history'

    def handle(self, *args, **kwargs):
        # Don't reseed if merchants already exist
        if Merchant.objects.exists():
            self.stdout.write('Database already seeded, skipping.')
            self._print_tokens()
            return

        self.stdout.write('Seeding database...')

        with transaction.atomic():
            self._clear_existing()
            self._seed_merchants()

        self.stdout.write(self.style.SUCCESS('Database seeded successfully'))
        self._print_tokens()

    def _clear_existing(self):
        self.stdout.write('Clearing existing data...')
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                TRUNCATE TABLE 
                    payouts_ledgerevent,
                    payouts_payout,
                    payouts_idempotencykey,
                    payouts_bankaccount,
                    payouts_merchant,
                    authtoken_token,
                    auth_user
                RESTART IDENTITY CASCADE;
            """)

    def _seed_merchants(self):
        user1 = User.objects.create_user(
            username='merchant_rahul',
            email='rahul@designstudio.com',
            password='testpass123',
        )
        token1, _ = Token.objects.get_or_create(user=user1)
        merchant1 = Merchant.objects.create(
            user=user1,
            name='Rahul Design Studio',
            email='rahul@designstudio.com',
        )
        BankAccount.objects.create(
            merchant=merchant1,
            account_number='1234567890',
            ifsc_code='HDFC0001234',
            account_holder_name='Rahul Sharma',
        )
        LedgerEvent.objects.create(
            merchant=merchant1,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=150000,
            description='Payment from Acme Corp',
        )
        LedgerEvent.objects.create(
            merchant=merchant1,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=230000,
            description='Payment from TechStart Inc',
        )
        LedgerEvent.objects.create(
            merchant=merchant1,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=80000,
            description='Payment from freelance gig',
        )
        self.stdout.write(f'  Created merchant: {merchant1.name}')
        self.stdout.write(f'  Auth token: {token1.key}')
        self.stdout.write(f'  Balance: ₹4600')

        user2 = User.objects.create_user(
            username='merchant_priya',
            email='priya@contentco.com',
            password='testpass123',
        )
        token2, _ = Token.objects.get_or_create(user=user2)
        merchant2 = Merchant.objects.create(
            user=user2,
            name='Priya Content Co',
            email='priya@contentco.com',
        )
        BankAccount.objects.create(
            merchant=merchant2,
            account_number='9876543210',
            ifsc_code='SBIN0009876',
            account_holder_name='Priya Patel',
        )
        LedgerEvent.objects.create(
            merchant=merchant2,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=500000,
            description='Retainer - GlobalBrand',
        )
        LedgerEvent.objects.create(
            merchant=merchant2,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=120000,
            description='Invoice #1042',
        )
        self.stdout.write(f'  Created merchant: {merchant2.name}')
        self.stdout.write(f'  Auth token: {token2.key}')
        self.stdout.write(f'  Balance: ₹6200')

        user3 = User.objects.create_user(
            username='merchant_devcraft',
            email='amit@devcraft.com',
            password='testpass123',
        )
        token3, _ = Token.objects.get_or_create(user=user3)
        merchant3 = Merchant.objects.create(
            user=user3,
            name='DevCraft Solutions',
            email='amit@devcraft.com',
        )
        BankAccount.objects.create(
            merchant=merchant3,
            account_number='1122334455',
            ifsc_code='ICIC0001122',
            account_holder_name='Amit Kumar',
        )
        LedgerEvent.objects.create(
            merchant=merchant3,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=1000000,
            description='Project milestone payment',
        )
        LedgerEvent.objects.create(
            merchant=merchant3,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=250000,
            description='Consulting - Feb',
        )
        LedgerEvent.objects.create(
            merchant=merchant3,
            event_type=LedgerEvent.CREDIT_RECEIVED,
            amount_paise=175000,
            description='Consulting - Mar',
        )
        self.stdout.write(f'  Created merchant: {merchant3.name}')
        self.stdout.write(f'  Auth token: {token3.key}')
        self.stdout.write(f'  Balance: ₹14250')

    def _print_tokens(self):
        self.stdout.write('\n' + '─' * 50)
        self.stdout.write('AUTH TOKENS (use in Authorization header):')
        self.stdout.write('─' * 50)

        for user in User.objects.filter(
            username__startswith='merchant_'
        ):
            token = Token.objects.get(user=user)
            self.stdout.write(
                f'{user.username}: Token {token.key}'
            )

        self.stdout.write('─' * 50)
        self.stdout.write(
            'Usage: Authorization: Token <token_value>'
        )