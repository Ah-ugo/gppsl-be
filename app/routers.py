"""Registry of the routers added by each phase. Phases append here."""
from app.modules.ai.router import router as ai_router
from app.modules.contracts.router import router as contracts_router
from app.modules.crm.router import router as crm_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.documents.router import router as documents_router
from app.modules.equipment.router import router as equipment_router
from app.modules.finance.router import router as finance_router
from app.modules.hse.router import router as hse_router
from app.modules.inventory.router import router as inventory_router
from app.modules.issues.router import router as issues_router
from app.modules.logistics.router import router as logistics_router
from app.modules.projects.reports import router as reports_router
from app.modules.projects.router import router as projects_router
from app.modules.staff.attendance import router as attendance_router
from app.modules.staff.router import router as staff_router

extra_routers: list = [
    crm_router,
    inventory_router,
    contracts_router,
    logistics_router,
    hse_router,
    issues_router,
    equipment_router,
    projects_router,
    reports_router,
    finance_router,
    dashboard_router,
    staff_router,
    attendance_router,
    documents_router,
    ai_router,
]
