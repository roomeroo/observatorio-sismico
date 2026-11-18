"""Geographic enrichment: point-in-polygon against the country catalog.

Rule (documented in docs/diccionario-datos.md):
  * ``covers`` semantics: a point on a polygon boundary belongs to it.
  * If several catalog entities match, the lexicographically smallest
    ``ADM0_A3`` is chosen and the result is flagged ``ambiguous``.
  * No match -> ``country_id`` is ``None`` ("Sin pais asignado").
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from shapely import STRtree
from shapely.geometry import Point, shape

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_PATH = Path(__file__).parent / "data" / "paises.geojson"


@dataclass(frozen=True)
class Country:
    country_id: str
    name: str
    iso_a2: Optional[str]
    continent: Optional[str]
    subregion: Optional[str]


@dataclass(frozen=True)
class GeoAssignment:
    country_id: Optional[str]
    ambiguous: bool


class CountryCatalog:
    def __init__(self, features: list[dict]):
        self.countries: dict[str, Country] = {}
        geometries = []
        ids: list[str] = []
        duplicates: dict[str, int] = {}

        for feature in features:
            props = feature.get("properties") or {}
            adm0 = props.get("ADM0_A3")
            if not adm0:
                logger.warning("Catalog feature without ADM0_A3 skipped: %s", props.get("NAME"))
                continue
            geom = shape(feature["geometry"])
            if adm0 in self.countries:
                # Deterministic resolution: keep the first record's attributes and
                # merge the geometry so no area is lost.
                duplicates[adm0] = duplicates.get(adm0, 1) + 1
                idx = ids.index(adm0)
                geometries[idx] = geometries[idx].union(geom)
                continue
            self.countries[adm0] = Country(
                country_id=adm0,
                name=props.get("NAME_ES") or props.get("NAME") or props.get("ADMIN") or adm0,
                iso_a2=props.get("ISO_A2") if props.get("ISO_A2") not in (None, "-99") else None,
                continent=props.get("CONTINENT"),
                subregion=props.get("SUBREGION"),
            )
            geometries.append(geom)
            ids.append(adm0)

        for adm0, count in sorted(duplicates.items()):
            logger.warning(
                "Duplicate ADM0_A3 %s appears %d times in the catalog; geometries merged, first attributes kept",
                adm0,
                count,
            )
        self.duplicate_ids = dict(duplicates)
        self._ids = ids
        self._geometries = geometries
        self._tree = STRtree(geometries)

    @classmethod
    def load(cls, path: Path = DEFAULT_CATALOG_PATH) -> "CountryCatalog":
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(data["features"])

    def locate(self, longitude: float, latitude: float) -> GeoAssignment:
        point = Point(longitude, latitude)
        candidates = self._tree.query(point, predicate="intersects")
        matches = sorted(
            self._ids[i] for i in candidates if self._geometries[i].covers(point)
        )
        if not matches:
            return GeoAssignment(None, False)
        return GeoAssignment(matches[0], len(matches) > 1)


_default_catalog: Optional[CountryCatalog] = None


def get_catalog() -> CountryCatalog:
    global _default_catalog
    if _default_catalog is None:
        _default_catalog = CountryCatalog.load()
    return _default_catalog
