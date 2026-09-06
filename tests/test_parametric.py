"""Tests for Phase 3: Parametric Submodules & Supply Chain Resiliency."""

from openhac.core.board import Board
from openhac.stdlib.power import SwitchingRegulator
from openhac.core.compile_context import OpenHaCCompileContext, compile_context_set, compile_context_reset

def test_parametric_switching_regulator(tmp_db, monkeypatch):
    """Test that an abstract SwitchingRegulator resolves to a real IC and injects passives."""
    # tmp_db returns (db_path, DatabaseManager_instance)
    db_path, db = tmp_db
    
    # Force the ParametricModule to use our tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    # Also override the module-level DB_PATH in db_manager so instances use it
    from openhac.database import db_manager
    monkeypatch.setattr(db_manager, "DB_PATH", db_path)
    
    # We need to insert a mock PMIC in the DB so parametric_search finds it
    db.insert_component({
        "generic_name": "TPS54302DDCR",
        "category": "Power Management",
        "description": "5V, 3A, 28V, 400kHz Synchronous Step-Down Converter",
        "manufacturer": "Texas Instruments",
        "mpn": "TPS54302DDCR",
        "package": "SOT-23-6",
        "kicad_symbol": "Regulator_Switching:TPS54302",
        "kicad_footprint": "Package_TO_SOT_SMD:SOT-23-6",
        # Pin mapping keys for TPS54302
        "pinout_json": '[{"num": "1", "name": "GND"}, {"num": "2", "name": "VIN"}, {"num": "3", "name": "SW"}, {"num": "4", "name": "FB"}, {"num": "5", "name": "EN"}, {"num": "6", "name": "BOOT"}]'
    }, ignore_duplicate=True)
    
    board = Board(size_mm=(50, 50))
    ctx = OpenHaCCompileContext(board)
    tok = compile_context_set(ctx)
    
    try:
        # Create an abstract parametric regulator, forcing it to find our mock by filtering for mpn
        reg = SwitchingRegulator(
            "Main_Power",
            v_in_nominal=12.0,
            v_out=5.0,
            current_min=3.0,
            mpn="TPS54302DDCR",
            l_value="4.7uH",
        )
        board.add_module(reg)
        
        # It should not have inner components yet (aside from its interface nets)
        assert len(reg.components) == 0, "Parametric module should not instantiate ICs before resolve()"
        
        # Manually call resolve for unit testing (Board.compile calls this normally)
        reg.resolve()
        
        # It should now be populated with the IC, Inductor, and Capacitors
        assert len(reg.components) == 4, "Should inject exactly 1 IC and 3 passives (L, Cin, Cout)"
        
        ic = next((c for c in reg.components if c.refdes == "U_REG"), None)
        assert ic is not None
        assert "TPS54302" in ic.fields.get("Value", ""), "Should have resolved the TI buck converter"
        
        inductor = next((c for c in reg.components if c.refdes == "L1"), None)
        assert inductor is not None
        assert "4.7uH" in inductor.fields.get("Value", ""), "Should have calculated 4.7uH for a 3A buck"
        
        # Verify wiring (e.g. SW node connects to Inductor Pin 1)
        sw_net = ic["3"].net
        assert sw_net is not None
        assert inductor["1"].net == sw_net, "Inductor should be connected to the SW pin (3)"
        
        # Verify subsequent calls to resolve() are idempotent
        reg.resolve()
        assert len(reg.components) == 4
        
    finally:
        compile_context_reset(tok)
