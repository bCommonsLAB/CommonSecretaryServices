# Analyse: Mehrere Bilder und Seed-Mapping

## Kontext
Der Client soll mehrere Vorschaubilder in kleiner Aufloesung erzeugen
und fuer das gewaehlte Motiv spaeter eine hoehere Aufloesung mit
demselben Seed nachgenerieren koennen. Dazu muss der Server:
- mehrere Bilder generieren,
- die verwendeten Seeds pro Bild zurueckgeben,
- eine klare Zuordnung Bild <-> Seed liefern.

## Varianten
### Variante A: Mehrere Bilder via n (Provider-intern)
- `n` wird an den Provider gegeben.
- Seeds pro Bild sind nicht immer verfuegbar.
- Zuordnung Bild <-> Seed ist unsicher.

### Variante B: Mehrere Bilder via Einzel-Requests
- Server erzeugt pro Bild einen eigenen Request mit explizitem Seed.
- Seeds werden pro Bild zurueckgegeben.
- Zuordnung ist stabil und reproduzierbar.

### Variante C: Nur ein Bild, keine Seeds
- Aktueller Stand.
- Kein Preview-Workflow moeglich.

## Entscheidung
Variante B bietet die geforderte Seed-Zuordnung und ist reproduzierbar.
Sie ist langsamer, aber fuer Preview-Workflows am robustesten.
