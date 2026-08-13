"""
Generates a synthetic fintech (UPI/card-style) transactions dataset and
writes it to CSV files under data/seed/generated/. Purely synthetic —
no real user, merchant, or employer data of any kind.

Usage:
    python data/seed/generate_data.py [--seed 42] [--users 2000] [--merchants 300] [--transactions 50000]

Output tables (CSV, one file per table, matches schema.sql):
    states.csv, banks.csv, merchant_categories.csv, users.csv,
    merchants.csv, cards.csv, transactions.csv, disputes.csv
"""

import argparse
import csv
import os
import random
from datetime import datetime, timedelta

from faker import Faker

OUT_DIR = os.path.join(os.path.dirname(__file__), "generated")

# ---- Reference data (small, hand-curated for realism) ----------------------

STATES = [
    # (code, name, region)
    ("MH", "Maharashtra", "West"),
    ("DL", "Delhi", "North"),
    ("KA", "Karnataka", "South"),
    ("TN", "Tamil Nadu", "South"),
    ("TG", "Telangana", "South"),
    ("UP", "Uttar Pradesh", "North"),
    ("WB", "West Bengal", "East"),
    ("GJ", "Gujarat", "West"),
    ("RJ", "Rajasthan", "North"),
    ("KL", "Kerala", "South"),
    ("PB", "Punjab", "North"),
    ("HR", "Haryana", "North"),
    ("MP", "Madhya Pradesh", "Central"),
    ("BR", "Bihar", "East"),
    ("AS", "Assam", "Northeast"),
    ("OD", "Odisha", "East"),
]

BANKS = [
    # (name, code, type)
    ("State Bank of India", "SBIN", "Public"),
    ("HDFC Bank", "HDFC", "Private"),
    ("ICICI Bank", "ICIC", "Private"),
    ("Axis Bank", "UTIB", "Private"),
    ("Punjab National Bank", "PUNB", "Public"),
    ("Kotak Mahindra Bank", "KKBK", "Private"),
    ("Bank of Baroda", "BARB", "Public"),
    ("IDFC First Bank", "IDFB", "Private"),
    ("Paytm Payments Bank", "PYTM", "Payments Bank"),
    ("Airtel Payments Bank", "AIRP", "Payments Bank"),
]

MERCHANT_CATEGORIES = [
    # (name, group)
    ("Groceries", "Essential"),
    ("Electronics", "Discretionary"),
    ("Food Delivery", "Discretionary"),
    ("Travel & Transit", "Discretionary"),
    ("Utilities", "Essential"),
    ("Healthcare & Pharmacy", "Essential"),
    ("Apparel & Fashion", "Discretionary"),
    ("Entertainment", "Discretionary"),
    ("Education", "Essential"),
    ("Fuel", "Essential"),
    ("Home & Furniture", "Discretionary"),
    ("Financial Services", "Essential"),
]

CARD_NETWORKS = ["VISA", "MASTERCARD", "RUPAY", "AMEX"]
CARD_TYPES = ["CREDIT", "DEBIT"]
TXN_TYPES = ["UPI", "CARD", "NEFT", "IMPS"]
# Weighted so UPI dominates volume the way it does in the real Indian market.
TXN_TYPE_WEIGHTS = [0.55, 0.25, 0.10, 0.10]
TXN_STATUS = ["SUCCESS", "FAILED", "PENDING"]
TXN_STATUS_WEIGHTS = [0.92, 0.06, 0.02]
USER_SEGMENTS = ["Retail", "SME", "Premium"]
USER_SEGMENT_WEIGHTS = [0.75, 0.15, 0.10]
DISPUTE_REASONS = [
    "Duplicate Charge", "Fraud - Unauthorized", "Item Not Received",
    "Item Not As Described", "Incorrect Amount", "Merchant Error",
]
DISPUTE_STATUS = ["OPEN", "RESOLVED", "REJECTED"]
DISPUTE_STATUS_WEIGHTS = [0.20, 0.65, 0.15]

# Amount ranges vary by category to feel realistic (e.g. groceries small,
# electronics large).
CATEGORY_AMOUNT_RANGE = {
    "Groceries": (100, 3000),
    "Electronics": (1500, 90000),
    "Food Delivery": (100, 1500),
    "Travel & Transit": (200, 25000),
    "Utilities": (300, 6000),
    "Healthcare & Pharmacy": (100, 8000),
    "Apparel & Fashion": (300, 12000),
    "Entertainment": (150, 5000),
    "Education": (500, 50000),
    "Fuel": (200, 4000),
    "Home & Furniture": (500, 60000),
    "Financial Services": (100, 20000),
}

DATE_END = datetime(2026, 8, 10)          # "today" for this dataset
DATE_START = DATE_END - timedelta(days=730)  # 2 years of history


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  wrote {len(rows):>7,} rows -> {path}")


def random_date(start, end):
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days))


def random_ts(start, end):
    delta = end - start
    seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=seconds)


def generate(n_users, n_merchants, n_transactions, seed):
    random.seed(seed)
    fake = Faker("en_IN")
    Faker.seed(seed)

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- states ----
    write_csv(
        os.path.join(OUT_DIR, "states.csv"),
        ["state_code", "state_name", "region"],
        STATES,
    )
    state_codes = [s[0] for s in STATES]

    # ---- banks ----
    bank_rows = [(i + 1, *b) for i, b in enumerate(BANKS)]
    write_csv(
        os.path.join(OUT_DIR, "banks.csv"),
        ["bank_id", "bank_name", "bank_code", "bank_type"],
        bank_rows,
    )
    bank_ids = [b[0] for b in bank_rows]

    # ---- merchant_categories ----
    category_rows = [(i + 1, *c) for i, c in enumerate(MERCHANT_CATEGORIES)]
    write_csv(
        os.path.join(OUT_DIR, "merchant_categories.csv"),
        ["category_id", "category_name", "category_group"],
        category_rows,
    )
    category_by_id = {c[0]: c[1] for c in category_rows}

    # ---- users ----
    print(f"Generating {n_users:,} users...")
    user_rows = []
    for uid in range(1, n_users + 1):
        name = fake.name()
        email = f"{name.split()[0].lower()}{uid}@example.com"  # deterministic + unique
        phone = fake.msisdn()[:10]
        state = random.choice(state_codes)
        signup = random_date(DATE_START, DATE_END)
        segment = random.choices(USER_SEGMENTS, weights=USER_SEGMENT_WEIGHTS)[0]
        is_active = random.random() > 0.05
        user_rows.append((uid, name, email, phone, state, signup.isoformat(), segment, is_active))
    write_csv(
        os.path.join(OUT_DIR, "users.csv"),
        ["user_id", "full_name", "email", "phone", "state_code", "signup_date", "user_segment", "is_active"],
        user_rows,
    )

    # ---- merchants ----
    print(f"Generating {n_merchants:,} merchants...")
    merchant_rows = []
    for mid in range(1, n_merchants + 1):
        name = f"{fake.company()}"
        cat_id = random.choice(list(category_by_id.keys()))
        state = random.choice(state_codes)
        settlement_bank = random.choice(bank_ids)
        onboarded = random_date(DATE_START, DATE_END)
        is_active = random.random() > 0.03
        merchant_rows.append((mid, name, cat_id, state, settlement_bank, onboarded.isoformat(), is_active))
    write_csv(
        os.path.join(OUT_DIR, "merchants.csv"),
        ["merchant_id", "merchant_name", "category_id", "state_code", "settlement_bank_id", "onboarded_date", "is_active"],
        merchant_rows,
    )

    # ---- cards (1-3 per user, ~80% of users have at least one) ----
    print("Generating cards...")
    card_rows = []
    card_id = 1
    user_card_ids = {}  # user_id -> list of card_ids (for txn generation)
    for uid, *_ in user_rows:
        user_card_ids[uid] = []
        if random.random() < 0.80:
            n_cards = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
            for _ in range(n_cards):
                bank_id = random.choice(bank_ids)
                card_type = random.choices(CARD_TYPES, weights=[0.4, 0.6])[0]
                network = random.choices(CARD_NETWORKS, weights=[0.35, 0.15, 0.45, 0.05])[0]
                issued = random_date(DATE_START, DATE_END)
                is_active = random.random() > 0.05
                card_rows.append((card_id, uid, bank_id, card_type, network, issued.isoformat(), is_active))
                user_card_ids[uid].append(card_id)
                card_id += 1
    write_csv(
        os.path.join(OUT_DIR, "cards.csv"),
        ["card_id", "user_id", "bank_id", "card_type", "card_network", "issued_date", "is_active"],
        card_rows,
    )

    # ---- transactions ----
    print(f"Generating {n_transactions:,} transactions...")
    user_ids = [u[0] for u in user_rows]
    merchant_ids = [m[0] for m in merchant_rows]
    merchant_category_lookup = {m[0]: category_by_id[m[2]] for m in merchant_rows}

    # Slight month-over-month growth + a seasonal bump (Oct-Dec, festival season)
    # so "trend" / "quarter over quarter" questions have something real to find.
    txn_rows = []
    txn_id = 1
    for _ in range(n_transactions):
        uid = random.choice(user_ids)
        merchant_id = random.choice(merchant_ids)
        category_name = merchant_category_lookup[merchant_id]
        low, high = CATEGORY_AMOUNT_RANGE[category_name]
        amount = round(random.uniform(low, high), 2)

        txn_type = random.choices(TXN_TYPES, weights=TXN_TYPE_WEIGHTS)[0]
        card_id = ""
        if txn_type == "CARD" and user_card_ids.get(uid):
            card_id = random.choice(user_card_ids[uid])
        elif txn_type == "CARD":
            txn_type = "UPI"  # user has no card, fall back

        state = random.choice(state_codes)
        status = random.choices(TXN_STATUS, weights=TXN_STATUS_WEIGHTS)[0]

        ts = random_ts(DATE_START, DATE_END)
        # Festival season bump: resample ~15% of transactions into Oct-Dec of their year.
        if random.random() < 0.15:
            safe_day = min(ts.day, 28)  # avoid invalid day-of-month after swapping months
            ts = ts.replace(month=random.choice([10, 11, 12]), day=safe_day)

        txn_rows.append((txn_id, uid, card_id, merchant_id, state, amount, "INR", txn_type, status, ts.isoformat(sep=" ")))
        txn_id += 1

    write_csv(
        os.path.join(OUT_DIR, "transactions.csv"),
        ["transaction_id", "user_id", "card_id", "merchant_id", "state_code", "amount", "currency", "transaction_type", "status", "transaction_ts"],
        txn_rows,
    )

    # ---- disputes (~2% of SUCCESS transactions get disputed) ----
    print("Generating disputes...")
    dispute_rows = []
    dispute_id = 1
    success_txns = [t for t in txn_rows if t[8] == "SUCCESS"]
    n_disputes = int(len(success_txns) * 0.02)
    disputed_txns = random.sample(success_txns, min(n_disputes, len(success_txns)))
    for t in disputed_txns:
        txn_id_ = t[0]
        txn_ts = datetime.fromisoformat(t[9])
        opened = txn_ts + timedelta(days=random.randint(1, 20))
        if opened > DATE_END:
            opened = DATE_END
        reason = random.choice(DISPUTE_REASONS)
        status = random.choices(DISPUTE_STATUS, weights=DISPUTE_STATUS_WEIGHTS)[0]
        resolved = ""
        if status in ("RESOLVED", "REJECTED"):
            resolved_dt = opened + timedelta(days=random.randint(1, 15))
            if resolved_dt <= DATE_END:
                resolved = resolved_dt.date().isoformat()
        dispute_rows.append((dispute_id, txn_id_, reason, status, opened.date().isoformat(), resolved))
        dispute_id += 1

    write_csv(
        os.path.join(OUT_DIR, "disputes.csv"),
        ["dispute_id", "transaction_id", "reason", "status", "opened_date", "resolved_date"],
        dispute_rows,
    )

    print("\nDone. CSVs written to:", OUT_DIR)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--users", type=int, default=2000)
    parser.add_argument("--merchants", type=int, default=300)
    parser.add_argument("--transactions", type=int, default=50000)
    args = parser.parse_args()

    generate(args.users, args.merchants, args.transactions, args.seed)
