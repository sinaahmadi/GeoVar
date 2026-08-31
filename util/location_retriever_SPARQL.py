import requests

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {
	"Accept": "application/sparql-results+json",
	"User-Agent": "MyGeolocBot/1.0 (your@email.com)"
}

def get_qid(location_name):
	"""Get Wikidata Q-ID for any location with a coordinate."""
	location_name = location_name.strip()
	if not location_name:
		return "NAN"
	query = f"""
	SELECT ?item WHERE {{
	  ?item rdfs:label "{location_name}"@it .
	  ?item wdt:P625 ?coord .
	}} LIMIT 1
	"""
	try:
		resp = requests.get(
			SPARQL_URL,
			params={"query": query, "format": "json"},
			headers=HEADERS,
			timeout=15
		)
		resp.raise_for_status()
		data = resp.json()
		if data["results"]["bindings"]:
			return data["results"]["bindings"][0]["item"]["value"].split("/")[-1]
		return "NAN"
	except Exception as e:
		print(f"Error for '{location_name}': {e}")
		return "NAN"


def get_qid_city(location_name):
	"""Get Wikidata Q-ID specifically for Italian comuni."""
	location_name = location_name.strip()
	if not location_name:
		return "NAN"
	query = f"""
	SELECT ?item WHERE {{
	  ?item rdfs:label "{location_name}"@it .
	  ?item wdt:P31 wd:Q747074 .
	}} LIMIT 1
	"""
	try:
		resp = requests.get(
			SPARQL_URL,
			params={"query": query, "format": "json"},
			headers=HEADERS,
			timeout=15
		)
		resp.raise_for_status()
		data = resp.json()
		if data["results"]["bindings"]:
			return data["results"]["bindings"][0]["item"]["value"].split("/")[-1]
		return "NAN"
	except Exception as e:
		print(f"Error for '{location_name}': {e}")
		return "NAN"
	
missing_locations = """
	Midsland
	Lies
	West-Terschelling
	Oosterend
	Hollum
	Schiermonnikoog
	Ferwerd
	Anjum
	Kollum
	Visvliet
	Oosterbierum
	Beetgum
	Bergum
	Jorwerd
	Bakkeveen
	Waskemeer
	Kloosterburen
	Warffum
	Leermens
	Groningen
	Nieuw-Scheemda
	Langelo
	Paterswolde
	Bellingwolde
	Een
	Spijkerboor
	Onstwedde
	Monster
	Hippolytushoef
	Schagerbrug
	Opperdoes
	Warmenhuizen
	Schoorl
	Oostwoud
	Lutjebroek
	Schermerhorn
	Oost-Knollendam
	Beverwijk
	Monnickendam
	Marken
	Amsterdam
	Weesp
	Huizen
	Eemnes Buiten
	Katwijk aan den Rijn
	De Kwakel
	Zoeterwoude
	Kamerik
	Utrecht
	Boskoop
	Hindeloopen
	Heerenveen
	Makkinga
	Rijs
	Lemmer
	Wolvega
	Diever
	Oldemarkt
	Steenwijk
	Giethoorn
	Urk
	Staphorst
	Wezep
	Wechterholt
	Epe
	Spakenburg
	Nijkerk
	Hoog Soeren
	Gorssel
	Lunteren
	Beekbergen
	Brummen
	Doesburg
	Appelscha
	Bovensmilde
	Hooghalen
	Rolde
	Gasselte
	Roswinkel
	Zuid-Sleen
	Emmen
	Emmer-Compascuum
	Erica
	Klazienaveen
	Zwartemeer
	Gramsbergen
	Coevorden
	Sibculo
	Vriezenveen
	Almelo
	Ootmarsum
	Rossum
	Noord Deurningen
	Enter
	Losser
	Eibergen
	Haaksbergen
	Groenlo
	Oostkerke
	Oostende
	Brugge
	Nieuwpoort
	Gistel
	Hertsberge
	Bray Dunes
	Veurne
	Diksmuide
	Torhout
	Tielt
	Oostvoorne
	Ouddorp
	Dirksland
	Zierikzee
	Stavenisse
	Steenbergen
	Oostkapelle
	Goes
	Scherpenisse
	Ossendrecht
	Oostburg
	Hoek
	Hulst
	Doel
	Sint Laureins
	Eeklo
	Oosteeklo
	Koewacht Be
	Sint-Niklaas
	Beveren
	Oostveld
	Aalter
	Lovendegem
	Oostakker
	Zaffelare
	Lokeren
	Gent
	Laarne
	Berlare
	Moerzeke
	Sint-Gillis-Bij-Dendermonde
	Malderen
	Rotterdam
	Lopik
	Culemborg
	Geldermalsen
	Sliedrecht
	Moerdijk
	Strijen
	Waspik
	Vlijmen
	Fijnaart
	Gilze
	Tilburg
	Nieuwmoer
	Zundert
	Meer
	Sint Lenaarts
	Weelde
	Kapellen
	's-Gravenwezel
	Beerse
	Arendonk
	Antwerpen
	Zandhoven
	Sint-Jozef-Olen
	Mol
	Lommel
	Lier
	Tongerlo
	Willebroek
	Mechelen
	Heist op den Berg
	Wolfsdonk
	Tessenderlo
	Didam
	Kilder
	Druten
	Nijmegen
	Groesbeek
	Reek
	Cuijk
	Vorstenbosch
	Liempde
	Gemert
	Meterik
	Arcen
	Veldhoven
	Asten
	Maasbree
	Tegelen
	Hamont
	Panningen
	Beesel
	Tungelroy
	Eksel
	Bree
	Maaseik
	Maasbracht
	Houthalen
	Opglabbeek
	Stokkem
	Aalten
	Winterswijk
	Gendringen
	Izenberge
	Poelkapelle
	Hooglede
	Roeselare
	Rubrouck
	Poperinge
	Ieper
	Moorsele
	Sainte-Marie-Cappel
	Steenvoorde
	Wulvergem
	Wervik
	Menen
	Kortrijk
	Wallon-Cappel
	Morbecque
	Deinze
	Merelbeke
	Mere
	Aalst
	Waregem
	Bevere
	Meilegem
	Strijpen
	Ninove
	Dilbeek
	Geraardsbergen
	Kooigem
	Ronse
	Herne
	Halle
	Humbeek
	Kampenhout
	Tremelo
	Lummen
	Brussel
	Leuven
	Boutersem
	Zoutleeuw
	Bosvoorde
	Overijse
	Tienen
	Sint-Truiden
	Walshoutem
	Jeuk
	Hasselt
	Genk
	Nuth
	Eigenbilzen
	Borgharen
	Itteren
	Ubachsberg
	Heerlen
	Nieuwenhagen
	Kerkrade
	Borgloon
	Tongeren
	Grote-Spouwen
	Gronsveld
	Rijckholt
	Vaals
	Lauw
	Merckeghem
"""
for location in missing_locations.splitlines():
	location = location.strip()
	qid = get_qid_city(location)
	if qid == "NAN":
		qid = get_qid(location)
	print(location, qid)
	