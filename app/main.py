import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError

CONTADOR_ID = "singleton"

_mongo: Optional[MongoClient] = None


def _collection():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise HTTPException(
            status_code=503,
            detail="MONGODB_URI não configurado",
        )
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(
            uri,
            serverSelectionTimeoutMS=8000,
            maxPoolSize=10,
        )
    db_name = os.environ.get("MONGODB_DB", "pinga_ana")
    return _mongo[db_name]["contador"]


app = FastAPI(title="pinga-ana-adventure-demo-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.api_route("/contador", methods=["GET", "POST"])
def incrementar_contador():
    try:
        doc = _collection().find_one_and_update(
            {"_id": CONTADOR_ID},
            {"$inc": {"valor": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            raise HTTPException(status_code=500, detail="contador indisponível")
        return {"valor": int(doc["valor"])}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/contador/total")
def total_contador():
    try:
        doc = _collection().find_one({"_id": CONTADOR_ID})
        valor = int(doc["valor"]) if doc else 0
        return {"total": valor}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
