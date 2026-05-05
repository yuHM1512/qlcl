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
                WHERE table_name='qc_error_log' and column_name='date';
            """)
            if not cur.fetchone():
                print("Adding 'date' column to qc_error_log...")
                cur.execute("ALTER TABLE public.qc_error_log ADD COLUMN date DATE;")
                print("Filling existing records...")
                # Note: created_at might be timestamp with time zone. Casting to date directly.
                cur.execute("UPDATE public.qc_error_log SET date = (created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date WHERE date IS NULL;")
                
                # Make it required for the future
                # cur.execute("ALTER TABLE public.qc_error_log ALTER COLUMN date SET NOT NULL;")
                
                conn.commit()
                print("Done.")
            else:
                print("Column 'date' already exists.")

if __name__ == "__main__":
    migrate()
