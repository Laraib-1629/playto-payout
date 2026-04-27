from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payouts', '0001_initial'),
    ]

    operations = [
        # ── Trigger 1: Immutability ──────────────────────────────
        # Prevents ANY update or delete on LedgerEvent rows.
        # Once written, a ledger event is permanent.
        # This is enforced at DB level — no application code
        # can accidentally corrupt financial history.
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION prevent_ledger_mutation()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION
                        'LedgerEvent is immutable. Cannot % row id=%',
                        TG_OP, OLD.id;
                END;
                $$ LANGUAGE plpgsql;

                CREATE TRIGGER ledger_immutability
                    BEFORE UPDATE OR DELETE ON payouts_ledgerevent
                    FOR EACH ROW
                    EXECUTE FUNCTION prevent_ledger_mutation();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS ledger_immutability
                    ON payouts_ledgerevent;
                DROP FUNCTION IF EXISTS prevent_ledger_mutation();
            """
        ),

        # ── Trigger 2: Non-negative balance ─────────────────────
        # Prevents any debit that would push balance negative.
        # Third layer of defense after:
        #   1. Python available_balance check
        #   2. SELECT FOR UPDATE lock
        # Even if both fail due to a bug, DB rejects the insert.
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION check_non_negative_balance()
                RETURNS TRIGGER AS $$
                DECLARE
                    current_balance BIGINT;
                BEGIN
                    -- Only check negative amounts (debits)
                    IF NEW.amount_paise >= 0 THEN
                        RETURN NEW;
                    END IF;

                    SELECT COALESCE(SUM(amount_paise), 0)
                    INTO current_balance
                    FROM payouts_ledgerevent
                    WHERE merchant_id = NEW.merchant_id;

                    IF (current_balance + NEW.amount_paise) < 0 THEN
                        RAISE EXCEPTION
                            'Insufficient balance. Current: % paise, '
                            'Attempted debit: % paise, '
                            'Would result in: % paise',
                            current_balance,
                            NEW.amount_paise,
                            (current_balance + NEW.amount_paise);
                    END IF;

                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                CREATE TRIGGER enforce_non_negative_balance
                    BEFORE INSERT ON payouts_ledgerevent
                    FOR EACH ROW
                    EXECUTE FUNCTION check_non_negative_balance();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS enforce_non_negative_balance
                    ON payouts_ledgerevent;
                DROP FUNCTION IF EXISTS check_non_negative_balance();
            """
        ),
    ]