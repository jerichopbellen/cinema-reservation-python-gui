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
- User registration and login
- Secure password storage (PBKDF2-SHA256 with a random salt per user)
- Profile management: edit your full name and change your password
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
├── services/
│   ├── auth_service.py
│   └── session.py
├── ui/
│   ├── app.py
│   ├── auth_views.py
│   ├── main_view.py
│   ├── profile_view.py
│   ├── styles.py
│   └── widgets.py
├── utils/
│   └── formatting.py
├── tests/
│   ├── test_auth.py
│   └── test_database.py
├── assets/
├── receipts/
└── data/
```