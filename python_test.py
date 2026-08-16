import os, sys, time
from dotenv import load_dotenv
load_dotenv()
import psycopg2

dsn = os.environ.get("READONLY_DATABASE_URL")
print("Connecting with 10s timeout...")
start = time.time()
try:
    conn = psycopg2.connect(dsn, connect_timeout=10)
    print(f"Connected in {time.time()-start:.2f}s")
    cur = conn.cursor()
    cur.execute("SELECT current_user, current_database();")
    print(cur.fetchone())
    conn.close()
except Exception as e:
    print(f"Failed after {time.time()-start:.2f}s: {e}")