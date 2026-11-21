import os
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tr_operativos")

if MONGO_URI:
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000
    )
    db = client[MONGO_DB_NAME]
else:
    client = None
    db = None


def check_connection():
    if client is None:
        raise RuntimeError("No se encontro MONGO_URI en el archivo .env")

    client.admin.command("ping")
    return True
