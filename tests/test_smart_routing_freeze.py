import inspect
from pathlib import Path

from multiprovider_llm.async_client import AsyncClient
from multiprovider_llm.client import Client
from multiprovider_llm.config import LibraryConfig


def test_client_complete_has_no_routing_mode():
    assert "routing_mode" not in inspect.signature(Client.complete).parameters
    assert "routing_mode" not in inspect.signature(AsyncClient.acomplete).parameters


def test_library_config_has_no_routing_mode():
    assert "routing_mode" not in LibraryConfig.__dataclass_fields__


def test_smart_client_module_does_not_exist():
    root = Path(__file__).resolve().parents[1] / "src" / "multiprovider_llm"
    assert not (root / "smart_client.py").exists()


def test_experimental_modules_do_not_mention_ain_tier_routing():
    root = Path(__file__).resolve().parents[1] / "src" / "multiprovider_llm"
    hits = []
    paths = (
        list((root / "catalog").rglob("*.py"))
        + list((root / "routing").rglob("*.py"))
        + list((root / "resilience").rglob("*.py"))
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for needle in ("routing_mode", "routing_prior"):
            if needle in text:
                hits.append(f"{path.name}:{needle}")
        # tier_routing is legitimate in frozen chain.py (0.1.0 Client tier order).
        if needle := "tier_routing":
            if needle in text and path.name != "chain.py":
                hits.append(f"{path.name}:{needle}")
    assert hits == []
