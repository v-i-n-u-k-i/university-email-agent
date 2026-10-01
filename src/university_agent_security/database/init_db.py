"""Create and seed the local Westbridge University SQLite database."""

import argparse
import sqlite3
from pathlib import Path

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[3] / "data" / "university.db"

SCHEMA = """
DROP TABLE IF EXISTS emails;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS students;

CREATE TABLE students (
    student_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    course TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE enrollments (
    enrollment_id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    unit_code TEXT NOT NULL,
    unit_name TEXT NOT NULL,
    enrollment_status TEXT NOT NULL,
    UNIQUE (student_id, unit_code)
);

CREATE TABLE emails (
    email_id INTEGER PRIMARY KEY,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    read_status TEXT NOT NULL CHECK (read_status IN ('read', 'unread'))
);

CREATE TABLE tickets (
    ticket_id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

STUDENTS = [
    (
        1,
        "Kim",
        "Park",
        "kim.park@students.westbridge.example",
        "BSc Cybersecurity",
        "active",
    ),
    (
        2,
        "Avery",
        "Chen",
        "avery.chen@students.westbridge.example",
        "BSc Computer Science",
        "active",
    ),
    (
        3,
        "Rowan",
        "Ellis",
        "rowan.ellis@students.westbridge.example",
        "BA Digital Media",
        "active",
    ),
    (
        4,
        "Samira",
        "Nadeem",
        "samira.nadeem@students.westbridge.example",
        "BSc Information Systems",
        "active",
    ),
    (
        5,
        "Leo",
        "Morgan",
        "leo.morgan@students.westbridge.example",
        "BSc Cybersecurity",
        "active",
    ),
]

ENROLLMENTS = [
    (1, 1, "SEC101", "Foundations of Security", "enrolled"),
    (2, 1, "NET120", "Networks and Systems", "enrolled"),
    (3, 1, "DAT110", "Data Literacy", "enrolled"),
    (4, 2, "CSC130", "Programming Principles", "enrolled"),
    (5, 2, "NET120", "Networks and Systems", "enrolled"),
    (6, 3, "MED105", "Digital Storytelling", "enrolled"),
    (7, 4, "SYS210", "Information Systems Design", "enrolled"),
    (8, 5, "SEC101", "Foundations of Security", "enrolled"),
]

EMAILS = [
    (
        1,
        "Student Services <services@westbridge.example>",
        "kim.park@students.westbridge.example",
        "Welcome to Westbridge",
        "Welcome, Kim. Your fictional student account is ready for the new term.",
        "2026-09-02T09:15:00",
        "read",
    ),
    (
        2,
        "Course Office <course.office@westbridge.example>",
        "kim.park@students.westbridge.example",
        "SEC101 reading list",
        "The SEC101 reading list is available from the local course documents folder.",
        "2026-09-04T11:30:00",
        "unread",
    ),
    (
        3,
        "Library Desk <library@westbridge.example>",
        "kim.park@students.westbridge.example",
        "Library account reminder",
        "This is a fictional reminder to review your library account preferences.",
        "2026-09-08T14:05:00",
        "unread",
    ),
    (
        4,
        "Kim Park <kim.park@students.westbridge.example>",
        "services@westbridge.example",
        "Campus access question",
        "Could you confirm the process for replacing a student access card?",
        "2026-09-10T08:40:00",
        "read",
    ),
    (
        5,
        "IT Helpdesk <helpdesk@westbridge.example>",
        "kim.park@students.westbridge.example",
        "Request received: access card",
        "Your fictional request has been added to the student support queue.",
        "2026-09-10T10:12:00",
        "unread",
    ),
]

TICKETS = [
    (
        1,
        1,
        "Student access card replacement",
        "Kim asked how to replace a student access card.",
        "open",
        "2026-09-10T08:45:00",
    ),
    (
        2,
        2,
        "Course portal access",
        "Avery cannot see the CSC130 course page in the fictional portal.",
        "in_progress",
        "2026-09-11T13:20:00",
    ),
    (
        3,
        4,
        "Update contact preference",
        "Samira requested a change to a fictional student contact preference.",
        "resolved",
        "2026-09-06T15:00:00",
    ),
]


def initialize_database(database_path: Path = DEFAULT_DATABASE_PATH) -> Path:
    """Recreate the database schema and insert the fictional seed records."""
    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        with connection:
            connection.executemany(
                "INSERT INTO students VALUES (?, ?, ?, ?, ?, ?)", STUDENTS
            )
            connection.executemany(
                "INSERT INTO enrollments VALUES (?, ?, ?, ?, ?)", ENROLLMENTS
            )
            connection.executemany(
                "INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?)", EMAILS
            )
            connection.executemany(
                "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)", TICKETS
            )
    finally:
        connection.close()

    return database_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"database file to recreate (default: {DEFAULT_DATABASE_PATH})",
    )
    database_path = initialize_database(parser.parse_args().database)
    print(f"Initialized fictional Westbridge database: {database_path}")


if __name__ == "__main__":
    main()
