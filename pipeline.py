import csv
import colorsys
import random

from geogrid import GeoGrid

LANGUAGE_HUES = {
	"german":     210,
	"french":      45,
	"italian":    120,
	"spanish":      0,
	"portuguese":  30,
	"greek":      270,
	"arabic":     180,
	"english":    200,
	"dutch":      160,
	"catalan":     15,
}

class GeoGridPipeline:
	def __init__(self, grid_size=0.1, cache_file="regions_cache.tsv", language_hues=None):
		self.grid = GeoGrid(grid_size=grid_size)
		self.cache_file = cache_file
		self.cell_colors = {}
		self.language_hues = language_hues or LANGUAGE_HUES

	def resolve_and_save(self, qids, path=None, override_path=None):
		"""Query Wikidata for each Q-ID, save resolved bboxes/points to TSV.
		If override_path is set, entries there replace matching names in the output."""
		path = path or self.cache_file
		rows = {}
		for item in qids:
			if isinstance(item, tuple) and len(item) == 3:
				qid, name, language = item
			elif isinstance(item, tuple) and len(item) == 2:
				qid, name, language = item[0], item[1], ""
			else:
				qid, name, language = item, None, ""
			print(f"Querying {qid}...")
			wd = self.grid._query_wikidata(qid)
			if wd is None:
				print(f"  No results for {qid}, skipping")
				continue
			label = name or wd["label"] or qid
			country = wd["country_label"] or ""
			n, s, e, w = wd["northernmost"], wd["southernmost"], wd["easternmost"], wd["westernmost"]
			if all([n, s, e, w]):
				rows[label] = {
					"qid": qid, "name": label, "country": country,
					"language": language, "type": "bbox",
					"min_lat": s[0], "max_lat": n[0],
					"min_lon": w[1], "max_lon": e[1],
				}
			elif wd["coordinate_location"]:
				lat, lon = wd["coordinate_location"]
				rows[label] = {
					"qid": qid, "name": label, "country": country,
					"language": language, "type": "point",
					"min_lat": lat, "max_lat": lat,
					"min_lon": lon, "max_lon": lon,
				}
			else:
				print(f"  No coordinates for {qid}, skipping")

		# Apply overrides
		if override_path is not None:
			count = 0
			with open(override_path, "r") as f:
				for row in csv.DictReader(f, delimiter="\t"):
					rows[row["name"]] = row
					count += 1
			print(f"Applied {count} overrides from {override_path}")

		fields = ["qid", "name", "country", "language", "type", "min_lat", "max_lat", "min_lon", "max_lon"]
		with open(path, "w", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
			writer.writeheader()
			writer.writerows(rows.values())
		print(f"Saved {len(rows)} regions to {path}")

	def load_and_build(self, path=None):
		"""Load TSV cache, populate the grid, and build the cell_colors map."""
		path = path or self.cache_file
		with open(path, "r") as f:
			for row in csv.DictReader(f, delimiter="\t"):
				name = row["name"]
				lang = (row.get("language") or "unknown").lower()
				hue = self.language_hues.get(lang)

				if hue is not None:
					shade = random.Random(hash(name) % 10000).random()
					color = colorsys.hsv_to_rgb(hue / 360, 0.65, 0.45 + 0.45 * shade)
				else:
					color = (0.7, 0.7, 0.7)

				if row["type"] == "bbox":
					cells = self.grid.add_region(
						name, row["country"],
						float(row["min_lat"]), float(row["max_lat"]),
						float(row["min_lon"]), float(row["max_lon"]),
					)
				else:
					cells = self.grid.add_point(name, float(row["min_lat"]), float(row["min_lon"]))

				for cell in cells:
					self.cell_colors[cell] = color
