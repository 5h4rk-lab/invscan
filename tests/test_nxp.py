from invscan.ingest import batch_key, ingest
from invscan.parser import parse_scan
from tests.test_ingest import Fake, FakeDK

GS, RS, EOT = "\x1d", "\x1e", "\x04"
# decoded from photos of two real NXP factory bags
BAG1 = (f"[)>{RS}06{GS}1P935324873557{GS}30PMC9S08PA60AVLF{GS}Q5{GS}9D2230{GS}1TW39137.00{GS}30T{GS}30Q{GS}31P-3/260"
        f"{GS}31TFPXND{GS}32TO260{GS}30D{GS}31D{GS}33T02CTNJ2301EV000{GS}34T{RS}{EOT}")
BAG2 = BAG1.replace("935324873557", "935313339557").replace("MC9S08PA60AVLF", "S9S12G192F0VLH").replace("2230", "2306") \
    .replace("W39137.00", "DV84489.1W").replace("02CTNJ2301EV000", "07CTMEA2XG6K00000")


def test_nxp_label_uses_the_type_not_the_order_code():
    s = parse_scan(BAG1)
    assert (s.vendor, s.mpn, s.manufacturer, s.qty) == ("nxp", "MC9S08PA60AVLF", "NXP", 5)
    assert s.order_code == "935324873557" and s.puid == "02CTNJ2301EV000"
    assert (s.lot_code, s.date_code, s.supplier_sku) == ("W39137.00", "2230", None)  # 30P is not a DigiKey number here


def test_decoder_glyphs_and_second_bag():
    s = parse_scan(BAG2.replace(GS, "␝").replace(RS, "␞").replace(EOT, "␄"))
    assert (s.vendor, s.mpn, s.puid) == ("nxp", "S9S12G192F0VLH", "07CTMEA2XG6K00000")


def test_twelve_digit_order_code_alone_is_enough_to_tell_nxp_apart():
    s = parse_scan(f"[)>{RS}06{GS}1P935313339557{GS}30PS9S12G192F0VLH{GS}Q5")
    assert s.vendor == "nxp" and s.mpn == "S9S12G192F0VLH"


def test_digikey_labels_are_not_mistaken_for_nxp():
    from tests.test_parser import ADA, NEW, REAL
    assert [parse_scan(x).vendor for x in (REAL, NEW, ADA)] == ["digikey", "digikey", "digikey"]
    assert parse_scan(ADA).mpn == "4939"


def test_each_bag_has_its_own_batch_key():
    assert batch_key(parse_scan(BAG1)) != batch_key(parse_scan(BAG2))
    assert batch_key(parse_scan(BAG1)) == "NXP-02CTNJ2301EV000"


def test_nxp_bag_becomes_stock_and_is_not_scanned_twice():
    inv, dk = Fake(), FakeDK()
    r = ingest(inv, parse_scan(BAG1), 7, dk=dk)
    assert r.status == "created" and r.new_part
    assert inv.parts[0]["name"] == "MC9S08PA60AVLF" and inv.parts[0]["description"].startswith("Imported from NXP")
    assert inv.stock[0]["quantity"] == 5 and "935324873557" in inv.stock[0]["notes"] and "W39137.00" in inv.stock[0]["notes"]
    assert dk.asked == [("MC9S08PA60AVLF", None)]  # the order code and the 30P type are not sent as a DigiKey number
    assert ingest(inv, parse_scan(BAG1), 7, dk=dk).status == "duplicate"
    assert ingest(inv, parse_scan(BAG2), 7, dk=dk).new_part  # a different bag, a different part
