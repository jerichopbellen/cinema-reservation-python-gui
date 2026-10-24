# Cinema Ticket Booking System

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
- Administrator movie management: add, edit, archive, restore, and delete movies (movies with booking history are archived, never deleted)
- Administrator showtime scheduling with overlap checks per cinema; showtimes with confirmed upcoming bookings cannot be removed
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

Create the first administrator (prompts for a name, username, and hidden password):

```bash
python create_admin.py
```

Or promote an existing account (add `--revoke` to make it a customer again):

```bash
python promote_admin.py USERNAME
```

Administrators see **Manage Movies** in the sidebar after logging in. Accounts made through the app's registration screen are always customers.

## Seeding Demo Movies

Add new fictional movies with upcoming showtimes (asks before changing anything):

```bash
python seed_movies.py
```

Every run adds movies whose titles and descriptions aren't already in the database, and showtimes that all start after the moment you run it. Showtimes never overlap in a cinema (cleaning time included), and a day without room is skipped. Options: `--movies N` (default 5), `--days N` (default 3), `--per-day N` (default 2), `--yes` to skip the prompt, `--db PATH` for another database file.

## Project Structure

```text
cinema/
├── main.py
├── create_admin.py
├── promote_admin.py
├── seed_movies.py
├── database/
│   ├── connection.py
│   ├── schema.py
│   ├── seed.py
│   ├── movie_generator.py
│   └── inspect_db.py
├── services/
│   ├── auth_service.py
│   ├── booking_service.py
│   ├── catalog_service.py
│   ├── errors.py
│   ├── movie_admin_service.py
│   ├── receipt_service.py
│   ├── seating_service.py
│   ├── showtime_admin_service.py
│   └── session.py
├── ui/
│   ├── admin_views.py
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
│   ├── test_admin.py
│   ├── test_auth.py
│   ├── test_booking.py
│   ├── test_catalog.py
│   ├── test_database.py
│   ├── test_posters.py
│   └── test_showtime_admin.py
├── assets/
├── receipts/
└── data/       
```
