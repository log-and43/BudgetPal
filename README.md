# 💰 BudgetPal – Personal Budget Tracker

A Python desktop app for tracking expenses, paychecks, and savings goals.
Data is saved as human-readable `.xlsx` files (one per user).

---

## Requirements

- Python 3.10+
- Dependencies (install once):

```bash
pip install openpyxl pillow
```

> `pillow` is optional — only needed if you want to set custom background images.

---

## Running the App

```bash
cd budget_app
python app.py
```

---

## Features

| Feature | Details |
|---|---|
| **Currencies** | USD ($) and JPY (¥) |
| **Pay Periods** | Weekly, Biweekly, Monthly |
| **User Profiles** | Each user gets a unique 8-character ID (e.g. `A3F7C2B1`). Save it! |
| **Expenses** | Add, edit, delete named expenses at any time |
| **Savings Goals** | Set a target amount + deadline → app calculates per-paycheck contribution |
| **Budget Snapshot** | After logging a paycheck, see exactly how much is left to spend |
| **Background Images** | Click 🖼 BG to set any image as the background |
| **Data Storage** | All data saved to `user_data/<UID>.xlsx` — human-readable in Excel |

---

## File Structure

```
budget_app/
├── app.py              ← Main GUI (run this)
├── data_manager.py     ← Data logic & XLSX writer
├── user_data/          ← One .xlsx file per user (auto-created)
│   └── <UID>.xlsx
├── backgrounds/        ← Place your background images here
└── README.md
```

---

## Your XLSX File Sheets

| Sheet | Contents |
|---|---|
| **Meta** | Name, currency, pay period, user ID |
| **Expenses** | All expenses with per-period and annual totals |
| **Goals** | Savings goals with deadlines and per-paycheck amounts |
| **Paycheck Log** | History of all logged paychecks |
| **Budget Summary** | Latest budget snapshot |

---

## Tips

- **Losing your ID?** Check `user_data/` — each file is named with your ID.
- **Edit data directly?** Yes! The `.xlsx` is human-readable. Just re-open the app after.
- **Multiple users?** Each person gets their own file — just use different IDs.
