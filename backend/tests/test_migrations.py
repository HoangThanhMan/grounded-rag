"""The Alembic migrations build exactly the schema the models describe."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from grounded_rag.db.models import Base

INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _config(url: str) -> Config:
    cfg = Config(str(INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _columns(path: Path) -> dict[str, set[str]]:
    engine = sa.create_engine(f"sqlite:///{path}")
    insp = sa.inspect(engine)
    out = {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}
    engine.dispose()
    out.pop("alembic_version", None)
    return out


def test_upgrade_matches_the_models_and_downgrade_empties(tmp_path):
    db = tmp_path / "m.db"
    cfg = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(cfg, "head")
    expected = {t.name: {c.name for c in t.columns} for t in Base.metadata.sorted_tables}
    assert _columns(db) == expected
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        # types, nullability, indexes: nothing autogenerate would still add
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    engine.dispose()
    command.downgrade(cfg, "base")
    assert _columns(db) == {}
