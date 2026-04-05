"""netlist_gen helpers (LIB-004 BOM profiles)."""

from openhac.compiler.netlist_gen import BOM_PROFILE_PROD_OMITTED_COLUMNS, bom_fieldnames_for_profile


def test_bom_fieldnames_prod_omits_internal_columns():
    dev = bom_fieldnames_for_profile(None)
    prod = bom_fieldnames_for_profile("production")
    assert len(prod) < len(dev)
    assert not (set(prod) & BOM_PROFILE_PROD_OMITTED_COLUMNS)
