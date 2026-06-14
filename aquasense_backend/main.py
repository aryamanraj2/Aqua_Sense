"""
AquaSense Backend - FastAPI Application Entry Point
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config.database import engine, Base
from api.v1.router import api_router

# Import all models so SQLAlchemy knows about them before creating tables
from models.user import User
from models.tank import Tank
from models.water_quality import WaterQuality
from models.product import Product
from models.order import Order
from models.node import Node, Telemetry, Command, CommandAck

# Configure logging to show in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.StreamHandler()  # Output to console/terminal
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup: Create database tables
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")

    yield

    # Shutdown: Clean up resources
    print("Shutting down AquaSense backend")


app = FastAPI(
    title="AquaSense API",
    description="Aquaculture Management System Backend",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local development; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """
    Root endpoint - Health check
    """
    return {
        "message": "AquaSense API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {
        "status": "healthy",
        "service": "AquaSense Backend"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
