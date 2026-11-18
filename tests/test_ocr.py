from invscan.ocr import extract, find_parts, similarity, variants

# OCR output from photos of two real NXP bags, read at several angles (typos and all)
BAG1 = "SEALED DATE 06NOV26\nLo W39137, 0o(®1P J\nPMC   FPXND\nHC9S08PAG0AY\nP) TYPE MC9SO8PAGOAVLF\n(1P)CODENO\nODENO 9353 248\nNJ230) 1\n"
BAG2 = "NXP SEMICONDUCTORS\n(30P) TYPE $9S12G192FOVLH\nENO 9353 133 39557\nll DV84489, WP\n$126192F gy)\n"


def test_labelled_type_field_is_found_and_corrected():
    e = extract(BAG1)
    assert e.labelled == ["MC9SO8PAGOAVLF"]
    assert "MC9S08PA60AVLF" in e.queries  # O->0 and G->6 fixed
    e2 = extract(BAG2)
    assert e2.labelled == ["S9S12G192FOVLH"]  # $ read as S
    assert "S9S12G192F0VLH" in e2.queries


def test_variants_keep_the_original_and_cap_the_count():
    v = variants("MC9SO8PAGOAVLF")
    assert v[0] == "MC9SO8PAGOAVLF" and len(v) <= 4 and "MC9S08PA60AVLF" in v


def test_dates_captions_and_plain_words_are_not_candidates():
    e = extract("SEALED DATE 06NOV26\nCountry of Diffusion UNITED STATES\nHALOGEN FREE\nTYPE\n")
    assert e.labelled == [] and e.generic == []


def test_digikey_part_number_wins_even_with_spaced_hyphens():
    e = extract("PN: 296 - 19733-5 -ND\nQTY: 25\nLOT: AB1234")
    assert e.dk_pn == "296-19733-5-ND" and e.queries[0] == "296-19733-5-ND"
    assert (e.qty, e.lot) == (25, "AB1234")


def test_quantity_lot_and_date_code_labels():
    e = extract("(Q)QTY 5\n(1T)LOT W39137.00\n(9D)DATE 2230\n")
    assert (e.qty, e.lot, e.date_code) == (5, "W39137.00", "2230")
    assert extract("QTY 5").lot == "" and extract("LOT JUNKJUNK").lot == ""  # a lot needs a digit; none means blank


def test_similarity_ignores_punctuation_and_case():
    assert similarity("MC9S08PA60AVLF", "mc9s08pa60avlf") == 1.0
    assert similarity("MC9S08PA60AVLF", "MC9S08PAG0AVLF") > 0.9 > similarity("MC9S08PA60AVLF", "LM358")


class DK:
    def __init__(self, by_query):
        self.by_query, self.asked = by_query, []

    def search(self, q, limit=5):
        self.asked.append(q)
        return self.by_query.get(q, [])

    def lookup(self, mpn, sku=None, manufacturer=None):
        return self.by_query.get("lookup")


def prod(mpn, maker="NXP USA Inc.", pn=None):
    return {"ManufacturerProductNumber": mpn, "Manufacturer": {"Name": maker}, "Description": {"ProductDescription": "IC MCU"},
            "ProductVariations": [{"DigiKeyProductNumber": pn or mpn + "-ND"}]}


def test_find_parts_ranks_by_closeness_and_stops_at_an_exact_match():
    dk = DK({"MC9SO8PAGOAVLF": [prod("MC9S08PA60VLF")], "MC9S08PAGOAVLF": [prod("MC9S08PA60AVLF"), prod("MC9S08PA16AVLF")],
             "MC9S08PAG0AVLF": [prod("MC9S08PA60AVLF")], "MC9S08PA60AVLF": [prod("MC9S08PA60AVLF")]})
    r = find_parts(dk, extract(BAG1).queries)
    assert r[0]["mpn"] == "MC9S08PA60AVLF" and r[0]["dk_pn"] == "MC9S08PA60AVLF-ND" and r[0]["score"] == 1.0
    assert "W39137" not in dk.asked  # stopped before the weak guesses
    assert len({c["mpn"] for c in r}) == len(r)  # no duplicates


def test_digikey_part_number_is_looked_up_directly():
    dk = DK({"lookup": prod("3SMAJ5939B-TP", "Micro Commercial Co", "3SMAJ5939B-TPMSCT-ND")})
    r = find_parts(dk, ["x"], "3SMAJ5939B-TPMSCT-ND")
    assert [c["mpn"] for c in r] == ["3SMAJ5939B-TP"] and dk.asked == []


def test_nothing_found_gives_an_empty_list():
    assert find_parts(DK({}), ["ABC123X"]) == []
