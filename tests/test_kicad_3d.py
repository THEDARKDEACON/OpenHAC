"""KiCad library 3D detection, VSSOP/MSOP alias, stock vs JLC attach."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _fake_pack(tmp_path: Path) -> Path:
    root = tmp_path / "3dmodels"
    so = root / "Package_SO.3dshapes"
    r = root / "Resistor_SMD.3dshapes"
    so.mkdir(parents=True)
    r.mkdir()
    (so / "MSOP-10_3x3mm_P0.5mm.step").write_text("solid msop\n", encoding="utf-8")
    (r / "R_0805_2012Metric.step").write_text("solid r0805\n", encoding="utf-8")
    return root


def test_detects_3d_pack_without_env(monkeypatch, tmp_path):
    from openhac.database import kicad_3d

    pack = _fake_pack(tmp_path)
    for key in kicad_3d._LIB_DIR_ENVS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(kicad_3d, "_platform_3d_candidates", lambda: [str(pack)])
    monkeypatch.setattr(kicad_3d, "_sibling_3dmodels_from_footprint_env", lambda: [])

    assert kicad_3d.kicad_3dmodel_dir() == str(pack.resolve())
    assert kicad_3d.ensure_kicad_3d_env() == str(pack.resolve())
    assert os.environ.get("KICAD9_3DMODEL_DIR") == str(pack.resolve())


def test_expand_kicad8_token_uses_detected_dir(monkeypatch, tmp_path):
    from openhac.database import kicad_3d

    pack = _fake_pack(tmp_path)
    for key in kicad_3d._LIB_DIR_ENVS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    raw = "${KICAD8_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0805_2012Metric.step"
    expanded = kicad_3d.expand_3d_path(raw)
    assert expanded.endswith("R_0805_2012Metric.step")
    assert Path(expanded).is_file()


def test_vssop10_aliases_to_msop10_step(monkeypatch, tmp_path):
    from openhac.database import kicad_3d

    pack = _fake_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    fp = "Package_SO:VSSOP-10_3x3mm_P0.5mm"
    rel = kicad_3d.resolve_library_3d_relpath(fp)
    assert rel == "Package_SO.3dshapes/MSOP-10_3x3mm_P0.5mm.step"
    pointer = kicad_3d.library_3d_pointer_for_footprint(fp)
    assert pointer.endswith("MSOP-10_3x3mm_P0.5mm.step")
    assert pointer.startswith("${KICAD9_3DMODEL_DIR}/")


def test_pcb_filename_stock_ignores_jlc_cache(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import reset_fillin_map_cache

    pack = _fake_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    cache = tmp_path / "easyeda_generated.3dshapes"
    cache.mkdir()
    jlc = tmp_path / "jlc2kicad_generated" / "packages3d" / "R0805.step"
    jlc.parent.mkdir(parents=True)
    jlc.write_text("solid wrong\n", encoding="utf-8")
    monkeypatch.setenv("OPENHAC_3D_CACHE_DIRS", str(cache))
    fn = pcb_3d_model_filename(
        "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
        str(jlc),
    )
    assert fn is None or "R0805" not in str(fn)

    ads = pcb_3d_model_filename(
        "Package_SO:VSSOP-10_3x3mm_P0.5mm",
        str(jlc),
    )
    assert ads is not None
    assert "MSOP-10_3x3mm_P0.5mm.step" in ads
    assert "jlc2kicad" not in ads.lower()


def test_pcb_filename_usbc_uses_fillin_cache(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename
    from openhac.database.threed_fillin import fillin_step_path, reset_fillin_map_cache

    pack = tmp_path / "3dmodels"
    pack.mkdir()
    (pack / "empty.3dshapes").mkdir()
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    fillin = tmp_path / "fillin"
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(fillin))
    reset_fillin_map_cache()
    usb_fp = "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
    sd_fp = "Connector_Card:microSD_HC_Molex_47219-2001"
    usb_dest = fillin_step_path(usb_fp)
    sd_dest = fillin_step_path(sd_fp)
    assert usb_dest is not None and sd_dest is not None
    usb_dest.parent.mkdir(parents=True)
    sd_dest.parent.mkdir(parents=True)
    usb_dest.write_text("usbc\n", encoding="utf-8")
    sd_dest.write_text("sd\n", encoding="utf-8")
    cache = tmp_path / "easyeda_generated.3dshapes"
    cache.mkdir()
    (cache / "R0805.step").write_text("cube\n", encoding="utf-8")
    monkeypatch.setenv("OPENHAC_3D_CACHE_DIRS", str(cache))

    usb = pcb_3d_model_filename(usb_fp, str(cache / "R0805.step"))
    assert usb == str(usb_dest.resolve())
    assert "R0805" not in usb

    slot = pcb_3d_model_filename(sd_fp, None)
    assert slot == str(sd_dest.resolve())


def test_skip_easyeda_3d_jedec_not_missing_connector():
    from openhac.database.kicad_3d import should_skip_easyeda_3d

    assert should_skip_easyeda_3d({"kicad_footprint": "Resistor_SMD:R_0603_1608Metric"})
    assert not should_skip_easyeda_3d(
        {"kicad_footprint": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"}
    )
    assert not should_skip_easyeda_3d({"kicad_footprint": "easyeda_generated:C99"})


def test_pcb_filename_generated_fp_keeps_download(tmp_path):
    from openhac.database.kicad_3d import pcb_3d_model_filename

    step = tmp_path / "easyeda_generated.3dshapes" / "C123.step"
    step.parent.mkdir(parents=True)
    step.write_text("solid ok\n", encoding="utf-8")
    fn = pcb_3d_model_filename("easyeda_generated:C123", str(step))
    assert fn == str(step.resolve())


def test_audit_does_not_poison_kicad_lib_token(tmp_path):
    from openhac.database.db_manager import DatabaseManager

    db_path = str(tmp_path / "c.db")
    dm = DatabaseManager(db_path=db_path)
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "C1",
            "description": "r",
            "category": "resistors",
            "model_3d_source": "kicad_lib",
            "model_3d_local": "${KICAD8_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0805_2012Metric.wrl",
        }
    )
    failed = dm.audit_data_integrity(["R_10k_0805"])
    assert failed == []


def test_project_file_writes_3d_env_vars(tmp_path, monkeypatch):
    from openhac.compiler.project_gen import generate_project_file

    pack = _fake_pack(tmp_path)
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    p = tmp_path / "board.kicad_pro"
    generate_project_file(str(p))
    data = json.loads(p.read_text(encoding="utf-8"))
    vars_ = (data.get("environment") or {}).get("vars") or {}
    got = vars_.get("KICAD9_3DMODEL_DIR")
    assert got in {str(pack), str(pack.resolve())}


def test_jedec_passive_excludes_soic_and_testpoints():
    from openhac.database.kicad_3d import is_jedec_passive_footprint, skip_3d_fillin_footprint

    assert is_jedec_passive_footprint("Resistor_SMD:R_0805_2012Metric")
    assert is_jedec_passive_footprint("Capacitor_SMD:C_0603_1608Metric")
    assert not is_jedec_passive_footprint("Package_SO:SOIC-4_4.55x2.6mm_P1.27mm")
    assert not is_jedec_passive_footprint("Package_TO_SOT_SMD:SOT-23")
    assert skip_3d_fillin_footprint("TestPoint:TestPoint_Pad_D1.5mm")
    assert skip_3d_fillin_footprint("MountingHole:MountingHole_3.2mm_M3")
    assert not skip_3d_fillin_footprint("Package_SO:SOIC-4_4.55x2.6mm_P1.27mm")


def test_qfn_ep_near_miss_uses_declared_library_folder(monkeypatch, tmp_path):
    from openhac.database import kicad_3d
    from openhac.database.threed_fillin import reset_fillin_map_cache

    pack = tmp_path / "3dmodels"
    qfn = pack / "Package_DFN_QFN.3dshapes"
    qfn.mkdir(parents=True)
    (qfn / "QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm.step").write_text("qfn\n", encoding="utf-8")
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    reset_fillin_map_cache()
    fp_root = tmp_path / "fp"
    pretty = fp_root / "Sensor_Motion.pretty"
    pretty.mkdir(parents=True)
    (pretty / "InvenSense_QFN-24_4x4mm_P0.5mm.kicad_mod").write_text(
        '(footprint "InvenSense_QFN-24_4x4mm_P0.5mm" (model "'
        '${KICAD9_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/'
        'QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.6mm.step"))\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KICAD9_FOOTPRINT_DIR", str(fp_root))
    fp = "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm"
    declared = (
        "${KICAD9_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/"
        "QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.6mm.step"
    )
    hit = kicad_3d.resolve_declared_3d_filename(declared)
    assert hit is not None
    assert hit.endswith("QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm.step")
    pointer = kicad_3d.library_3d_pointer_for_footprint(fp)
    assert pointer is not None
    assert "Package_DFN_QFN.3dshapes" in pointer
    assert pointer.endswith("EP2.7x2.7mm.step")
    fn = kicad_3d.pcb_3d_model_filename(fp, None, declared_model=declared)
    assert fn == pointer


def test_missing_pack_file_is_not_a_dangling_pointer(monkeypatch, tmp_path):
    from openhac.database.kicad_3d import library_3d_pointer_for_footprint, pcb_3d_model_filename
    from openhac.database.threed_fillin import reset_fillin_map_cache

    pack = tmp_path / "3dmodels"
    pack.mkdir()
    (pack / "Package_SO.3dshapes").mkdir()
    monkeypatch.setenv("KICAD9_3DMODEL_DIR", str(pack))
    monkeypatch.setenv("OPENHAC_3D_FILLIN_DIR", str(tmp_path / "fillin"))
    monkeypatch.setenv("KICAD9_FOOTPRINT_DIR", str(tmp_path / "empty_fp"))
    reset_fillin_map_cache()
    fp = "Package_SO:SOIC-4_4.55x2.6mm_P1.27mm"
    assert library_3d_pointer_for_footprint(fp) is None
    assert pcb_3d_model_filename(fp, None) is None

