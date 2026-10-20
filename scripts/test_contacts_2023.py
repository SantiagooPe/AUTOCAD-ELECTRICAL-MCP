"""Live MCP contact insertion check in a temporary unsaved drawing.

Run with AutoCAD Electrical 2023 open: python -m scripts.test_contacts_2023
"""
import asyncio

from src.autocad.connection import get_connection
from src.server import mcp


async def main():
    conn = get_connection()
    app = conn.get_application()
    print("COM version:", app.Version)
    if not app.GetAcadState().IsQuiescent:
        raise RuntimeError("AutoCAD está ocupado: terminá el comando o cerrá el diálogo y reintentá.")
    try:
        previous = app.ActiveDocument
    except Exception:
        previous = None
    doc = app.Documents.Add()
    # AutoCAD briefly rejects automation while initializing a new drawing.
    await asyncio.sleep(3)
    try:
        for index, (kind, symbol) in enumerate([
            ("contacto normalmente abierto", "VCR21"),
            ("contacto normalmente cerrado", "VCR22"),
        ]):
            result = await mcp.call_tool("insert_component", {
                "component_type": kind, "x": index * 50, "y": 0,
            })
            print("MCP result:", result)
            if isinstance(result, tuple):
                assert result[1]["success"], result[1]
            assert doc.ModelSpace.Count == index + 1
            block = doc.ModelSpace.Item(index)
            assert block.Name.upper() == symbol
            assert abs(block.XScaleFactor - 2) < 1e-9
            assert tuple(block.InsertionPoint) == (index * 50, 0, 0)
            print("Verified:", block.Name, block.Handle)
    finally:
        await asyncio.sleep(2)
        doc.Close(False)
        if previous is not None:
            previous.Activate()
    print("LIVE MCP INSERTION PASSED; temporary drawing closed without saving")


if __name__ == "__main__":
    asyncio.run(main())
