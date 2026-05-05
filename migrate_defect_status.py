import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def migrate():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Check if column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='qc_defect' and column_name='status';
            """)
            if not cur.fetchone():
                print("Adding 'status' column to qc_defect...")
                cur.execute("ALTER TABLE public.qc_defect ADD COLUMN status VARCHAR(50);")
                conn.commit()
                print("Done.")
            else:
                print("Column 'status' already exists.")

if __name__ == "__main__":
    migrate()
