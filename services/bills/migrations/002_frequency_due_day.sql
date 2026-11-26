ALTER TABLE dbo.bills DROP CONSTRAINT chk_bill_due_day;
ALTER TABLE dbo.bills ADD CONSTRAINT chk_bill_due_day CHECK (
    (frequency = 'weekly' AND due_day BETWEEN 1 AND 7) OR
    (frequency = 'biweekly' AND due_day BETWEEN 1 AND 14) OR
    (frequency = 'monthly' AND due_day BETWEEN 1 AND 31) OR
    (frequency = 'quarterly' AND due_day BETWEEN 1 AND 90) OR
    (frequency = 'yearly' AND due_day BETWEEN 1 AND 365)
);
