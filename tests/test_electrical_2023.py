"""Regression tests for IEC2 insertion and the actual MCP tool schema."""
import asyncio
import math
from unittest.mock import MagicMock, patch

import pytest

from src.tools import electrical


@pytest.fixture(autouse=True)
def valid_project_for_insertion_unit_tests():
    # Project safety is covered separately; these tests isolate COM placement.
    with patch('src.tools.project_validation.require_valid_project'):
        yield


@pytest.fixture
def library(tmp_path, monkeypatch):
    for name in ("VCR21.dwg", "VCR22.dwg"):
        (tmp_path / name).touch()
    monkeypatch.setattr(electrical, "IEC2_LIBRARY", tmp_path)
    return tmp_path


@pytest.mark.parametrize("name,file", [
    ("contacto normalmente abierto", "VCR21.dwg"),
    (" CONTACTO  NA ", "VCR21.dwg"),
    ("contacto no", "VCR21.dwg"),
    ("contacto normalmente cerrado", "VCR22.dwg"),
    ("contacto NC", "VCR22.dwg"),
])
def test_semantic_insertion(library, name, file):
    conn = MagicMock()
    conn.get_model_space.return_value.InsertBlock.return_value.Handle = "123"
    conn.get_model_space.return_value.InsertBlock.return_value.GetAttributes.return_value = [MagicMock(TagString='TAG2')]
    with patch.object(electrical, "_get_conn", return_value=conn):
        result = electrical.insert_component(name, 10, 20, 2, 90, attributes={"TAG2": "KM1"})
    assert result["success"] is True
    assert result["handle"] == "123"
    args = conn.get_model_space.return_value.InsertBlock.call_args.args
    assert args[1] == str(library / file)
    assert args[2:5] == (2, 2, 2)
    assert args[5] == pytest.approx(math.pi / 2)
    conn.send_command.assert_not_called()


@pytest.mark.parametrize("scale,rotation", [(0, 0), (-1, 0), (1, float("nan")), (float("inf"), 0)])
def test_invalid_geometry(library, scale, rotation):
    with patch.object(electrical, "_get_conn") as connect:
        assert not electrical.insert_component("contacto NA", 0, 0, scale, rotation)["success"]
        connect.assert_not_called()


def test_missing_unknown_and_path_rejected(library):
    with patch.object(electrical, "_get_conn") as connect:
        for result in (
            electrical.insert_component("unknown", 0, 0),
            electrical.insert_electrical_symbol("missing", 0, 0),
            electrical.insert_electrical_symbol("../VCR21.dwg", 0, 0),
        ):
            assert result["success"] is False
        connect.assert_not_called()


def test_attributes_target_returned_block(library):
    conn = MagicMock()
    block = conn.get_model_space.return_value.InsertBlock.return_value
    attr = MagicMock(TagString="TAG2")
    block.GetAttributes.return_value = [attr]
    with patch.object(electrical, "_get_conn", return_value=conn):
        result = electrical.insert_electrical_symbol("VCR22.dwg", 0, 0, attributes={"TAG2": "K1"})
    assert result["success"] and result["attributes_set"] == 1
    assert attr.TextString == "K1"
    attr.Update.assert_called_once()


def test_com_failure_is_error(library):
    conn = MagicMock()
    conn.get_model_space.return_value.InsertBlock.side_effect = RuntimeError("COM unavailable")
    with patch.object(electrical, "_get_conn", return_value=conn):
        result = electrical.insert_component("contacto NC", 0, 0, attributes={"TAG2": "KM1"})
    assert not result["success"]
    assert "COM unavailable" in result["error"]


def test_busy_autocad_does_not_insert(library):
    conn = MagicMock()
    conn.get_application.return_value.GetAcadState.return_value.IsQuiescent = False
    with patch.object(electrical, "_get_conn", return_value=conn):
        result = electrical.insert_component("contacto NA", 0, 0, attributes={"TAG2": "KM1"})
    assert not result["success"]
    assert "ocupado" in result["error"]
    conn.get_model_space.assert_not_called()


def test_catalog_uses_real_files(library):
    result = electrical.get_symbol_list("contacts")
    assert result["symbols"] == ["VCR21", "VCR22"]


def test_missing_identity_or_inherited_reference_blocks_before_insert(library):
    conn = MagicMock()
    with patch.object(electrical, '_get_conn', return_value=conn):
        for attrs in ({}, {'TAG2': 'KM1', 'XREF': 'foreign-sheet'}):
            assert not electrical.insert_component('contacto NA', 0, 0, attributes=attrs)['success']
    conn.get_model_space.return_value.InsertBlock.assert_not_called()


def test_missing_tag_attribute_rolls_back_new_instance(library):
    conn = MagicMock()
    block = conn.get_model_space.return_value.InsertBlock.return_value
    block.GetAttributes.return_value = []
    with patch.object(electrical, '_get_conn', return_value=conn):
        assert not electrical.insert_component('contacto NA', 0, 0, attributes={'TAG2': 'KM1'})['success']
    block.Delete.assert_called_once()


def test_cached_reference_is_cleared_on_new_instance(library):
    conn = MagicMock()
    block = conn.get_model_space.return_value.InsertBlock.return_value
    tag = MagicMock(TagString='TAG2')
    reference = MagicMock(TagString='XREF', TextString='old-sheet')
    block.GetAttributes.return_value = [tag, reference]
    with patch.object(electrical, '_get_conn', return_value=conn):
        assert electrical.insert_component('contacto NA', 0, 0, attributes={'TAG2': 'KM1'})['success']
    assert reference.TextString == ''


def test_mcp_registration_and_dispatch(library):
    from src.server import mcp

    async def check():
        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["insert_component"].inputSchema
        assert set(schema["required"]) == {"component_type", "x", "y"}
        assert "VCR21" in tools["insert_component"].description
        assert "scale" in tools["insert_electrical_symbol"].inputSchema["properties"]
        conn = MagicMock()
        conn.get_model_space.return_value.InsertBlock.return_value.Handle = "MCP123"
        conn.get_model_space.return_value.InsertBlock.return_value.GetAttributes.return_value = [MagicMock(TagString='TAG2')]
        with patch.object(electrical, "_get_conn", return_value=conn):
            result = await mcp.call_tool("insert_component", {"component_type": "contacto NC", "x": 0, "y": 0, "attributes": {"TAG2": "KM1"}})
        assert "MCP123" in str(result)
        assert "VCR22.dwg" in str(result)

    asyncio.run(check())
