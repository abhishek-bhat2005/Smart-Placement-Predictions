#!/usr/bin/env python
"""
migrate_to_mongo.py

Idempotent migration script to copy users and predictions from local SQLite `users.db`
into MongoDB (`placement_app` database). Uses `MONGO_URI` environment variable.

Usage (Windows PowerShell):
  $env:MONGO_URI='your full uri here'
  py migrate_to_mongo.py --dry-run   # show what would be inserted
  py migrate_to_mongo.py             # perform migration

The script creates indexes: users.email (unique), predictions.user_email, predictions.created_at
"""
import os
import sqlite3
import argparse
from datetime import datetime

try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
except Exception:
    raise SystemExit("pymongo is required. Install with: py -m pip install pymongo")


def parse_args():
    p = argparse.ArgumentParser(description="Migrate SQLite users.db -> MongoDB placement_app")
    p.add_argument("--db", default="users.db", help="Path to local SQLite DB (default users.db)")
    p.add_argument("--dry-run", action="store_true", help="Don't insert, just report counts")
    return p.parse_args()


def connect_mongo():
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI environment variable is not set")
    client = MongoClient(uri)
    # prefer default db name if provided in URI, otherwise use placement_app
    db = client.get_default_database()
    if db is None:
        db = client["placement_app"]
    return client, db


def read_sqlite_users(conn):
    cur = conn.cursor()
    cur.execute("SELECT username, email, password_hash, is_admin, last_login FROM users")
    rows = cur.fetchall()
    users = []
    for r in rows:
        users.append({
            "username": r[0],
            "email": r[1],
            "password_hash": r[2],
            "is_admin": bool(r[3]) if r[3] is not None else False,
            "last_login": r[4],
        })
    return users


def read_sqlite_predictions(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT user_email, name, age, gender, stream, internships, hostel, backlog, cgpa, prediction, eligibility_notes, created_at FROM predictions"
    )
    rows = cur.fetchall()
    preds = []
    for r in rows:
        created = r[11]
        # try to convert sqlite timestamp to python datetime
        if isinstance(created, str):
            try:
                created_dt = datetime.fromisoformat(created)
            except Exception:
                try:
                    created_dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    created_dt = None
        else:
            created_dt = created
        preds.append({
            "user_email": r[0],
            "name": r[1],
            "age": r[2],
            "gender": r[3],
            "stream": r[4],
            "internships": r[5],
            "hostel": r[6],
            "backlog": r[7],
            "cgpa": float(r[8]) if r[8] is not None else None,
            "prediction": int(r[9]) if r[9] is not None else None,
            "eligibility_notes": r[10],
            "created_at": created_dt,
        })
    return preds


def ensure_indexes(db):
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.predictions.create_index([("user_email", ASCENDING)])
    db.predictions.create_index([("created_at", DESCENDING)])


def migrate(db, users, preds, dry_run=False):
    inserted_users = 0
    inserted_preds = 0

    for u in users:
        q = {"email": u["email"]}
        if dry_run:
            exists = db.users.find_one(q) is not None
        else:
            exists = db.users.find_one(q) is not None
        if not exists:
            if dry_run:
                inserted_users += 1
            else:
                db.users.insert_one({
                    "username": u["username"],
                    "email": u["email"],
                    "password_hash": u["password_hash"],
                    "is_admin": u["is_admin"],
                    "last_login": u["last_login"],
                    "created_at": datetime.utcnow(),
                })
                inserted_users += 1

    for p in preds:
        # avoid duplicate by matching on user_email + created_at + cgpa
        q = {"user_email": p["user_email"], "cgpa": p.get("cgpa"), "created_at": p.get("created_at")}
        if p.get("created_at") is None:
            # if no created_at, match on user_email+cgpa+name+age
            q = {"user_email": p["user_email"], "cgpa": p.get("cgpa"), "name": p.get("name"), "age": p.get("age")}
        exists = db.predictions.find_one(q) is not None
        if not exists:
            if dry_run:
                inserted_preds += 1
            else:
                doc = p.copy()
                if doc.get("created_at") is None:
                    doc["created_at"] = datetime.utcnow()
                db.predictions.insert_one(doc)
                inserted_preds += 1

    return inserted_users, inserted_preds


def main():
    args = parse_args()
    if args.dry_run:
        print("Running dry-run migration (no writes)")

    if not os.path.exists(args.db):
        raise SystemExit(f"SQLite DB not found: {args.db}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    users = read_sqlite_users(conn)
    preds = read_sqlite_predictions(conn)

    print(f"Found {len(users)} users and {len(preds)} predictions in {args.db}")

    client, db = connect_mongo()
    print("Connected to MongoDB database:", db.name)

    ensure_indexes(db)
    print("Ensured indexes on users.email and predictions.user_email, created_at")

    u_count, p_count = migrate(db, users, preds, dry_run=args.dry_run)
    print(f"To insert (users, predictions): {u_count}, {p_count}")

    if not args.dry_run:
        print("Migration complete.")
    else:
        print("Dry-run finished. Rerun without --dry-run to perform migration.")


if __name__ == "__main__":
    main()
