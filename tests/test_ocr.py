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

    def details(self, pn):
        self.detailed = getattr(self, "detailed", []) + [pn]
        return self.by_query.get("details:" + pn) or (self.by_query.get("lookup") if "details:*" in self.by_query else None)


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
    dk = DK({"details:3SMAJ5939B-TPMSCT-ND": prod("3SMAJ5939B-TP", "Micro Commercial Co", "3SMAJ5939B-TPMSCT-ND")})
    r = find_parts(dk, ["x"], "3SMAJ5939B-TPMSCT-ND")
    assert [c["mpn"] for c in r] == ["3SMAJ5939B-TP"] and dk.asked == []


def test_nothing_found_gives_an_empty_list():
    assert find_parts(DK({}), ["ABC123X"]) == []


def test_dates_are_never_part_numbers_even_when_misread():
    for d in ("06NOV26", "O6NOV26", "06-NOV-2026", "06N0V26", "NOV-06-26", "I5DEC2025", "29-0CT", "29-OCT", "29OCT", "OCT-29", "0CT29"):
        e = extract(f"SEALED DATE {d}\nSEALED DATE {d}\nSEALED DATE {d}\n(30P) TYPE LM358DR\n")
        assert d.upper() not in e.queries and e.queries[0] == "LM358DR", d
    e = extract("O6NOV26 O6NOV26 O6NOV26\nSTM32F103C8T6\n")  # no caption at all: still not chosen over the real part
    assert e.generic[0] == "STM32F103C8T6" and "O6NOV26" not in e.generic


def test_words_after_date_lot_and_bag_captions_are_skipped():
    e = extract("LOT AB12CD34\nDATE 2230X9\nPUID 02CTNJ2301EV000\nTYPE MC9S08PA60AVLF\nMSL/PBT 3/260")
    assert e.labelled == ["MC9S08PA60AVLF"] and not {"AB12CD34", "02CTNJ2301EV000"} & set(e.generic)


def test_weak_matches_are_hidden_for_ocr_but_not_for_typed_searches():
    dk = DK({"ZZ9999XX": [prod("LM358DR")]})
    assert find_parts(dk, ["ZZ9999XX"], min_score=0.55) == []
    assert [c["mpn"] for c in find_parts(dk, ["ZZ9999XX"])] == ["LM358DR"]


def test_digikey_numbers_survive_typical_ocr_damage():
    from invscan.ocr import digikey_numbers
    want = ["296-19733-5-ND"]
    for text in ("296-19733-5-ND", "296 - 19733 - 5 - ND", "296–19733–5–ND", "296-19733-5-NO", "296-19733-5-N0",
                 "296-19733-5ND", "PN: 296-19733-5-ND QTY 5", "2O6-19733-5-ND".replace("2O6", "296")):
        assert digikey_numbers(text) == want, text
    assert digikey_numbers("2521-IS32CG5317EVK_KIT-ND") == ["2521-IS32CG5317EVK_KIT-ND"]
    assert digikey_numbers("1528-4939-ND") == ["1528-4939-ND"]


def test_ordinary_words_and_part_numbers_are_not_digikey_numbers():
    from invscan.ocr import digikey_numbers
    assert digikey_numbers("RESEARCH-AND-DEVELOPMENT 3-ND LM358DR 1-AND MC9S08PA60AVLF") == []
    assert digikey_numbers("SEALED DATE 06NOV26 FPXND") == []


def test_every_digikey_number_on_the_photo_is_tried_and_the_rest_skipped():
    e = extract("PN 296-19733-5-ND\nPN 1528-4939-NO\n(30P) TYPE MC9S08PA60AVLF")
    assert e.dk_pns == ["296-19733-5-ND", "1528-4939-ND"] and e.queries[:2] == e.dk_pns
    dk = DK({"details:1528-4939-ND": prod("4939", "Adafruit Industries LLC", "1528-4939-ND")})
    r = find_parts(dk, e.queries, e.dk_pns)
    assert [c["dk_pn"] for c in r] == ["1528-4939-ND"] and dk.asked == []  # no keyword guessing once a DigiKey number resolved


def test_garbled_copies_of_a_digikey_number_are_not_searched_as_guesses():
    assert extract("SHIP 29-0CT\nPN: 296-19733-5-NO\n").queries == ["296-19733-5-ND"]
    assert extract("29-0CT\n29-0CT\n").queries == []


# OCR of a real old-style DigiKey label (condensed font): P/N P15BQCT-ND, MFG P/N ERA-8AHD150V, dated 29-OCT-2014
OLD = "29-0CT-2014 13:06 DIGI-KEY 809 34\n7x: P19B0CT-AD\nP/N\nMFG,\nERA-BAHD15@V\nDESC: RR\nUHM\n29-0CT\nERA-BAHD 150v\nERA-BAHD158Y\n"


def test_letter_led_digikey_number_is_recognised():
    from invscan.ocr import digikey_numbers
    assert digikey_numbers("P/N: P15BQCT-ND") == ["P15BQCT-ND"]
    assert digikey_numbers("PN 3SMAJ5939B-TPMSCT-ND") == ["3SMAJ5939B-TPMSCT-ND"]
    assert digikey_numbers("STANDARD-ND FPXND") == []


def test_damaged_digikey_number_becomes_a_guess_and_the_date_is_ignored():
    e = extract(OLD)
    assert "P19B0CT-ND" in e.dk_guesses and e.dk_pns == []
    assert "29-0CT" not in e.generic and "ERA-BAHD150V" in e.generic  # "ERA-BAHD 150v" is joined, @ is read as 0


def test_fuzz_tries_single_fixes_before_pairs_and_fixes_the_real_case():
    from invscan.ocr import fuzz
    v = fuzz("ERA-BAHD150V", 8)
    assert v[0] == "ERA-8AHD150V" and "ERA-BAHD150V" not in v and all(len(x) == 12 for x in v)
    assert "P15BQCT" in fuzz("P19B0CT", 40)  # 9->5 and 0->Q together
    assert len(fuzz("ZZZ", 5)) == 5 and fuzz("MM", 5) == []


def test_old_label_finds_the_resistor_and_keeps_the_packaging_printed_on_it():
    resistor = prod("ERA-8AHD150V", "Panasonic Industry", "P15BQTR-ND")
    resistor["ProductVariations"].append({"DigiKeyProductNumber": "P15BQCT-ND"})
    dk = DK({"ERA-8AHD150V": [resistor], "details:P15BQCT-ND": resistor})
    e = extract(OLD)
    r = find_parts(dk, e.queries, e.dk_pns, min_score=0.55, guesses=e.dk_guesses, fuzz_targets=e.generic[:2])
    assert [c["mpn"] for c in r] == ["ERA-8AHD150V"] and r[0]["dk_pn"] == "P15BQCT-ND"


def test_digikey_header_text_is_not_a_part_number():
    e = extract("29-OCT-2014 13:06 DIGI-KEY 800 344-4539\nWWW.DIGIKEY.COM\nDIGI-KEY899\n")
    assert e.generic == [] and e.queries == []
