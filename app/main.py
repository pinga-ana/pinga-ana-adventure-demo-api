import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CONTADOR_ID = "singleton"

_mongo: Optional[MongoClient] = None


def _require_mongo_uri() -> str:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise HTTPException(
            status_code=503,
            detail="MONGODB_URI não configurado",
        )
    return uri


def _get_mongo() -> MongoClient:
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(
            _require_mongo_uri(),
            serverSelectionTimeoutMS=8000,
            maxPoolSize=10,
        )
    return _mongo


def _db():
    db_name = os.environ.get("MONGODB_DB", "pinga_ana")
    return _get_mongo()[db_name]


def _collection_contador():
    return _db()["contador"]


def _collection_partidas():
    name = os.environ.get("MONGODB_PARTIDAS_COLLECTION", "partidas")
    return _db()[name]


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


app = FastAPI(title="pinga-ana-adventure-demo-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PartidaCreate(BaseModel):
    pontuacao: int = Field(ge=0, description="Pontuação final da partida")
    device: str = Field(
        min_length=1,
        max_length=128,
        description="Origem: local, navegador_pc, navegador_celular, etc.",
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.api_route("/contador", methods=["GET", "POST"])
def incrementar_contador():
    try:
        doc = _collection_contador().find_one_and_update(
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
        doc = _collection_contador().find_one({"_id": CONTADOR_ID})
        valor = int(doc["valor"]) if doc else 0
        return {"total": valor}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/partidas")
def registar_partida(payload: PartidaCreate, request: Request):
    """Grava ip (servidor), device e pontuação enviados pelo cliente; timestamp em UTC."""
    try:
        doc = {
            "ip": _client_ip(request),
            "device": payload.device,
            "pontuacao": payload.pontuacao,
            "timestamp": datetime.now(timezone.utc),
        }
        result = _collection_partidas().insert_one(doc)
        return {"id": str(result.inserted_id)}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
