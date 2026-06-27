from .health import router as health_router
from .events import router as events_router
from .entities import router as entities_router
from .identities import router as identities_router
from .decisions import router as decisions_router

__all__ = [
    "health_router",
    "events_router",
    "entities_router",
    "identities_router",
    "decisions_router",
]
