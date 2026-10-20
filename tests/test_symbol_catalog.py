"""Semantic lookup uses real inventory, never requires COM or external services."""
import json
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from src.tools import electrical, symbol_catalog as catalog


@pytest.fixture
def symbols(tmp_path, monkeypatch):
    for stem, *_ in catalog.CONCEPTS:
        for orientation in "HV":
            (tmp_path / f"{orientation}{stem}.dwg").touch()
    (tmp_path / "custom.dwg").touch()
    monkeypatch.setattr(electrical, "IEC2_LIBRARY", tmp_path)
    return tmp_path


@pytest.mark.parametrize("query,code", [
    (" CONTACTO  NA ", "VCR21"), ("contacto NC", "VCR22"),
    ("BOBINA", "VCR1"), ("contactor", "VMS1"),
    ("pulsador NC", "VPB12"), ("motor trifasico", "VMO13"),
    ("RELÉ TÉRMICO", "VOL1"), ("temporizador a la conexion", "VTD1N"),
    ("temporizador a la desconexión", "VTD1F"), ("hcr21.DWG", "HCR21"),
])
def test_resolve(symbols, query, code):
    assert catalog.resolve(symbols, query)["symbol"] == code


@pytest.mark.parametrize("query", ["motor", "pulsador", "temporizador"])
def test_ambiguous_does_not_connect(symbols, query):
    with patch.object(electrical, "_get_conn") as connect:
        result = electrical.insert_component(query, 0, 0)
        assert not result["success"]
        assert "ambiguo" in result["error"]
        connect.assert_not_called()


def test_inventory_filters_and_case(symbols):
    assert len(catalog.search(symbols, "contacto NA", "horizontal")) == 1
    assert len(catalog.search(symbols, category="motors")) == 4
    assert catalog.resolve(symbols, "CUSTOM")["filename"] == "custom.dwg"
    (symbols / "VCR1.dwg").unlink()
    with pytest.raises(ValueError):
        catalog.resolve(symbols, "bobina")
    assert not electrical.search_symbols(orientation="diagonal")["success"]
    assert not electrical.search_symbols(limit=0)["success"]
    assert electrical.search_symbols(limit=1)["truncated"]


def test_all_concepts_insert_through_com(symbols):
    conn = MagicMock()
    with patch.object(electrical, "_get_conn", return_value=conn):
        for _, label, *_ in catalog.CONCEPTS:
            assert electrical.insert_component(label, 0, 0)["success"]
    assert conn.get_model_space.return_value.InsertBlock.call_count == len(catalog.CONCEPTS)


def test_portable_inventory_has_menu_evidence():
    data = json.loads(catalog.DATA.read_text(encoding="utf-8"))
    assert data["count"] == len(data["symbols"])
    for stem, *_ in catalog.CONCEPTS:
        assert data["symbols"]["V" + stem]["source"].startswith("ACE_IEC_MENU.DAT")


def test_mcp_search_registration(symbols):
    from src.server import mcp

    async def check():
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        assert "orientation" in tools["search_symbols"].inputSchema["properties"]
        result = await mcp.call_tool("search_symbols", {"query": "motor trifásico"})
        assert "VMO13" in str(result)
        assert "HMO13" in str(result)

    asyncio.run(check())
