"""3D-006: footprint-keyed fill-in cache, not EasyEDA folder globs."""

from __future__ import annotations

from pathlib import Path


USB_FP = "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
SD_FP = "Connector_Card:microSD_HC_Molex_47219-2001"


def _empty_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "3dmodels"
    pack.mkdir()
    (pack / "empty.3dshapes").mkdir()
    return pack


def test_bundled_map_has_usbc_and_microsd():
    from openhac.database.threed_fillin import lcsc_for_footprint, load_fillin_map

    fmap = load_fillin_map()
    assert fmap[USB_FP]["source"] == "lcsc:C165948"
    assert fmap[SD_FP]["source"] == "lcsc:C164170"
    assert lcsc_for_footprint(USB_FP) == "C165948"
    assert lcsc_for_footprint(SD_FP) == "C164170"


def test_fillin_step_path_is_lib_name(monkeypatch, tmp_path):
    from openhac.database.threed_fillin import fillin_step_path, reset_fillin_map_cache

    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "3d_models"))
    reset_fillin_map_cache()
    dest = fillin_step_path(USB_FP)
    assert dest is not None
    assert dest.name == "USB_C_Receptacle_HRO_TYPE-C-31-M-12.step"
    assert dest.parent.name == "Connector_USB"


def test_install_and_pcb_attach(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import (
        fillin_step_path,
        install_fillin_step,
        reset_fillin_map_cache,
    )

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    src = tmp_path / "USB-C_SMD-TYPE-C-31-M-12_1.step"
    src.write_text("mesh\n", encoding="utf-8")
    installed = install_fillin_step(USB_FP, src)
    dest = fillin_step_path(USB_FP)
    assert dest is not None and dest.is_file()
    assert installed == str(dest.resolve())
    fn = pcb_3d_model_filename(USB_FP, str(tmp_path / "R0805.step"))
    assert fn == str(dest.resolve())


def test_seed_legacy_named_mesh_not_jedec_cube(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import fillin_step_path, reset_fillin_map_cache

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    cache = tmp_path / "easyeda_generated.3dshapes"
    cache.mkdir()
    (cache / "R0805.step").write_text("cube\n", encoding="utf-8")
    (cache / "USB-C_SMD-TYPE-C-31-M-12_1.step").write_text("usbc\n", encoding="utf-8")
    monkeypatch.setenv("OPENHAC_3D_CACHE_DIRS", str(cache))
    reset_fillin_map_cache()

    fn = pcb_3d_model_filename(USB_FP, str(cache / "R0805.step"))
    dest = fillin_step_path(USB_FP)
    assert dest is not None and dest.is_file()
    assert fn == str(dest.resolve())
    assert dest.read_text(encoding="utf-8") == "usbc\n"


def test_prefetch_map_sku_installs_stable_path(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import (
        fillin_step_path,
        prefetch_fillin_for_skus,
        reset_fillin_map_cache,
    )

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    downloaded = tmp_path / "C165948.step"
    downloaded.write_text("hro\n", encoding="utf-8")

    def fake_fetch(sku):
        assert sku == "C165948"
        return ("easyeda_generated:C165948", str(downloaded))

    monkeypatch.setattr(
        "openhac.database.easyeda_integration.generate_footprint_from_lcsc",
        fake_fetch,
    )
    attempted, updated = prefetch_fillin_for_skus(["C165948"])
    assert attempted == 1
    assert updated == 1
    dest = fillin_step_path(USB_FP)
    assert dest is not None and dest.is_file()
    assert dest.read_text(encoding="utf-8") == "hro\n"
    fn = pcb_3d_model_filename(USB_FP, None)
    assert fn == str(dest.resolve())


def test_extra_map_file_overrides(monkeypatch, tmp_path):
    from openhac.database.threed_fillin import lcsc_for_footprint, reset_fillin_map_cache

    extra = tmp_path / "extra.json"
    extra.write_text(
        '{"schema":"openhac.3d-fillin.v1","entries":{"Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12":{"source":"lcsc:C999999"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENHAC_3D_FILLIN_MAP", str(extra))
    reset_fillin_map_cache()
    assert lcsc_for_footprint(USB_FP) == "C999999"
    monkeypatch.delenv("OPENHAC_3D_FILLIN_MAP", raising=False)
    reset_fillin_map_cache()
    assert lcsc_for_footprint(USB_FP) == "C165948"


def test_catalog_3d_on_disk_uses_fillin_without_seeding(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import catalog_3d_is_on_disk
    from openhac.database.threed_fillin import fillin_step_path, reset_fillin_map_cache

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    cache = tmp_path / "easyeda_generated.3dshapes"
    cache.mkdir()
    (cache / "USB-C_SMD-TYPE-C-31-M-12_1.step").write_text("usbc\n", encoding="utf-8")
    monkeypatch.setenv("OPENHAC_3D_CACHE_DIRS", str(cache))
    reset_fillin_map_cache()
    row = {"kicad_footprint": USB_FP, "model_3d_local": ""}
    assert catalog_3d_is_on_disk(row) is False
    dest = fillin_step_path(USB_FP)
    assert dest is not None
    dest.parent.mkdir(parents=True)
    dest.write_text("usbc\n", encoding="utf-8")
    assert catalog_3d_is_on_disk(row) is True


def _board_with_parts(*items: tuple[str, str]):
    class _Part:
        def __init__(self, fp: str, mpn: str):
            self.footprint = fp
            self.fields = {"MPN": mpn} if mpn else {}
            self.mpn = mpn

    class _Comp:
        def __init__(self, fp: str, mpn: str):
            self.generic_name = mpn or fp
            self._comp_data = {"kicad_footprint": fp, "mpn": mpn}
            self.part = _Part(fp, mpn)

    class _Mod:
        def __init__(self, comps):
            self.components = comps

    class _Board:
        def __init__(self, comps):
            self.modules = [_Mod(comps)]

        def _get_all_modules(self):
            return self.modules

    return _Board([_Comp(fp, mpn) for fp, mpn in items])


SOIC4 = "Package_SO:SOIC-4_4.55x2.6mm_P1.27mm"
TP_FP = "TestPoint:TestPoint_Pad_D1.5mm"


def test_pick_lcsc_requires_mfr_match():
    from openhac.database.threed_fillin import pick_lcsc_matching_mpn

    items = [
        {"lcsc": 1, "mfr": "LM358", "stock": 9999},
        {"lcsc": 8150, "mfr": "PC817", "stock": 10},
    ]
    assert pick_lcsc_matching_mpn("PC817", items) == "C8150"
    assert pick_lcsc_matching_mpn("PC817", [{"lcsc": 1, "mfr": "LM358"}]) is None
    assert pick_lcsc_matching_mpn("PC8", items) is None


def test_discovered_does_not_override_bundled(monkeypatch, tmp_path):
    from openhac.database.threed_fillin import (
        lcsc_for_footprint,
        remember_discovered_lcsc,
        reset_fillin_map_cache,
    )

    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    remember_discovered_lcsc(USB_FP, "C00001", note="should not win")
    reset_fillin_map_cache()
    assert lcsc_for_footprint(USB_FP) == "C165948"


def test_prefetch_discovers_mpn_not_first_jlc_row(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import (
        discovered_map_path,
        fillin_step_path,
        lcsc_for_footprint,
        prefetch_fillin_from_board,
        reset_fillin_map_cache,
    )

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    monkeypatch.setenv("KICAD9_FOOTPRINT_DIR", str(tmp_path / "empty_fp"))
    reset_fillin_map_cache()
    downloaded = tmp_path / "PC817.step"
    downloaded.write_text("opto\n", encoding="utf-8")

    def fake_search(query: str):
        assert "PC817" in query
        return [
            {"lcsc": 1, "mfr": "UNRELATED-PART", "stock": 9999},
            {"lcsc": 8150, "mfr": "PC817", "stock": 10},
        ]

    def fake_fetch(sku):
        assert sku == "C8150"
        return ("easyeda_generated:C8150", str(downloaded))

    monkeypatch.setattr(
        "openhac.database.easyeda_integration.generate_footprint_from_lcsc",
        fake_fetch,
    )
    board = _board_with_parts((SOIC4, "PC817"))
    attempted, updated = prefetch_fillin_from_board(board, search=fake_search)
    assert attempted == 1
    assert updated == 1
    dest = fillin_step_path(SOIC4)
    assert dest is not None and dest.is_file()
    assert dest.read_text(encoding="utf-8") == "opto\n"
    assert dest.parent.name == "Package_SO"
    assert lcsc_for_footprint(SOIC4) == "C8150"
    assert discovered_map_path().is_file()
    fn = pcb_3d_model_filename(SOIC4, None)
    assert fn == str(dest.resolve())


def test_prefetch_rejects_jedec_cube(monkeypatch, tmp_path):
    from openhac.database.threed_fillin import (
        fillin_step_path,
        prefetch_fillin_from_board,
        reset_fillin_map_cache,
    )

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    monkeypatch.setenv("KICAD9_FOOTPRINT_DIR", str(tmp_path / "empty_fp"))
    reset_fillin_map_cache()
    cube = tmp_path / "R0805.step"
    cube.write_text("cube\n", encoding="utf-8")

    def fake_search(_query: str):
        return [{"lcsc": 8150, "mfr": "PC817", "stock": 10}]

    def fake_fetch(sku):
        assert sku == "C8150"
        return ("easyeda_generated:C8150", str(cube))

    monkeypatch.setattr(
        "openhac.database.easyeda_integration.generate_footprint_from_lcsc",
        fake_fetch,
    )
    board = _board_with_parts((SOIC4, "PC817"))
    _attempted, updated = prefetch_fillin_from_board(board, search=fake_search)
    dest = fillin_step_path(SOIC4)
    assert updated == 0
    assert dest is None or not dest.is_file()


def test_prefetch_skips_testpoints(monkeypatch, tmp_path):
    from openhac.database.threed_fillin import (
        fillin_step_on_disk,
        prefetch_fillin_from_board,
        reset_fillin_map_cache,
    )

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    searches: list[str] = []

    def fake_search(query: str):
        searches.append(query)
        return [{"lcsc": 1, "mfr": "PC817"}]

    board = _board_with_parts((TP_FP, "PC817"))
    attempted, updated = prefetch_fillin_from_board(board, search=fake_search)
    assert attempted == 0
    assert updated == 0
    assert searches == []
    assert not fillin_step_on_disk(TP_FP)


NRF_FP = "RF_Module:nRF24L01_Breakout"


def _qfn20_step(path: Path) -> None:
    path.write_text(
        "ISO-10303-21;\nHEADER;\n"
        "FILE_NAME ('QFN-20_L4.0-W4.0-H0.8-P0.50.step','x',('x'),('x'),'x','x','x');\n"
        "ENDSEC;\nDATA;\n"
        "#1 = CARTESIAN_POINT('',(-2.,-2.,0.));\n"
        "#2 = CARTESIAN_POINT('',(2.,2.,0.84));\n"
        "ENDSEC;\nEND-ISO-10303-21;\n",
        encoding="utf-8",
    )


def test_qfn_mesh_refused_on_breakout_footprint(tmp_path):
    from openhac.database.kicad_3d import fillin_mesh_ok_for_footprint, footprint_body_class

    step = tmp_path / "QFN-20_L4.0-W4.0-H0.8-P0.50.step"
    _qfn20_step(step)
    assert footprint_body_class(NRF_FP) == "module"
    assert fillin_mesh_ok_for_footprint(step, NRF_FP) is False
    assert fillin_mesh_ok_for_footprint(step, SOIC4) is False


def test_pick_lcsc_skips_qfn_package_on_module():
    from openhac.database.threed_fillin import pick_lcsc_matching_mpn

    items = [
        {"lcsc": 8791, "mfr": "nRF24L01+", "package": "QFN-20-EP(4x4)", "stock": 9999},
        {"lcsc": 42, "mfr": "nRF24L01+", "package": "Module", "stock": 1},
    ]
    assert pick_lcsc_matching_mpn("nRF24L01+", items, footprint=NRF_FP) == "C42"
    assert pick_lcsc_matching_mpn("nRF24L01+", items[:1], footprint=NRF_FP) is None
    assert pick_lcsc_matching_mpn("PC817", [{"lcsc": 8150, "mfr": "PC817", "package": "SOP-4"}], footprint=SOIC4) == "C8150"


def test_prefetch_evicts_qfn_breakout_and_remembers_reject(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import (
        fillin_step_path,
        prefetch_fillin_from_board,
        rejected_skus_for_footprint,
        remember_discovered_lcsc,
        reset_fillin_map_cache,
    )

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    monkeypatch.setenv("KICAD9_FOOTPRINT_DIR", str(tmp_path / "empty_fp"))
    reset_fillin_map_cache()
    dest = fillin_step_path(NRF_FP)
    assert dest is not None
    dest.parent.mkdir(parents=True)
    _qfn20_step(dest)
    remember_discovered_lcsc(NRF_FP, "C8791", note="jlcsearch mpn:nRF24L01+")
    fetches: list[str] = []

    def fake_search(query: str):
        assert "nRF24L01" in query
        return [{"lcsc": 8791, "mfr": "nRF24L01+", "package": "QFN-20-EP(4x4)", "stock": 99}]

    def fake_fetch(sku):
        fetches.append(sku)
        return ("easyeda_generated:" + sku, str(dest))

    monkeypatch.setattr(
        "openhac.database.easyeda_integration.generate_footprint_from_lcsc",
        fake_fetch,
    )
    board = _board_with_parts((NRF_FP, "nRF24L01+"))
    attempted, updated = prefetch_fillin_from_board(board, search=fake_search)
    assert updated == 0
    assert dest.exists() is False
    assert "C8791" in rejected_skus_for_footprint(NRF_FP)
    assert fetches == []
    assert pcb_3d_model_filename(NRF_FP, None) is None
    assert attempted == 0


def test_pcb_attach_evicts_invalid_fillin(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import fillin_step_path, reset_fillin_map_cache

    pack = _empty_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    dest = fillin_step_path(NRF_FP)
    assert dest is not None
    dest.parent.mkdir(parents=True)
    _qfn20_step(dest)
    assert pcb_3d_model_filename(NRF_FP, None) is None
    assert dest.exists() is False

