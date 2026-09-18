CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0)
);

CREATE TABLE IF NOT EXISTS bills (
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    card TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    due_in_days INTEGER NOT NULL CHECK (due_in_days >= 0),
    paid_cents INTEGER NOT NULL DEFAULT 0 CHECK (paid_cents >= 0),
    PRIMARY KEY (account_id, id)
);

CREATE TABLE IF NOT EXISTS investments (
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0),
    daily_liquidity INTEGER NOT NULL CHECK (daily_liquidity IN (0, 1)),
    PRIMARY KEY (account_id, id)
);

-- What the money did: redemptions and payments.
CREATE TABLE IF NOT EXISTS operations (
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('redeem_investment', 'pay_card_bill')),
    target_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, id)
);

-- What the agent did: every MCP tool call, including reads.
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
