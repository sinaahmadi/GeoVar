"""
Step 1: Enrich locations with Wikidata metadata
Input: language_data.json with structure {language: {location: [utterances]}}
Output: location_index.json with Wikidata IDs, coordinates, hierarchy
"""

import json
import time
from typing import Dict, List, Optional, Set, Tuple
from SPARQLWrapper import SPARQLWrapper, JSON
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Map languages to their Wikidata country QIDs
LANG_TO_COUNTRY = {
    "Danish": "Q35",
    "Faroese": "Q4628",
    "Icelandic": "Q189",
    "Norwegian": "Q20",
    "Ovdalian": "Q34",
    "Swedish": "Q34"
}

class LocationEnricher:
    def __init__(self, lang_to_country: Dict[str, str] = None):
        """
        Initialize enricher with language-to-country mapping
        """
        self.lang_to_country = lang_to_country or LANG_TO_COUNTRY
        self.sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        self.location_index = {}
        self.failed_locations = []
        self.query_count = 0
    
    def extract_locations_from_json(self, json_file: str) -> Set[Tuple[str, str]]:
        """
        Extract unique (language, location) pairs from language_data.json
        
        Args:
            json_file: Path to language_data.json
            
        Returns:
            Set of (language, location) tuples
        """
        logger.info(f"Loading locations from {json_file}...")
        
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        places = set()
        for lang in data:
            if lang not in self.lang_to_country:
                logger.warning(f"Unknown language: {lang}, skipping")
                continue
            
            for place in data[lang]:
                places.add((lang, place))
        
        places = list(places)
        logger.info(f"Found {len(places)} unique (language, location) pairs")
        
        return places
    
    def query_location_by_name(self, location_name: str, country_qid: str) -> Optional[Dict]:
        """
        Query Wikidata for a location by name.
        Returns the best settlement-type match.
        
        Args:
            location_name: Name of the location
            country_qid: Wikidata QID of the country (e.g., 'Q20' for Norway)
            
        Returns:
            Dictionary with location metadata or None if not found
        """
        
        query = f"""
        SELECT ?location ?locationLabel ?typeLabel ?country ?countryLabel
               ?coords ?osmId
        WHERE {{
            ?location rdfs:label "{location_name}"@en .
            ?location wdt:P17 ?country .
            ?location wdt:P31 ?type .
            ?type rdfs:label ?typeLabel .
            FILTER(LANG(?typeLabel) = "en")
            
            OPTIONAL {{ ?location wdt:P625 ?coords . }}
            OPTIONAL {{ ?location wdt:P402 ?osmId . }}
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        LIMIT 10
        """
        
        self.sparql.setQuery(query)
        self.sparql.setReturnFormat(JSON)
        
        try:
            results = self.sparql.query().convert()
            bindings = results.get('results', {}).get('bindings', [])
            self.query_count += 1
            
            if bindings:
                # Rank results by settlement type quality
                best_binding = self._rank_settlement_types(bindings)
                if best_binding:
                    return self._parse_wikidata_result(best_binding, location_name)
            
            return None
                
        except Exception as e:
            logger.debug(f"Query failed for '{location_name}': {e}")
            return None
    
    def _rank_settlement_types(self, bindings: List[Dict]) -> Optional[Dict]:
        """
        Rank settlement results by type preference.
        Prefers: human settlement > city/town/village > other
        """
        
        # Priority ranking for settlement types
        type_priority = {
            'human settlement': 100,
            'city': 90,
            'town': 85,
            'village': 80,
            'hamlet': 75,
            'populated place': 70,
            'rural area': 40,
            'geographical feature': 30,
        }
        
        best_binding = None
        best_score = -1
        
        for binding in bindings:
            type_label = binding.get('typeLabel', {}).get('value', '').lower()
            score = type_priority.get(type_label, 0)
            
            if score > best_score:
                best_score = score
                best_binding = binding
        
        return best_binding
    
    def _parse_wikidata_result(self, binding: Dict, location_name: str) -> Dict:
        """Parse a Wikidata SPARQL result into our location format"""
        
        # Extract Wikidata ID from URI
        location_uri = binding.get('location', {}).get('value', '')
        wikidata_id = location_uri.split('/')[-1] if location_uri else 'unknown'
        
        # Extract coordinates
        coords_str = binding.get('coords', {}).get('value', '')
        lat, lon = None, None
        if coords_str:
            try:
                # Format: "Point(lon lat)"
                parts = coords_str.replace('Point(', '').replace(')', '').split()
                lon, lat = float(parts[0]), float(parts[1])
            except Exception as e:
                logger.debug(f"Could not parse coordinates for {location_name}: {e}")
        
        location_data = {
            'name': location_name,
            'wikidata_id': wikidata_id,
            'settlement_type': binding.get('typeLabel', {}).get('value', 'unknown'),
            'country': binding.get('countryLabel', {}).get('value', 'unknown'),
            'region': binding.get('regionLabel', {}).get('value', None),
            'coordinates': {'lat': lat, 'lon': lon} if lat is not None and lon is not None else None,
            'osm_id': binding.get('osmId', {}).get('value', None),
            'wikidata_uri': location_uri,
            'matched': True
        }
        
        return location_data
    
    def enrich_locations(self, locations_list: List[Tuple[str, str]]) -> Dict:
        """
        Enrich (language, location) pairs with Wikidata information
        
        Args:
            locations_list: List of (language, location) tuples
            
        Returns:
            Dictionary mapping location → enriched metadata
        """
        
        logger.info(f"Enriching {len(locations_list)} (language, location) pairs...")
        
        for i, (lang, location_name) in enumerate(locations_list, 1):
            if lang not in self.lang_to_country:
                logger.warning(f"Unknown language {lang}, skipping {location_name}")
                continue
            
            country_qid = self.lang_to_country[lang]
            
            logger.info(f"[{i}/{len(locations_list)}] {lang}/{location_name}")
            
            # Create a unique key for the location
            location_key = f"{location_name} ({lang})"
            
            # Query Wikidata
            result = self.query_location_by_name(location_name, country_qid)
            
            if result:
                self.location_index[location_key] = {
                    'language': lang,
                    'country_qid': country_qid,
                    **result
                }
                logger.info(f"  ✓ Matched: {result['wikidata_id']} ({result['settlement_type']})")
            else:
                logger.warning(f"  ✗ No match found")
                self.failed_locations.append(location_key)
                self.location_index[location_key] = {
                    'language': lang,
                    'country_qid': country_qid,
                    'name': location_name,
                    'wikidata_id': 'unknown',
                    'matched': False
                }
            
            # Rate limiting: be respectful to Wikidata API (~1-2 seconds between queries)
            if i < len(locations_list):
                time.sleep(1.5)
        
        return self.location_index
    
    def save_index(self, output_file: str = 'location_index.json') -> None:
        """Save location index to JSON file"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.location_index, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\nSaved location index to {output_file}")
        self.print_summary()
    
    def print_summary(self) -> None:
        """Print summary of enrichment results"""
        total = len(self.location_index)
        matched = sum(1 for v in self.location_index.values() if v.get('matched', False))
        
        print("\n" + "="*70)
        print("LOCATION ENRICHMENT SUMMARY")
        print("="*70)
        print(f"Total (language, location) pairs processed: {total}")
        print(f"Successfully matched: {matched} ({100*matched/total:.1f}%)")
        print(f"Failed matches: {len(self.failed_locations)} ({100*len(self.failed_locations)/total:.1f}%)")
        print(f"Wikidata queries executed: {self.query_count}")
        
        if self.failed_locations:
            print(f"\nFailed locations (review these manually):")
            for loc in self.failed_locations[:15]:  # Show first 15
                print(f"  - {loc}")
            if len(self.failed_locations) > 15:
                print(f"  ... and {len(self.failed_locations) - 15} more")
        
        # Show sample of matched locations
        print(f"\nSample of matched locations:")
        for i, (key, value) in enumerate(self.location_index.items()):
            if i >= 5:
                break
            if value.get('matched'):
                print(f"  - {key}: {value['wikidata_id']} ({value['settlement_type']})")
        
        print("="*70 + "\n")


# MAIN EXECUTION
if __name__ == "__main__":
    
    # Step 1: Load and extract locations from your JSON
    enricher = LocationEnricher(lang_to_country=LANG_TO_COUNTRY)
    
    locations = enricher.extract_locations_from_json('language_data.json')
    
    # Step 2: Enrich with Wikidata
    enricher.enrich_locations(locations)
    
    # Step 3: Save results
    enricher.save_index('location_index.json')
    
    print("✓ Location enrichment complete!")
    print(f"✓ Location index saved to location_index.json")