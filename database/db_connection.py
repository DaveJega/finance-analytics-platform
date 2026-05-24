from sqlalchemy import create_engine

DATABASE_URL = "postgresql://postgres:08028408880@localhost:5432/finance_platform"

engine = create_engine(DATABASE_URL)

print("Database Connected")