# Cinema Ticket Booking System

A desktop cinema ticket booking system built with Python, Tkinter, and SQLite.

## Academic Context

This project was created as a class activity for a Python elective subject.

## Technologies

- Python
- Tkinter
- SQLite

## Features

- Cinema-themed desktop interface
- Sample movies and showtimes
- SQLite database for storing application data

## Getting Started

Run the application:

```bash
python main.py
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

No additional packages are required.

## Project Structure

```text
cinema/
├── main.py
├── database/
│   ├── connection.py
│   ├── schema.py
│   ├── seed.py
│   └── inspect_db.py
├── ui/
│   ├── styles.py
│   └── main_view.py
├── utils/
│   └── formatting.py
├── tests/
│   └── test_database.py
├── assets/
├── receipts/
└── data/
```