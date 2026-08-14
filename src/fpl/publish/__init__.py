"""The BI publish boundary.

Everything downstream of this package -- dashboards, notebooks, external BI tools -- reads an
atomic, read-only export and never queries the mutable production DuckDB. This package owns the
versioned semantic contract that export must satisfy, and later the exporter itself.
"""

from __future__ import annotations
