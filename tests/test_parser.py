import pytest
from invscan.parser import parse_scan, ScanError

GS, RS, EOT = "\x1d", "\x1e", "\x04"

# Modelled on a real 2019 DigiKey bag; order numbers and customer reference are made up.
REAL = (
    f"[)>{RS}06{GS}PBENCH1{GS}1PMSP430F2012TN{GS}K{GS}1K11111111{GS}10K22222222"
    f"{GS}11K1{GS}4LMY{GS}Q10{GS}11ZPICK{GS}12Z1044426{GS}13Z333333{GS}20Z" + "0" * 60 + EOT
)


def test_real_digikey_label():
    s = parse_scan(REAL)
    assert s.mpn == "MSP430F2012TN"
    assert s.qty == 10
    assert s.sales_order == "11111111"
    assert s.invoice == "22222222"
    assert s.country == "MY"
    assert s.digikey_part_id == "1044426"
    assert s.load_id == "333333"
    assert s.customer_ref == "BENCH1"
    assert s.po == ""
    assert s.supplier_sku is None  # 30P absent on this label


def test_30p_gives_supplier_sku():
    s = parse_scan(f"[)>{RS}06{GS}1PABC{GS}30P296-1-ND{GS}Q5{EOT}")
    assert s.supplier_sku == "296-1-ND"


def test_visible_glyph_separators_tolerated():
    # some decoders render control chars as U+241x symbols
    glyph = REAL.replace(GS, "␝").replace(RS, "␞").replace(EOT, "␄")
    assert parse_scan(glyph).mpn == "MSP430F2012TN"


def test_missing_header_tolerated():
    # scanners that strip the [)> 06 envelope
    s = parse_scan(f"1PABC{GS}Q3")
    assert (s.mpn, s.qty) == ("ABC", 3)


def test_not_a_digikey_code():
    with pytest.raises(ScanError):
        parse_scan("https://example.com")


def test_no_mpn_is_error():
    with pytest.raises(ScanError):
        parse_scan(f"[)>{RS}06{GS}Q5{EOT}")


# New-style label (2026): has 30P, 1T lot, 9D date code; 13Z is a placeholder (999999)
NEW = (
    f"[)>{RS}06{GS}PD202{GS}1P3SMAJ5939B-TP{GS}30P3SMAJ5939B-TPMSCT-ND{GS}K{GS}1K44444444{GS}10K55555555"
    f"{GS}9D2244{GS}1TBA100422102600013{GS}11K1{GS}4LCN{GS}Q15{GS}11ZPICK{GS}12Z1793316{GS}13Z999999{GS}20Z"
    + "0" * 60 + f"{RS}{EOT}"
)


def test_new_style_label():
    s = parse_scan(NEW)
    assert s.mpn == "3SMAJ5939B-TP"
    assert s.supplier_sku == "3SMAJ5939B-TPMSCT-ND"
    assert s.qty == 15
    assert s.lot_code == "BA100422102600013"
    assert s.date_code == "2244"
    assert s.sales_order == "44444444" and s.country == "CN"


# DigiKey sometimes puts its own part number in the customer-part field (P) and omits 30P
ADA = f"[)>{RS}06{GS}P1528-4939-ND{GS}1P4939{GS}K{GS}1K66666666{GS}10K77777777{GS}4LCN{GS}Q2{GS}12Z14552336{GS}13Z999999{EOT}"


def test_digikey_pn_in_customer_field_is_used_as_sku():
    s = parse_scan(ADA)
    assert s.mpn == "4939"
    assert s.supplier_sku == "1528-4939-ND"
    assert s.customer_ref == ""  # it was a part number, not a reference


def test_ordinary_customer_ref_is_not_mistaken_for_sku():
    assert parse_scan(NEW).supplier_sku == "3SMAJ5939B-TPMSCT-ND"
    assert parse_scan(REAL).supplier_sku is None and parse_scan(REAL).customer_ref == "BENCH1"


# Mouser label (modelled on a real one; order numbers made up). Literal '>' before '[)>', no RS, no MPN in the code.
MOUSER = f">[)>06{GS}K77777777{GS}14K011{GS}PC29{GS}Q10{GS}11K88888888{GS}4LCN{GS}1VNichicon"


def test_mouser_label_fields():
    s = parse_scan(MOUSER)
    assert s.vendor == "mouser"
    assert s.mpn == ""                       # Mouser's square code has no part number; it comes from the P/N barcode
    assert (s.qty, s.manufacturer, s.country) == (10, "Nichicon", "CN")
    assert (s.po, s.line_item, s.invoice) == ("77777777", "011", "88888888")   # invoice is 11K on Mouser labels
    assert s.customer_ref == "C29"


def test_mouser_with_printed_separators():
    # some decoders print control characters as <GS>
    s = parse_scan(">[)>06<GS>K77777777<GS>14K011<GS>PC29<GS>Q10<GS>11K88888888<GS>4LCN<GS>1VNichicon")
    assert s.vendor == "mouser" and s.qty == 10 and s.manufacturer == "Nichicon"


def test_digikey_labels_are_not_mistaken_for_mouser():
    assert parse_scan(REAL).vendor == "digikey" or parse_scan(REAL).vendor == ""
    assert parse_scan(NEW).vendor == "digikey"


def test_digikey_part_numbers_may_contain_underscores_and_other_punctuation():
    from invscan.parser import DK_PN
    for ok in ("296-19733-5-ND", "1528-4939-ND", "2521-IS32CG5317EVK_KIT-ND", "497-1234-1-ND", "3SMAJ5939B-TPMSCT-ND".replace("3SMAJ", "36-3SMAJ")):
        assert DK_PN.match(ok), ok
    for bad in ("C29", "647-RL81C221MDN1KX", "HAMZAH", "296-19733-5", "-ND", ""):
        assert not DK_PN.match(bad), bad


def test_pn_with_an_underscore_in_the_customer_field_is_used_as_the_sku():
    raw = f"[)>{RS}06{GS}P2521-IS32CG5317EVK_KIT-ND{GS}1PIS32CG5317EVK_KIT{GS}Q1{GS}12Z15772483{GS}13Z999999{EOT}"
    s = parse_scan(raw)
    assert s.supplier_sku == "2521-IS32CG5317EVK_KIT-ND" and s.customer_ref == "" and s.mpn == "IS32CG5317EVK_KIT"
