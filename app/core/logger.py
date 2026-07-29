import sys
from loguru import logger
from app.core.config import settings

# ─── Module name shortener ────────────────────────────────────────────────────
# Maps verbose module paths to short, readable labels shown in the terminal.
_MODULE_LABELS = {
    "app.services.ai_engine":     "AI      ",
    "app.services.vector_service":"QDRANT  ",
    "app.services.db_service":    "DB      ",
    "app.services.github_service":"GITHUB  ",
    "app.services.memory_service":"MEMORY  ",
    "app.api.ingest":             "INGEST  ",
    "app.api.sessions":           "SESSION ",
    "app.api.chat":               "CHAT    ",
    "app.api.documents":          "DOCS    ",
    "app.core.logger":            "SYSTEM  ",
    "main":                       "SERVER  ",
}

def _format(record):
    module  = record["name"]
    label   = _MODULE_LABELS.get(module, module[:8].upper().ljust(8))
    level   = record["level"].name

    # Pick a color per log level for the entire line
    if level == "DEBUG":
        line_color = "<dim>"
        end_color  = "</dim>"
        lvl_tag    = "<dim>DBG</dim>"
    elif level == "INFO":
        line_color = "<white>"
        end_color  = "</white>"
        lvl_tag    = "<cyan><bold>INF</bold></cyan>"
    elif level == "SUCCESS":
        line_color = "<green>"
        end_color  = "</green>"
        lvl_tag    = "<green><bold>✓ OK</bold></green>"
    elif level == "WARNING":
        line_color = "<yellow>"
        end_color  = "</yellow>"
        lvl_tag    = "<yellow><bold>WRN</bold></yellow>"
    elif level == "ERROR":
        line_color = "<red>"
        end_color  = "</red>"
        lvl_tag    = "<red><bold>ERR</bold></red>"
    elif level == "CRITICAL":
        line_color = "<red><bold>"
        end_color  = "</bold></red>"
        lvl_tag    = "<red><bold>CRT</bold></red>"
    else:
        line_color = ""
        end_color  = ""
        lvl_tag    = level[:3]

    # Module label gets a fixed color per category for quick visual grouping
    if label.strip() in ("QDRANT", "DB"):
        label_tag = f"<magenta>{label}</magenta>"
    elif label.strip() in ("AI",):
        label_tag = f"<blue><bold>{label}</bold></blue>"
    elif label.strip() in ("INGEST", "GITHUB"):
        label_tag = f"<green>{label}</green>"
    elif label.strip() in ("SESSION", "CHAT"):
        label_tag = f"<cyan>{label}</cyan>"
    elif label.strip() in ("MEMORY",):
        label_tag = f"<yellow>{label}</yellow>"
    elif label.strip() in ("SERVER", "SYSTEM"):
        label_tag = f"<dim>{label}</dim>"
    else:
        label_tag = f"<white>{label}</white>"

    fmt = (
        "<dim>{time:HH:mm:ss}</dim>"
        f" {lvl_tag}"
        f" <dim>│</dim> {label_tag} <dim>│</dim>"
        f" {line_color}{{message}}{end_color}"
        "\n{exception}"
    )
    return fmt


def setup_logger():
    logger.remove()

    # ── Console: colored, human-readable
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=_format,
        colorize=True,
    )

    # ── File: plain-text for grep/post-processing, DEBUG level
    logger.add(
        "logs/app.log",
        rotation="10 MB",
        retention="10 days",
        level="DEBUG",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        colorize=False,
    )


setup_logger()
logger.info("Logger initialized")
