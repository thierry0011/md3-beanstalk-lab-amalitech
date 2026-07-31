import os

import psycopg2
from flask import Flask, jsonify

application = Flask(__name__)

VERSION_FILE = os.path.join(os.path.dirname(__file__), "version.txt")
try:
    with open(VERSION_FILE) as f:
        VERSION = f.read().strip()
except FileNotFoundError:
    VERSION = "dev"


def get_db_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


@application.route("/")
def index():
    return jsonify(status="ok", message="Deployment successful", version=VERSION)


@application.route("/visits")
def visits():
    conn = get_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS visits (
                    id SERIAL PRIMARY KEY,
                    visited_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute("INSERT INTO visits DEFAULT VALUES")
            cur.execute("SELECT COUNT(*) FROM visits")
            row = cur.fetchone()
            count = row[0] if row else 0
        return jsonify(status="ok", visits=count)
    finally:
        conn.close()


if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8000)
