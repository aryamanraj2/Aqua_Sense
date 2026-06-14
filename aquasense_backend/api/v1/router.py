"""
API v1 Router - Aggregates all endpoint routers
"""
from fastapi import APIRouter
from api.v1.endpoints import tanks, products, analysis, voice_agent, nodes

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(tanks.router, prefix="/tanks", tags=["Tanks"])
api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(products.orders_router, prefix="/orders", tags=["Orders"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["Analysis"])
api_router.include_router(voice_agent.router, prefix="/voice", tags=["Voice Agent"])
api_router.include_router(nodes.router, prefix="/nodes", tags=["Sentinel Nodes"])
