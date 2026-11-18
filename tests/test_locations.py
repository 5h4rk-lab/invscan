from invscan.locations import location_contents, parse_label


class Inv:
    def get(self, path, **_):
        if path.endswith("/18/"):
            return {"pk": 18, "name": "Room 127", "pathstring": "Room 127", "parent": None}
        return {"pk": 19, "name": "Cabinet #3", "pathstring": "Room 127/Cabinet #3", "parent": 18}

    def list(self, path, **q):
        if path == "stock/":
            assert q["location"] == 19 and q["cascade"] == "true" and q["in_stock"] == "true"  # the whole cabinet, drawers included
            d = lambda n: {"name": n, "description": n + " desc", "thumbnail": None}
            return [
                {"pk": 1, "part": 7, "quantity": 5, "location": 20, "notes": "", "part_detail": d("MC9S08"), "location_detail": {"pathstring": "Room 127/Cabinet #3/Drawer 1"}},
                {"pk": 2, "part": 7, "quantity": 3, "location": 19, "notes": "NOTE: loose in the front\n", "part_detail": d("MC9S08"), "location_detail": {"pathstring": "Room 127/Cabinet #3"}},
                {"pk": 3, "part": 4, "quantity": 25, "location": 20, "notes": "", "part_detail": d("ERA-8AHD150V"), "location_detail": {"pathstring": "Room 127/Cabinet #3/Drawer 1"}},
                {"pk": 4, "part": 9, "quantity": 0, "location": 20, "notes": "", "part_detail": d("EMPTY"), "location_detail": {"pathstring": "x"}},
            ]
        return [{"pk": 20, "name": "Drawer 1", "pathstring": "Room 127/Cabinet #3/Drawer 1", "items": 2, "sublocations": 0}]


def test_contents_group_lines_by_part_and_include_sublocations():
    d = location_contents(Inv(), 19)
    assert [p["name"] for p in d["parts"]] == ["ERA-8AHD150V", "MC9S08"]  # no zero-quantity lines, sorted by name
    mc = d["parts"][1]
    assert mc["total"] == 8 and [l["here"] for l in mc["lines"]] == [False, True] and mc["lines"][1]["note"] == "loose in the front"
    assert d["lines"] == 3 and d["ancestors"] == [{"id": 18, "name": "Room 127"}]
    assert d["children"] == [{"id": 20, "name": "Drawer 1", "path": "Room 127/Cabinet #3/Drawer 1", "items": 2, "places": 0}]


def test_every_form_of_a_place_label_is_understood():
    assert parse_label("INVSCAN:LOC:21") == 21 and parse_label("INV-SL21") == 21  # printed before, still scan
    assert parse_label("https://invscan-eight.vercel.app/#loc/21") == 21  # the QR on the new cabinet labels
    assert parse_label("http://192.168.0.5:8800/#loc/7 ") == 7
    assert parse_label("https://example.com/#part/21") is None and parse_label("hello") is None
