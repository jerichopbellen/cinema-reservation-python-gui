# Cinemalaya

A desktop cinema ticket booking system built with Python, Tkinter, and SQLite.

## Academic Context

This project was created as a class activity for a Python elective subject.

## Technologies

- Python
- Tkinter
- SQLite

## Features

- Modern dark desktop interface with sidebar navigation, toast notifications, and a dark Windows title bar
- User registration, login, and logout with salted PBKDF2 password hashing
- Profile editing and password changes
- Movie catalog with genre, running time, age rating, ticket price, and generated genre posters
- Upcoming showtime selection
- Interactive seat map (rows A–H, seats 1–10) showing available, selected, and booked seats
- Live ticket totals as seats are selected
- Checkout with database-enforced protection against double booking
- Unique booking references and booking confirmation
- Text receipts that can be viewed and saved to a file
- Booking history with upcoming, completed, and canceled bookings
- Booking cancellation that releases seats for others
- Local SQLite storage with fictional sample movies and showtimes

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
│   ├── brand.py
│   ├── booking_views.py
│   ├── main_view.py
│   ├── movie_views.py
│   ├── posters.py
│   ├── profile_view.py
│   ├── seating_view.py
│   ├── styles.py
│   └── widgets.py
├── utils/
│   ├── branding.py
│   └── formatting.py
├── tests/
│   ├── helpers.py
│   ├── test_auth.py
│   ├── test_booking.py
│   ├── test_catalog.py
│   ├── test_database.py
│   └── test_posters.py
├── assets/
├── receipts/
└── data/       
```