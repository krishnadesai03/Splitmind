from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from .database import engine
from .models import db as models
from .routes import receipts, expenses

models.Base.metadata.create_all(bind=engine)

_INDEX_HTML = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")

app = FastAPI(
    title="AI Bill Splitter API",
    description="Upload receipts, split bills with voice",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(receipts.router)
app.include_router(expenses.router)


@app.get("/", response_class=HTMLResponse)
def root():
    return _INDEX_HTML
