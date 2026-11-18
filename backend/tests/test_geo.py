import logging
import unittest

from observatorio.geo import CountryCatalog, get_catalog


def square(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def feature(adm0, geometry, name=None):
    return {
        "type": "Feature",
        "properties": {
            "ADM0_A3": adm0,
            "NAME_ES": name or adm0,
            "ISO_A2": adm0[:2],
            "CONTINENT": "Test",
            "SUBREGION": "Testland",
        },
        "geometry": geometry,
    }


class CountryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = CountryCatalog(
            [
                feature("AAA", square(0, 0, 10, 10)),
                feature("BBB", square(10, 0, 20, 10)),  # shares the x=10 edge with AAA
                feature("CCC", square(30, 0, 40, 10)),
                feature("DDD", square(30, 0, 40, 10)),  # overlaps CCC completely
            ]
        )

    def test_interior_point(self):
        result = self.catalog.locate(5, 5)
        self.assertEqual(result.country_id, "AAA")
        self.assertFalse(result.ambiguous)

    def test_ocean_point_has_no_country(self):
        result = self.catalog.locate(-50, -50)
        self.assertIsNone(result.country_id)
        self.assertFalse(result.ambiguous)

    def test_boundary_point_is_covered(self):
        result = self.catalog.locate(20, 5)  # exactly on BBB's outer edge
        self.assertEqual(result.country_id, "BBB")
        self.assertFalse(result.ambiguous)

    def test_shared_edge_picks_smallest_id_and_flags(self):
        result = self.catalog.locate(10, 5)  # on the edge of AAA and BBB
        self.assertEqual(result.country_id, "AAA")
        self.assertTrue(result.ambiguous)

    def test_double_match_picks_smallest_id_and_flags(self):
        result = self.catalog.locate(35, 5)
        self.assertEqual(result.country_id, "CCC")
        self.assertTrue(result.ambiguous)

    def test_assignment_is_deterministic(self):
        first = self.catalog.locate(35, 5)
        for _ in range(5):
            self.assertEqual(self.catalog.locate(35, 5), first)

    def test_dimension_has_one_row_per_unique_id(self):
        self.assertEqual(set(self.catalog.countries), {"AAA", "BBB", "CCC", "DDD"})
        self.assertEqual(self.catalog.countries["AAA"].continent, "Test")
        self.assertEqual(self.catalog.countries["AAA"].subregion, "Testland")

    def test_duplicate_adm0_is_logged_and_resolved(self):
        with self.assertLogs("observatorio.geo", level=logging.WARNING) as logs:
            catalog = CountryCatalog(
                [
                    feature("ZZZ", square(0, 0, 1, 1), name="Primero"),
                    feature("ZZZ", square(5, 5, 6, 6), name="Segundo"),
                ]
            )
        self.assertTrue(any("ZZZ" in line for line in logs.output))
        self.assertEqual(len(catalog.countries), 1)
        self.assertEqual(catalog.countries["ZZZ"].name, "Primero")
        self.assertEqual(catalog.locate(0.5, 0.5).country_id, "ZZZ")
        self.assertEqual(catalog.locate(5.5, 5.5).country_id, "ZZZ")
        self.assertEqual(catalog.duplicate_ids, {"ZZZ": 2})


class BundledCatalogTests(unittest.TestCase):
    def test_bundled_catalog_has_unique_ids(self):
        catalog = get_catalog()
        self.assertEqual(catalog.duplicate_ids, {})
        self.assertGreater(len(catalog.countries), 150)

    def test_known_points(self):
        catalog = get_catalog()
        self.assertEqual(catalog.locate(-3.7, 40.4).country_id, "ESP")  # Madrid
        self.assertEqual(catalog.locate(139.7, 35.7).country_id, "JPN")  # Tokio
        self.assertIsNone(catalog.locate(-140.0, 0.0).country_id)  # Pacifico abierto


if __name__ == "__main__":
    unittest.main()
