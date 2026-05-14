import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
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


def _iso_utc(dt: Any) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _analytics_report(limit_recentes: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    coll = _collection_partidas()

    contador_doc = _collection_contador().find_one({"_id": CONTADOR_ID})
    invoc = int(contador_doc["valor"]) if contador_doc else 0

    total = coll.count_documents({})
    ultimas_24h = coll.count_documents({"timestamp": {"$gte": day_ago}})
    ultimos_7d = coll.count_documents({"timestamp": {"$gte": week_ago}})

    agg_global = list(
        coll.aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "max_p": {"$max": "$pontuacao"},
                        "avg_p": {"$avg": "$pontuacao"},
                    }
                }
            ]
        )
    )
    row_g = agg_global[0] if agg_global else {}
    max_p = int(row_g["max_p"]) if row_g.get("max_p") is not None else 0
    avg_p = round(float(row_g["avg_p"]), 2) if row_g.get("avg_p") is not None else 0.0

    por_device_raw = list(
        coll.aggregate(
            [
                {
                    "$group": {
                        "_id": "$device",
                        "partidas": {"$sum": 1},
                        "pontuacao_maxima": {"$max": "$pontuacao"},
                        "pontuacao_media": {"$avg": "$pontuacao"},
                    }
                },
                {"$sort": {"partidas": -1}},
            ]
        )
    )
    por_device: list[dict[str, Any]] = []
    for r in por_device_raw:
        pm = r.get("pontuacao_media")
        por_device.append(
            {
                "device": r.get("_id") or "unknown",
                "partidas": int(r.get("partidas", 0)),
                "pontuacao_maxima": int(r["pontuacao_maxima"])
                if r.get("pontuacao_maxima") is not None
                else 0,
                "pontuacao_media": round(float(pm), 2) if pm is not None else 0.0,
            }
        )

    ultimas_partidas: list[dict[str, Any]] = []
    for d in coll.find({}).sort("timestamp", -1).limit(limit_recentes):
        ts = d.get("timestamp")
        b_raw = d.get("build")
        build_out: int | None
        if b_raw is None:
            build_out = None
        else:
            try:
                build_out = int(b_raw)
            except (TypeError, ValueError):
                build_out = None
        ultimas_partidas.append(
            {
                "id": str(d["_id"]),
                "ip": d.get("ip"),
                "device": d.get("device"),
                "personagem": d.get("personagem"),
                "build": build_out,
                "pontuacao": int(d.get("pontuacao", 0)),
                "timestamp": _iso_utc(ts) if ts is not None else None,
            }
        )

    return {
        "gerado_em": now.isoformat(),
        "contador_invocacoes": invoc,
        "partidas": {
            "total": total,
            "ultimas_24h": ultimas_24h,
            "ultimos_7_dias": ultimos_7d,
            "pontuacao_maxima": max_p,
            "pontuacao_media": avg_p,
            "por_device": por_device,
        },
        "ultimas_partidas": ultimas_partidas,
    }


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
    personagem: str | None = Field(
        default=None,
        max_length=64,
        description="Identificador do personagem usado na partida (ex.: id em game_config).",
    )
    build: int | None = Field(
        default=None,
        ge=0,
        description="Número de build do cliente (ex.: CI / build_params.json).",
    )

    @field_validator("personagem", mode="before")
    @classmethod
    def _personagem_strip(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return None


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


@app.get("/analytics")
def get_analytics(
    limit: int = Query(20, ge=1, le=100, description="Número de partidas recentes no relatório"),
):
    """Relatório agregado: totais, janelas 24h/7d, estatísticas de pontuação, repartição por device e últimas partidas (com personagem/build quando existirem)."""
    try:
        return _analytics_report(limit_recentes=limit)
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/partidas")
def registar_partida(payload: PartidaCreate, request: Request):
    """Grava ip (servidor), device, pontuação e opcionalmente personagem/build; timestamp em UTC."""
    try:
        doc: dict[str, Any] = {
            "ip": _client_ip(request),
            "device": payload.device,
            "pontuacao": payload.pontuacao,
            "timestamp": datetime.now(timezone.utc),
        }
        if payload.personagem is not None:
            doc["personagem"] = payload.personagem
        if payload.build is not None:
            doc["build"] = payload.build
        result = _collection_partidas().insert_one(doc)
        return {"id": str(result.inserted_id)}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
