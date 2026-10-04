# Personal Finance Tracker - Envelope Budget + Bill Tracker

A comprehensive personal finance management application combining envelope budgeting with bill tracking and AI-powered financial insights.

## Features

### Domain A: Envelope Budgeting
- Create budget envelopes for different spending categories (Groceries, Dining, etc.)
- Set monthly allocations for each envelope
- Track transactions and automatically deduct from envelopes
- Overspend rules: "stop" (prevent overdraft) or "borrow" (allow negative)
- Monthly rollover: carry remaining funds to next month
- Auto-categorization of transactions based on merchant patterns

### Domain B: Bill & Subscription Tracking
- Track recurring bills (monthly, quarterly, yearly)
- Due date management and payment status (paid/unpaid)
- Project upcoming bills for multiple months
- Payment history tracking
- Automatic next due date calculation after payment

### Additional Features
- **Fake Bank API**: Simulates bank transactions being automatically imported
- **LLM Financial Analyzer**: Rule-based AI that answers questions and provides insights
- **Web Dashboard**: Clean, responsive interface for managing finances
- **API Endpoints**: RESTful API for all operations

## Technology Stack

- **Backend**: Python 3.11 with Flask 3.0
- **Database**: SQLite (single file at `./data/finance.db`)
- **Frontend**: HTML, CSS, vanilla JavaScript
- **Testing**: unittest with coverage reporting

## Setup Instructions

### Prerequisites
- Python 3.9 or higher
- pip (Python package manager)

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd finance-tracker