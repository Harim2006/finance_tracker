
CREATE TABLE dbo.bills (
    id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(255) NOT NULL,
    amount DECIMAL(18,2) NOT NULL,
    frequency NVARCHAR(30) NOT NULL,
    due_day INT NOT NULL,
    category NVARCHAR(255),
    auto_pay BIT NOT NULL DEFAULT 0,
    next_due_date DATE,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    active BIT NOT NULL DEFAULT 1,

    CONSTRAINT chk_bill_amount
        CHECK (amount > 0),

    CONSTRAINT chk_bill_due_day
        CHECK (due_day BETWEEN 1 AND 31)
);

CREATE TABLE dbo.bill_payments (
    id INT IDENTITY(1,1) PRIMARY KEY,
    bill_id INT NOT NULL,
    due_date DATE NOT NULL,
    paid_date DATE,
    amount_paid DECIMAL(18,2),
    status NVARCHAR(30) NOT NULL DEFAULT 'unpaid',

    FOREIGN KEY (bill_id)
        REFERENCES dbo.bills(id)
);

CREATE INDEX idx_bills_due_date
    ON dbo.bills(next_due_date);

CREATE INDEX idx_bill_payments_status
    ON dbo.bill_payments(status);
