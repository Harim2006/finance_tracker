
CREATE TABLE dbo.envelopes (
    id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(255) NOT NULL UNIQUE,
    monthly_allocation DECIMAL(18,2) NOT NULL,
    current_balance DECIMAL(18,2) NOT NULL DEFAULT 0,
    overspend_rule NVARCHAR(20) NOT NULL DEFAULT 'stop',
    rollover_enabled BIT NOT NULL DEFAULT 1,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    last_rollover_date DATE NULL,

    CONSTRAINT chk_envelope_allocation
        CHECK (monthly_allocation >= 0),

    CONSTRAINT chk_overspend_rule
        CHECK (overspend_rule IN ('stop', 'borrow'))
);

CREATE TABLE dbo.transactions (
    id INT IDENTITY(1,1) PRIMARY KEY,
    envelope_id INT NOT NULL,
    amount DECIMAL(18,2) NOT NULL,
    date DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    description NVARCHAR(500),
    merchant NVARCHAR(255),
    category NVARCHAR(255),

    FOREIGN KEY (envelope_id)
        REFERENCES dbo.envelopes(id)
);

CREATE TABLE dbo.envelope_history (
    id INT IDENTITY(1,1) PRIMARY KEY,
    envelope_id INT NOT NULL,
    month CHAR(7) NOT NULL,
    allocated DECIMAL(18,2),
    spent DECIMAL(18,2),
    rolled_over DECIMAL(18,2),

    FOREIGN KEY (envelope_id)
        REFERENCES dbo.envelopes(id)
);

CREATE TABLE dbo.category_rules (
    id INT IDENTITY(1,1) PRIMARY KEY,
    merchant_pattern NVARCHAR(255) NOT NULL,
    envelope_id INT NOT NULL,
    priority INT NOT NULL DEFAULT 0,

    FOREIGN KEY (envelope_id)
        REFERENCES dbo.envelopes(id)
);

CREATE INDEX idx_transactions_date
    ON dbo.transactions(date);

CREATE INDEX idx_transactions_envelope
    ON dbo.transactions(envelope_id);
