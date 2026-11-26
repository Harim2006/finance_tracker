USE master;
GO

IF DB_ID('budget_db') IS NULL
    CREATE DATABASE budget_db;
GO

IF DB_ID('bills_db') IS NULL
    CREATE DATABASE bills_db;
GO