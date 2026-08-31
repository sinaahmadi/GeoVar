"""
geogrid.py — Dialect classification on a geodesic grid.
"""

import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import requests
import pickle
from scipy.ndimage import gaussian_filter
from matplotlib.colors import LinearSegmentedColormap
from collections import defaultdict
from scipy.spatial import ConvexHull
import csv
from matplotlib.lines import Line2D
import random
random.seed(42)


class GeoGrid:
	def __init__(self, grid_size=0.1):
		self.grid_size = grid_size
		self.lat_cells = int(180 / grid_size)
		self.lon_cells = int(360 / grid_size)
		self.P = np.zeros((self.lat_cells, self.lon_cells))
		self.regions = {}
		self.world = gpd.read_file(
			"https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
		)

	def _lat_to_y(self, lat):
		return int((lat + 90) / self.grid_size)

	def _lon_to_x(self, lon):
		return int((lon + 180) / self.grid_size)

	def _y_to_mid_lat(self, y):
		return y * self.grid_size - 90 + self.grid_size / 2

	def _x_to_mid_lon(self, x):
		return x * self.grid_size - 180 + self.grid_size / 2

	def _query_wikidata(self, qid):
		"""Query Wikidata for bounding coordinates (P1332-P1335) and fallback P625.

		Returns dict with keys:
			'northernmost', 'southernmost', 'easternmost', 'westernmost'
				— each (lat, lon) or None
			'coordinate_location' — (lat, lon) or None
			'label' — str or None
			'country_qid' — str or None (e.g. 'Q41' for Greece)
			'country_label' — str or None
		"""
		query = """
		SELECT ?label ?coord
			   ?north ?south ?east ?west
			   ?country ?countryLabel
		WHERE {
		  wd:%(qid)s rdfs:label ?label . FILTER(LANG(?label) = "en")
		  OPTIONAL { wd:%(qid)s wdt:P625 ?coord . }
		  OPTIONAL { wd:%(qid)s wdt:P1332 ?north . }
		  OPTIONAL { wd:%(qid)s wdt:P1333 ?south . }
		  OPTIONAL { wd:%(qid)s wdt:P1334 ?east . }
		  OPTIONAL { wd:%(qid)s wdt:P1335 ?west . }
		  OPTIONAL {
			wd:%(qid)s wdt:P17 ?country .
			?country rdfs:label ?countryLabel . FILTER(LANG(?countryLabel) = "en")
		  }
		}
		LIMIT 1
		""" % {"qid": qid}

		url = "https://query.wikidata.org/sparql"
		r = requests.get(url, params={"query": query, "format": "json"},
						 headers={"User-Agent": "GeoGrid/1.0"})
		r.raise_for_status()
		results = r.json()["results"]["bindings"]

		if not results:
			return None

		row = results[0]
		out = {
			"label": row.get("label", {}).get("value"),
			"coordinate_location": None,
			"northernmost": None,
			"southernmost": None,
			"easternmost": None,
			"westernmost": None,
			"country_qid": None,
			"country_label": None,
		}

		def parse_point(wkt_str):
			"""Parse 'Point(lon lat)' WKT literal."""
			wkt_str = wkt_str.replace("Point(", "").replace(")", "")
			lon, lat = wkt_str.split()
			return float(lat), float(lon)

		for key, prop in [
			("coordinate_location", "coord"),
			("northernmost", "north"),
			("southernmost", "south"),
			("easternmost", "east"),
			("westernmost", "west"),
		]:
			val = row.get(prop, {}).get("value")
			if val:
				out[key] = parse_point(val)

		if "country" in row:
			out["country_qid"] = row["country"]["value"].split("/")[-1]
		if "countryLabel" in row:
			out["country_label"] = row["countryLabel"]["value"]

		return out

	def add_region(self, name, country_name, min_lat, max_lat, min_lon, max_lon):
		"""Add a region defined by a bounding box, clipped to a country polygon."""
		match = self.world[self.world["NAME"].str.lower() == country_name.lower()]
		if len(match) == 0:
			print(f"Could not find country '{country_name}' in Natural Earth data")
			return []

		polygon = match.geometry.iloc[0]
		cells = []

		y_min = max(self._lat_to_y(min_lat), 0)
		y_max = min(self._lat_to_y(max_lat) + 1, self.lat_cells)
		x_min = max(self._lon_to_x(min_lon), 0)
		x_max = min(self._lon_to_x(max_lon) + 1, self.lon_cells)

		buffered_polygon = polygon.buffer(0.1)
		for y in range(y_min, y_max):
			mid_lat = self._y_to_mid_lat(y)
			for x in range(x_min, x_max):
				mid_lon = self._x_to_mid_lon(x)
				if min_lat <= mid_lat <= max_lat and min_lon <= mid_lon <= max_lon:
					point = Point(mid_lon, mid_lat)
					if buffered_polygon.contains(point):
						self.P[y, x] = 1
						cells.append((y, x))

		if len(cells) == 0:
			print(f"  '{name}' bbox smaller than grid size, falling back to point")
			return self.add_point(name, (min_lat + max_lat) / 2, (min_lon + max_lon) / 2)
		
		self.regions[name] = cells
		return cells

	def add_point(self, name, lat, lon):
		"""Add a single grid cell for a point location."""
		y = self._lat_to_y(lat)
		x = self._lon_to_x(lon)
		y = np.clip(y, 0, self.lat_cells - 1)
		x = np.clip(x, 0, self.lon_cells - 1)
		self.P[y, x] = 1
		self.regions[name] = [(y, x)]
		mid_lat = self._y_to_mid_lat(y)
		mid_lon = self._x_to_mid_lon(x)
		print(f"Added '{name}': 1 cell at ({mid_lat:.2f}, {mid_lon:.2f})")
		return [(y, x)]

	def add_region_from_wikidata(self, qid, name=None, country_name=None):
		"""Add a region from a Wikidata Q-ID.

		Strategy:
		  1. Query Wikidata for P1332-P1335 (bounding directional points).
			 If all four are available → use their lat/lon as bounding box
			 → call add_region() clipped to the country polygon.
		  2. If bounding points are missing, fall back to P625 (coordinate location)
			 → call add_point() to set a single grid cell.

		Args:
			qid: Wikidata identifier, e.g. 'Q34374' for Crete.
			name: Display name. If None, uses the English label from Wikidata.
			country_name: Country name for polygon clipping. If None, uses
						  the country (P17) from Wikidata.
		"""
		print(f"Querying Wikidata for {qid}...")
		wd = self._query_wikidata(qid)

		if wd is None:
			print(f"No results found for {qid}")
			return []

		label = name or wd["label"] or qid
		country = country_name or wd["country_label"]

		n, s, e, w = wd["northernmost"], wd["southernmost"], wd["easternmost"], wd["westernmost"]

		if all([n, s, e, w]):
			min_lat = s[0]  # southernmost latitude
			max_lat = n[0]  # northernmost latitude
			min_lon = w[1]  # westernmost longitude
			max_lon = e[1]  # easternmost longitude
			print(f"  Bounding box for '{label}': "
				  f"lat [{min_lat:.3f}, {max_lat:.3f}], "
				  f"lon [{min_lon:.3f}, {max_lon:.3f}]")
			if country:
				return self.add_region(label, country, min_lat, max_lat, min_lon, max_lon)
			else:
				print(f"  No country found for polygon clipping — "
					  f"adding all cells in bounding box without clipping")
				return self._add_bbox_no_clip(label, min_lat, max_lat, min_lon, max_lon)
		else:
			available = {k: v for k, v in
						 [("N", n), ("S", s), ("E", e), ("W", w)] if v}
			if available:
				print(f"  Only partial bounding points available: "
					  f"{list(available.keys())}. Falling back to P625.")

			coord = wd["coordinate_location"]
			if coord:
				print(f"  Using coordinate location: ({coord[0]:.4f}, {coord[1]:.4f})")
				return self.add_point(label, coord[0], coord[1])
			else:
				print(f"  No coordinates found for {qid}")
				return []

	def _add_bbox_no_clip(self, name, min_lat, max_lat, min_lon, max_lon):
		"""Add all grid cells within a bounding box (no country clipping)."""
		cells = []
		y_min = max(self._lat_to_y(min_lat), 0)
		y_max = min(self._lat_to_y(max_lat) + 1, self.lat_cells)
		x_min = max(self._lon_to_x(min_lon), 0)
		x_max = min(self._lon_to_x(max_lon) + 1, self.lon_cells)

		for y in range(y_min, y_max):
			mid_lat = self._y_to_mid_lat(y)
			for x in range(x_min, x_max):
				mid_lon = self._x_to_mid_lon(x)
				if min_lat <= mid_lat <= max_lat and min_lon <= mid_lon <= max_lon:
					self.P[y, x] = 1
					cells.append((y, x))

		self.regions[name] = cells
		print(f"Added '{name}': {len(cells)} cells (no polygon clipping)")
		return cells

	def add_regions_from_wikidata(self, qids, country_name=None):
		"""Batch add multiple regions from a list of (qid,) or (qid, name) tuples.

		Args:
			qids: list of str or (str, str) — Q-IDs, optionally with display names.
				  e.g. ['Q34374', ('Q229', 'Cyprus'), 'Q199']
			country_name: default country for all, can be overridden per-item.
		"""
		results = {}
		for item in qids:
			if isinstance(item, tuple):
				q, n = item[0], item[1]
			else:
				q, n = item, None
			cells = self.add_region_from_wikidata(q, name=n, country_name=country_name)
			results[q] = cells
		return results

	def visualize(self, extent=None, save_path=None, cell_colors=None):
		"""Show the grid on a map. Pass cell_colors={(y,x): (r,g,b)} for coloured output."""
		fig = plt.figure(figsize=(12, 6))
		ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
		if extent:
			ax.set_extent(extent)
		else:
			ax.set_global()

		ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
		ax.add_feature(cfeature.LAND, alpha=0.2)
		ax.add_feature(cfeature.OCEAN, alpha=0.2)

		ys, xs = np.where(self.P == 1)
		for y, x in zip(ys, xs):
			mid_lat = self._y_to_mid_lat(y)
			mid_lon = self._x_to_mid_lon(x)
			color = cell_colors.get((y, x), (0.7, 0.7, 0.7)) if cell_colors else "gray"
			ax.add_patch(plt.Rectangle(
				(mid_lon - self.grid_size / 2, mid_lat - self.grid_size / 2),
				self.grid_size, self.grid_size,
				facecolor=color, alpha=0.6,
				transform=ccrs.PlateCarree(),
			))

		ax.set_title(f"Regions (grid={self.grid_size}°)")
		ax.gridlines(draw_labels=True, linewidth=0.3, linestyle="--")
		if save_path:
			plt.savefig(save_path, dpi=150, bbox_inches="tight")
		plt.show()

	def embed_dialects(self, dialect_data, model_name="paraphrase-multilingual-MiniLM-L12-v2",
					device="cuda", batch_size=256):
		"""
		Compute sentence embeddings for all dialects and store internally.

		Args:
			dialect_data: {dialect_name: {"sentences": [str, ...], ...}}
			model_name:   sentence-transformers model identifier
			device:       "cuda" or "cpu"
			batch_size:   encoding batch size

		Stores:
			self.dialect_data  — input dict with "embeddings" key added per dialect
			self.emb_dim       — embedding dimensionality
		"""
		from sentence_transformers import SentenceTransformer

		print(f"Loading model: {model_name} on {device}")
		model = SentenceTransformer(model_name, device=device)
		self.emb_dim = model.get_sentence_embedding_dimension()
		print(f"  Embedding dimension: {self.emb_dim}")

		total = sum(len(d["sentences"]) for d in dialect_data.values())
		print(f"  Total sentences to embed: {total}")

		done = 0
		for name, d in dialect_data.items():
			sents = d["sentences"]
			embs = model.encode(
				sents,
				batch_size=batch_size,
				show_progress_bar=False,
				normalize_embeddings=True,
				device=device,
			)
			d["embeddings"] = np.array(embs)
			done += len(sents)
			print(f"  [{done}/{total}] {name}: {len(sents)} sentences")

		self.dialect_data = dialect_data

	def embed_dialects_canine(self, dialect_data, model_name="google/canine-c",
							device="cuda", batch_size=64):
		"""Embed sentences using CANINE (character-level transformer)."""
		from transformers import CanineTokenizer, CanineModel
		import torch

		print(f"Loading model: {model_name} on {device}")
		tokenizer = CanineTokenizer.from_pretrained(model_name)
		model = CanineModel.from_pretrained(model_name).to(device)
		model.eval()

		self.emb_dim = model.config.hidden_size
		print(f"  Embedding dimension: {self.emb_dim}")

		total = sum(len(d["sentences"]) for d in dialect_data.values())
		print(f"  Total sentences to embed: {total}")

		done = 0
		for name, d in dialect_data.items():
			sents = d["sentences"]
			if len(sents) == 0:
				d["embeddings"] = np.empty((0, self.emb_dim))
				done += 0
				continue

			all_embs = []

			for i in range(0, len(sents), batch_size):
				batch = sents[i:i + batch_size]
				inputs = tokenizer(batch, padding=True, truncation=True,
								max_length=512, return_tensors="pt").to(device)
				with torch.no_grad():
					outputs = model(**inputs)
				# Mean pooling over non-padding tokens
				mask = inputs["attention_mask"].unsqueeze(-1).float()
				embs = (outputs.last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1)
				# L2 normalize
				embs = torch.nn.functional.normalize(embs, p=2, dim=1)
				all_embs.append(embs.cpu().numpy())

			d["embeddings"] = np.concatenate(all_embs, axis=0)
			done += len(sents)
			print(f"  [{done}/{total}] {name}: {len(sents)} sentences")

		self.dialect_data = dialect_data

	def _region_centroid_cell(self, dialect_name):
		"""Return the single cell closest to the centroid of a dialect's region."""
		cells = self.regions.get(dialect_name, [])
		if not cells:
			return None
		if len(cells) == 1:
			return cells[0]

		mid_lats = [self._y_to_mid_lat(y) for y, _ in cells]
		mid_lons = [self._x_to_mid_lon(x) for _, x in cells]
		cy = np.clip(self._lat_to_y(np.mean(mid_lats)), 0, self.lat_cells - 1)
		cx = np.clip(self._lon_to_x(np.mean(mid_lons)), 0, self.lon_cells - 1)
		return (cy, cx)

	def _region_centroid_coords(self, dialect_name):
		"""Return (lat, lon) of the centroid of a dialect's region."""
		cells = self.regions.get(dialect_name, [])
		if not cells:
			return None, None
		mid_lats = [self._y_to_mid_lat(y) for y, _ in cells]
		mid_lons = [self._x_to_mid_lon(x) for _, x in cells]
		return np.mean(mid_lats), np.mean(mid_lons)

	def build_cell_prototypes(self, mode="cell", sigma=3.0):
		from collections import defaultdict

		if not hasattr(self, "dialect_data"):
			raise RuntimeError("Call embed_dialects() or load_embeddings() before build_cell_prototypes()")

		cell_embeddings = defaultdict(list)
		cell_dialects = defaultdict(set)
		skipped = []

		if mode == "kde":
			max_radius = self._find_max_radius(sigma)
			print(f"  KDE sigma={sigma}, max_radius={max_radius} cells")

		for name, d in self.dialect_data.items():
			embs = d.get("embeddings")
			if embs is None or name not in self.regions:
				skipped.append(name)
				continue

			if mode == "centroid":
				cell = self._region_centroid_cell(name)
				if cell is None:
					skipped.append(name)
					continue
				cell_embeddings[cell].append((embs, 1.0))
				cell_dialects[cell].add(name)

			elif mode == "cell":
				target_cells = self.regions.get(name, [])
				if not target_cells:
					skipped.append(name)
					continue
				for cell in target_cells:
					cell_embeddings[cell].append((embs, 1.0))
					cell_dialects[cell].add(name)

			elif mode == "kde":
				mean_emb = embs.mean(axis=0)
				centroid_lat, centroid_lon = self._region_centroid_coords(name)
				if centroid_lat is None:
					skipped.append(name)
					continue

				center_y = self._lat_to_y(centroid_lat)
				center_x = self._lon_to_x(centroid_lon)

				min_y = max(0, center_y - max_radius)
				max_y = min(self.lat_cells, center_y + max_radius + 1)
				min_x = max(0, center_x - max_radius)
				max_x = min(self.lon_cells, center_x + max_radius + 1)

				for cy in range(min_y, max_y):
					cell_lat = self._y_to_mid_lat(cy)
					for cx in range(min_x, max_x):
						cell_lon = self._x_to_mid_lon(cx)
						w = self._kernel(cell_lat, cell_lon, centroid_lat, centroid_lon, sigma)
						if w > 0.001:
							cell_embeddings[(cy, cx)].append((mean_emb, w))
							cell_dialects[(cy, cx)].add(name)
			else:
				raise ValueError(f"Unknown mode: {mode}. Use 'centroid', 'cell', or 'kde'.")

		# Compute prototypes
		self.cell_prototypes = {}
		for cell, emb_weight_list in cell_embeddings.items():
			if mode == "kde":
				total_weight = sum(w for _, w in emb_weight_list)
				weighted_sum = sum(e * w for e, w in emb_weight_list)
				prototype = weighted_sum / total_weight
			else:
				stacked = np.vstack([e for e, _ in emb_weight_list])
				prototype = stacked.mean(axis=0)

			norm = np.linalg.norm(prototype)
			if norm > 0:
				prototype /= norm
			self.cell_prototypes[cell] = prototype

		self.cell_dialects = dict(cell_dialects)

		if skipped:
			print(f"  Skipped {len(skipped)} dialects (no embeddings or region): "
				f"{skipped[:10]}{'...' if len(skipped) > 10 else ''}")

		mapped = len(self.dialect_data) - len(skipped)
		print(f"  Mode: {mode}" + (f", sigma={sigma}" if mode == "kde" else ""))
		print(f"  Non-empty cells: {len(self.cell_prototypes)}")
		print(f"  Dialects mapped: {mapped}")

	def save_embeddings(self, path="embeddings.pkl"):
		import pickle
		emb_dict = {name: d["embeddings"] for name, d in self.dialect_data.items()
					if "embeddings" in d}
		with open(path, "wb") as f:
			pickle.dump(emb_dict, f)
		print(f"Saved embeddings for {len(emb_dict)} dialects to {path}")

	def load_embeddings(self, dialect_data, path="embeddings.pkl"):
		import pickle
		with open(path, "rb") as f:
			emb_dict = pickle.load(f)
		loaded = 0
		for name in dialect_data:
			if name in emb_dict:
				dialect_data[name]["embeddings"] = emb_dict[name]
				loaded += 1
		self.dialect_data = dialect_data
		self.emb_dim = next(iter(emb_dict.values())).shape[1]
		print(f"Loaded embeddings for {loaded}/{len(dialect_data)} dialects (dim={self.emb_dim})")
		
	def _kernel(self, lat, lon, m_lat, m_lon, sigma):
		"""Gaussian kernel density at (lat, lon) given observation at (m_lat, m_lon)."""
		coef = 1 / (2 * np.pi * sigma**2)
		exponent = -((lat - m_lat)**2 + (lon - m_lon)**2) / (2 * sigma**2)
		return coef * np.exp(exponent)

	def _find_max_radius(self, sigma, min_density=0.001):
		"""Find how many cells away the kernel is still above min_density."""
		for r in range(1, 1000):
			distance = r * self.grid_size
			density = self._kernel(distance, 0, 0, 0, sigma)
			if density < min_density:
				return r
		return r
	
	def save_prototypes(self, path="prototypes.pkl"):
		data = {
			"cell_prototypes": self.cell_prototypes,
			"cell_dialects": self.cell_dialects,
			"grid_size": self.grid_size,
		}
		with open(path, "wb") as f:
			pickle.dump(data, f)
		print(f"Saved {len(self.cell_prototypes)} prototypes to {path}")

	def load_prototypes(self, path="prototypes.pkl"):
		import pickle
		with open(path, "rb") as f:
			data = pickle.load(f)
		self.cell_prototypes = data["cell_prototypes"]
		self.cell_dialects = data["cell_dialects"]
		print(f"Loaded {len(self.cell_prototypes)} prototypes from {path}")
	
	# =======================================================================
	def visualize_continua(self, continua, extent=None, save_path=None,
					cache_path="regions_cache.tsv",
					geojson_path="GeoVar-Continua.geojson",
					figsize=(16, 9), dpi=300):
		import json
		from shapely.geometry import shape

		rlang = {}
		with open(cache_path) as f:
			for row in csv.DictReader(f, delimiter="\t"):
				rlang[row["name"]] = row.get("language", "")

		l2c = {lang: cont for cont, langs in continua.items() for lang in langs}

		PAL = [
			'#e6194b',
			'#3cb44b',
			"#B7B71B",
			'#f58231',
			'#911eb4',
			'#f032e6',
			'#9a6324',
			"#f49242",
			'#808000',
			"#161AE26F"
		]
		cc = {name: PAL[i % len(PAL)] for i, name in enumerate(continua)}

		# Subsample rate per language (1.0 = keep all, 0.3 = keep 30%)
		LANG_SUBSAMPLE = {"German": 0.25}

		cont_dots = defaultdict(list)
		for rname, cells in self.regions.items():
			lang = rlang.get(rname, "")
			cont = l2c.get(lang)
			if not cont or not cells:
				continue
			rate = LANG_SUBSAMPLE.get(lang, 1.0)
			if rate < 1.0 and len(cells) > 1:
				k = max(1, int(len(cells) * rate))
				cells = random.sample(list(cells), k)
			for y, x in cells:
				cont_dots[cont].append(
					(self._y_to_mid_lat(y), self._x_to_mid_lon(x))
				)

		# --- Load continua polygons from GeoJSON ---
		# Features are matched to continua by order (1st feature → 1st continuum, etc.)
		cont_polygons = {}
		try:
			with open(geojson_path) as f:
				gj = json.load(f)
			for feat in gj["features"]:
				name = feat["properties"].get("name")
				if name in continua:
					cont_polygons[name] = shape(feat["geometry"])
				else:
					print(f"Polygon '{name}' not in continua dict, skipping")
		except FileNotFoundError:
			print(f"GeoJSON not found at {geojson_path}, skipping polygons")

		if extent is None and cont_dots:
			all_pts = [p for pts in cont_dots.values() for p in pts]
			lats, lons = zip(*all_pts)
			margin = 3.0
			extent = [min(lons) - margin, max(lons) + margin,
					min(lats) - margin, max(lats) + margin]

		fig = plt.figure(figsize=figsize, facecolor='white')
		ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
		if extent:
			ax.set_extent(extent, crs=ccrs.PlateCarree())
		
		ax.set_facecolor('white')
		ax.add_feature(cfeature.OCEAN, facecolor='white')
		ax.add_feature(cfeature.LAND, facecolor='#f5f5f5', edgecolor='none')
		ax.add_feature(cfeature.BORDERS, linewidth=0.25, edgecolor='#d0d0d0')
		ax.add_feature(cfeature.COASTLINE, linewidth=0.3, edgecolor='#999')

		# # --- Draw continua polygons (below scatter points) ---
		for cont_name, geom in cont_polygons.items():
			color = cc.get(cont_name, '#888888')
			geoms = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
			for poly in geoms:
				# ax.add_geometries(
				# 	[poly],
				# 	crs=ccrs.PlateCarree(),
				# 	facecolor=color,
				# 	alpha=0.3,   
				# 	edgecolor='none',
				# 	linewidth=0,
				# 	joinstyle='round',
				# 	capstyle='round',
				# 	zorder=-1,
				# )
				ax.add_geometries([poly], crs=ccrs.PlateCarree(),
					facecolor=color, edgecolor='none',
					alpha=0.12, zorder=-1)

		SIZE_OVERRIDE = {"West Germanic": 0.1, "Basque": 0.2, "Italic": 0.2, "Ukrainian": 0.8}  # default is 0.5

		for cont_name in continua:
			dots = cont_dots.get(cont_name, [])
			if not dots:
				continue
			dlats, dlons = zip(*dots)
			ax.scatter(
				dlons, dlats,
				c=cc[cont_name],
				s=SIZE_OVERRIDE.get(cont_name, 0.5),
				alpha=1,
				marker=',',
				edgecolors='none',
				transform=ccrs.PlateCarree(),
				zorder=2
			)

		handles = [Line2D([0], [0], marker='o', color='w', markerfacecolor=cc[c],
                  mec='none', ms=4, label=c)
           for c in continua if c in cont_dots]
		
		# handles = [Line2D([0], [0], marker='o', color='w', markerfacecolor=cc[c],
		# 				mec='white', ms=9, label=c)
		# 		for c in continua if c in cont_dots]

		leg = ax.legend(
			handles=handles,
			loc='lower center',
			bbox_to_anchor=(0.5, 1.02),
			ncol=4,
			fontsize=6,
			frameon=False,
			handletextpad=0.3,
			columnspacing=0.8,
			borderpad=0.2,
			prop={'family': 'serif', 'size': 6},
		)
		gl = ax.gridlines(draw_labels=True, linewidth=0.15,
						color='#d0c8c0', alpha=0.4)
		gl.top_labels = gl.right_labels = False
		gl.xlabel_style = gl.ylabel_style = {'size': 8, 'color': '#888'}
		
		
		plt.tight_layout()
		if save_path:
			plt.savefig(save_path, format=save_path.rsplit('.')[-1],
						dpi=dpi, bbox_inches='tight', facecolor='white')
			print(f"Saved to {save_path}")
		plt.show()