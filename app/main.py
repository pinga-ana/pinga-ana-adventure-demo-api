import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        app.state.dsn = normalize_database_url(dsn)
        with psycopg.connect(app.state.dsn) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contador (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    valor BIGINT NOT NULL DEFAULT 0,
                    CONSTRAINT contador_singleton CHECK (id = 1)
                );
                """
            )
            conn.execute(
                "INSERT INTO contador (id, valor) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;"
            )
    else:
        app.state.dsn = None
    yield


app = FastAPI(
    title="pinga-ana-adventure-demo-api",
    lifespan=lifespan,
)
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
    if not app.state.dsn:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL não configurado",
        )
    with psycopg.connect(app.state.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE contador SET valor = valor + 1 WHERE id = 1 RETURNING valor"
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="contador não inicializado")
    return {"valor": int(row[0])}


@app.get("/contador/total")
def total_contador():
    if not app.state.dsn:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL não configurado",
        )
    with psycopg.connect(app.state.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT valor FROM contador WHERE id = 1")
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="contador não inicializado")
    return {"total": int(row[0])}
