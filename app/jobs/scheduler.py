"""APScheduler jobs (Africa/Lagos). Each job is a plain async function so tests can call it directly."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings

logger = logging.getLogger("gppsl.jobs")


async def daily_summary_job() -> int:
    """19:00: send the MD the day's summary."""
    from app.modules.dashboard.service import daily_summary
    from app.modules.notifications import notify_roles

    text = await daily_summary()
    try:  # Phase 9 upgrade: AI-written version when available
        from app.modules.ai.service import ai_daily_summary

        text = await ai_daily_summary() or text
    except ImportError:
        pass
    return await notify_roles(["md"], "Daily summary", text, "/", email=True)


async def morning_scan_job() -> int:
    """07:00: expiring certificates, overdue service, overdue invoices, unreturned rentals."""
    from app.modules.dashboard.service import alerts
    from app.modules.notifications import notify_roles

    found = await alerts()
    high = [a for a in found if a["severity"] == "high"]
    if not found:
        return 0
    body = f"{len(found)} item(s) need attention, {len(high)} urgent. " + "; ".join(a["title"] for a in high[:4])
    return await notify_roles(["md", "admin"], "Morning scan", body, "/")


async def signature_reminder_job() -> int:
    """Daily: remind signers whose turn it is."""
    try:
        from app.modules.documents.service import remind_pending_signers
    except ImportError:
        return 0
    return await remind_pending_signers()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=get_settings().timezone)
    scheduler.add_job(daily_summary_job, CronTrigger(hour=19, minute=0), id="daily_summary", replace_existing=True)
    scheduler.add_job(morning_scan_job, CronTrigger(hour=7, minute=0), id="morning_scan", replace_existing=True)
    scheduler.add_job(signature_reminder_job, CronTrigger(hour=9, minute=0), id="signature_reminders", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    return scheduler
