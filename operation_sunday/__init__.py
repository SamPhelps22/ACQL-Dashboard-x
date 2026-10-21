"""Operation Sunday: weekly learning, model selection and the Thursday forecast lock.

A research and shadow-production workflow. It reads data and, read-only, the
ACQL pool rules (acql.model.backtest, acql.analytics). It never writes to the
dashboard's database, never changes Deadeye's pricing, and never touches the
public site. Everything it keeps lives under its own state folder.

See operation_sunday/docs/ for the audit, the plan and the operating guide.
"""

__version__ = "1.0.0"
