-- QueryMind synthetic fintech dataset schema.
-- Loosely modeled on a UPI/card payments processor: users hold cards,
-- transact with merchants, transactions can be disputed, everything is
-- geographically tagged by Indian state/region for "group by state" style
-- analytics questions.

DROP TABLE IF EXISTS disputes CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS cards CASCADE;
DROP TABLE IF EXISTS merchants CASCADE;
DROP TABLE IF EXISTS merchant_categories CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS banks CASCADE;
DROP TABLE IF EXISTS states CASCADE;

-- Reference table: Indian states/UTs grouped into regions.
CREATE TABLE states (
    state_code   CHAR(2) PRIMARY KEY,
    state_name   VARCHAR(50) NOT NULL,
    region       VARCHAR(20) NOT NULL   -- North / South / East / West / Central / Northeast
);

-- Reference table: issuing/settlement banks.
CREATE TABLE banks (
    bank_id      SERIAL PRIMARY KEY,
    bank_name    VARCHAR(100) NOT NULL,
    bank_code    VARCHAR(10) UNIQUE NOT NULL,
    bank_type    VARCHAR(20) NOT NULL   -- Public / Private / Payments Bank / NBFC
);

-- Reference table: merchant category codes (MCC-style groupings).
CREATE TABLE merchant_categories (
    category_id     SERIAL PRIMARY KEY,
    category_name   VARCHAR(50) NOT NULL,     -- e.g. "Groceries", "Travel"
    category_group  VARCHAR(30) NOT NULL      -- e.g. "Essential", "Discretionary"
);

CREATE TABLE users (
    user_id        SERIAL PRIMARY KEY,
    full_name      VARCHAR(100) NOT NULL,
    email          VARCHAR(120) UNIQUE NOT NULL,
    phone          VARCHAR(15) NOT NULL,
    state_code     CHAR(2) NOT NULL REFERENCES states(state_code),
    signup_date    DATE NOT NULL,
    user_segment   VARCHAR(20) NOT NULL,   -- Retail / SME / Premium
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE merchants (
    merchant_id       SERIAL PRIMARY KEY,
    merchant_name     VARCHAR(120) NOT NULL,
    category_id       INTEGER NOT NULL REFERENCES merchant_categories(category_id),
    state_code        CHAR(2) NOT NULL REFERENCES states(state_code),
    settlement_bank_id INTEGER NOT NULL REFERENCES banks(bank_id),
    onboarded_date    DATE NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE cards (
    card_id        SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(user_id),
    bank_id        INTEGER NOT NULL REFERENCES banks(bank_id),
    card_type      VARCHAR(10) NOT NULL,   -- CREDIT / DEBIT
    card_network   VARCHAR(15) NOT NULL,   -- VISA / MASTERCARD / RUPAY / AMEX
    issued_date    DATE NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE transactions (
    transaction_id     BIGSERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL REFERENCES users(user_id),
    card_id            INTEGER REFERENCES cards(card_id),   -- NULL for UPI transactions
    merchant_id        INTEGER NOT NULL REFERENCES merchants(merchant_id),
    state_code         CHAR(2) NOT NULL REFERENCES states(state_code),  -- where txn occurred
    amount             NUMERIC(12, 2) NOT NULL,
    currency           CHAR(3) NOT NULL DEFAULT 'INR',
    transaction_type   VARCHAR(10) NOT NULL,   -- UPI / CARD / NEFT / IMPS
    status             VARCHAR(10) NOT NULL,   -- SUCCESS / FAILED / PENDING
    transaction_ts     TIMESTAMP NOT NULL
);

CREATE TABLE disputes (
    dispute_id      SERIAL PRIMARY KEY,
    transaction_id  BIGINT NOT NULL REFERENCES transactions(transaction_id),
    reason          VARCHAR(50) NOT NULL,   -- e.g. "Duplicate Charge", "Fraud", "Item Not Received"
    status          VARCHAR(15) NOT NULL,   -- OPEN / RESOLVED / REJECTED
    opened_date     DATE NOT NULL,
    resolved_date   DATE
);

-- Indexes that matter for the analytics questions this project targets.
CREATE INDEX idx_transactions_ts ON transactions (transaction_ts);
CREATE INDEX idx_transactions_state ON transactions (state_code);
CREATE INDEX idx_transactions_merchant ON transactions (merchant_id);
CREATE INDEX idx_transactions_user ON transactions (user_id);
CREATE INDEX idx_disputes_txn ON disputes (transaction_id);
