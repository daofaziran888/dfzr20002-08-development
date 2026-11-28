"""业务路由汇总：通用资源路由 + 跨模块会展引擎。"""
from __future__ import annotations

from app.routers.resource import router as resource_router
from app.routers.exhibition_routes import exhibition_router
from app.routers.power_routes import router as power_router

# Match fixed exhibition paths before /api/{module}/{entry_id}.
ROUTERS = [power_router, exhibition_router, resource_router]
