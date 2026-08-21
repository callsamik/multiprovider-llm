import ast
import inspect
from pathlib import Path

from multiprovider_llm import __all__ as PACKAGE_ALL
from multiprovider_llm.async_client import AsyncClient
from multiprovider_llm.client import Client
from multiprovider_llm.config import LibraryConfig
from multiprovider_llm.routing.types import Candidate


ROOT = Path(__file__).resolve().parents[1] / "src" / "multiprovider_llm"


def test_client_complete_has_no_routing_mode():
    assert "routing_mode" not in inspect.signature(Client.complete).parameters
    assert "routing_mode" not in inspect.signature(AsyncClient.acomplete).parameters


def test_library_config_has_no_routing_mode():
    assert "routing_mode" not in LibraryConfig.__dataclass_fields__


def test_smart_client_not_in_package_all():
    assert "SmartClient" not in PACKAGE_ALL


def test_candidate_has_no_pool_key():
    assert "pool_key" not in Candidate.__dataclass_fields__


def test_smart_client_source_forbids_retryable_and_ain_routing():
    text = (ROOT / "smart_client.py").read_text(encoding="utf-8")
    for needle in ("is_retryable", "tier_routing", "routing_mode", "routing_prior"):
        assert needle not in text


def test_routing_init_does_not_eager_import_ranking():
    tree = ast.parse((ROOT / "routing" / "__init__.py").read_text(encoding="utf-8"))
    eager = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {"rank", "pool", "scoring", "lkgp", "types"}:
            eager.append(node.module)
    assert eager == []


def test_experimental_modules_do_not_mention_ain_tier_routing():
    chain_py = ROOT / "routing" / "chain.py"
    hits = []
    paths = (
        list((ROOT / "catalog").rglob("*.py"))
        + list((ROOT / "routing").rglob("*.py"))
        + list((ROOT / "resilience").rglob("*.py"))
        + [ROOT / "smart_client.py"]
    )
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for needle in ("routing_mode", "routing_prior"):
            if needle in text:
                hits.append(f"{rel}:{needle}")
        if "tier_routing" in text and path != chain_py:
            hits.append(f"{rel}:tier_routing")
    assert hits == []
