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
- Movie browsing with genre, running time, rating, and ticket price
- Showtime selection from upcoming screenings
- Interactive seat selection with live availability (rows A–H, seats 1–10)
- Live ticket price calculation as seats are selected
- Ticket checkout and confirmation, with seats protected against double booking
- Unique booking references
- Receipt generation and saving (saved to `receipts/` by default)
- Booking history showing upcoming, completed, and canceled bookings
- Booking cancellation that releases seats for others
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
│   ├── booking_service.py
│   ├── catalog_service.py
│   ├── errors.py
│   ├── receipt_service.py
│   ├── seating_service.py
│   └── session.py
├── ui/
│   ├── app.py
│   ├── auth_views.py
│   ├── booking_views.py
│   ├── main_view.py
│   ├── movie_views.py
│   ├── profile_view.py
│   ├── seating_view.py
│   ├── styles.py
│   └── widgets.py
├── utils/
│   ├── branding.py
│   └── formatting.py
├── tests/
│   ├── test_auth.py
│   ├── test_booking.py
│   ├── test_catalog.py
│   └── test_database.py
├── assets/
├── receipts/
└── data/
```