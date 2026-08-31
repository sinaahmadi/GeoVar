#!/usr/bin/env python3
"""
extract_sand.py — Extract text and metadata from SAND TEI-XML files.
Usage: python extract_sand.py <input_dir> <output_file.tsv>

Source of the data: https://sand.meertens.knaw.nl//zoeken/tei/index.php#
"""

import sys
import csv
import xml.etree.ElementTree as ET
from pathlib import Path


def extract_sand_file(filepath):
	try:
		tree = ET.parse(filepath)
		root = tree.getroot()
	except ET.ParseError as e:
		print(f"  Parse error in {filepath}: {e}", file=sys.stderr)
		return None

	meta = {
		"file": Path(filepath).name,
		"id": root.get("id") or root.get("{http://www.w3.org/XML/1998/namespace}id"),
		"location_name": None,
		"recording_date": None,
	}

	header = root.find("teiHeader")
	if header is not None:
		title_el = header.find(".//title")
		if title_el is not None and title_el.text:
			t = title_el.text.strip()
			if "(" in t:
				loc = t[:t.rfind("(")].strip()
				for prefix in ("SAND-interview ", "SAND interview "):
					if loc.startswith(prefix):
						loc = loc[len(prefix):]
				meta["location_name"] = loc.strip()

		date_el = header.find(".//recording/date")
		if date_el is not None:
			meta["recording_date"] = (date_el.text or "").strip() or date_el.get("when")

	informant_ids = {
		p.get("id")
		for p in root.findall(".//person")
		if p.get("role") == "informant"
	}

	rows = []
	for u in root.iter("u"):
		if u.get("who") not in informant_ids:
			continue
		parts = []
		if u.text:
			parts.append(u.text.strip())
		for child in u:
			if child.text:
				parts.append(child.text.strip())
			if child.tail:
				parts.append(child.tail.strip())
		text = " ".join(p for p in parts if p)
		if text:
			rows.append({**meta, "text": text})

	return rows


def extract_sand_corpus(input_dir, output_file):
	xml_files = sorted(Path(input_dir).rglob("*.xml"))
	if not xml_files:
		print(f"No XML files found in {input_dir}", file=sys.stderr)
		sys.exit(1)

	print(f"Found {len(xml_files)} XML files in '{input_dir}'")

	total = 0
	with open(output_file, "w", encoding="utf-8", newline="") as f:
		writer = csv.writer(f, delimiter="\t")
		writer.writerow(["file", "id", "location_name", "recording_date", "text"])
		for fp in xml_files:
			rows = extract_sand_file(fp)
			if rows:
				for row in rows:
					writer.writerow([row["file"], row["id"], row["location_name"],
									 row["recording_date"], row["text"]])
				total += len(rows)

	print(f"Wrote {total} rows to '{output_file}'")


if __name__ == "__main__":
	if len(sys.argv) != 3:
		print("Usage: python extract_sand.py <input_dir> <output_file.tsv>")
		sys.exit(1)
	extract_sand_corpus(sys.argv[1], sys.argv[2])