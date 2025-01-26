# Metadaten-Konzept für wissenschaftliche Medienarchivierung

## 1. Einführung

Dieses Dokument beschreibt die Metadatenstruktur für die wissenschaftliche Medienarchivierung. Die Struktur wurde entwickelt, um verschiedene Medientypen (Bücher, Videos, Audio, etc.) mit standardisierten, maschinenlesbaren Metadaten zu versehen.

### 1.1 Ziele
- Standardisierte Erfassung wissenschaftlicher Medien
- Kompatibilität mit bibliothekarischen Standards (Dublin Core, BibTeX)
- Flexible Erweiterbarkeit für verschiedene Medientypen
- Maschinenlesbare und durchsuchbare Metadaten

### 1.2 Designprinzipien
- Flache Hierarchie für einfache Verarbeitung
- Präfix-basierte Gruppierung von Eigenschaften
- Strikte Typisierung aller Felder
- Klare Trennung von technischen und inhaltlichen Metadaten
- Listen werden als komma-separierte Strings gespeichert

## 2. Grundlegende Metadatenstruktur

### 2.1 Basis-Metadaten (BaseMetadata)

Die Basis-Schnittstelle, von der alle anderen Metadaten-Typen erben:

```typescript
interface BaseMetadata {
  type: string;    // Art der Metadaten
  created: string; // Erstellungszeitpunkt (ISO 8601)
  modified: string; // Letzter Änderungszeitpunkt (ISO 8601)
}
```

### 2.2 Technische Metadaten (TechnicalMetadata)

Automatisch extrahierbare technische Informationen über die Mediendatei:

```typescript
interface TechnicalMetadata extends BaseMetadata {
  file_size: number;           // Dateigröße in Bytes
  file_mime: string;           // Dateityp (z.B. audio/mp3)
  file_extension: string;      // Dateiendung
  
  // Medienspezifische Details
  media_duration?: number;     // Länge des Mediums in Sekunden
  media_bitrate?: number;      // Bitrate in kbps
  media_codec?: string;        // Verwendeter Codec
  media_resolution?: string;   // Auflösung (bei Video, z.B. "1920x1080")
  media_format?: string;       // Medienformat (z.B. "MP3", "H.264")
  media_channels?: number;     // Anzahl der Audiokanäle
  media_samplerate?: number;   // Abtastrate in Hz
  
  // Bildspezifische Details (für Bilder und Videos)
  image_width?: number;        // Bildbreite in Pixeln
  image_height?: number;       // Bildhöhe in Pixeln
  image_colorspace?: string;   // Farbraum (z.B. "RGB", "CMYK")
  image_dpi?: number;         // Auflösung in DPI
  
  // Dokumentspezifische Details (für PDFs, etc.)
  doc_pages?: number;         // Anzahl der Seiten
  doc_wordcount?: number;     // Anzahl der Wörter
  doc_software?: string;      // Erstellungssoftware
  doc_encrypted?: boolean;    // Verschlüsselungsstatus
}
```

### 2.3 Inhaltliche Metadaten (ContentMetadata)

Beschreibende Metadaten für den Inhalt der Ressource:

```typescript
interface ContentMetadata extends BaseMetadata {
  // Bibliographische Grunddaten
  title: string;                    // Haupttitel des Werks
  subtitle?: string;                // Untertitel
  authors?: string;                 // Komma-separierte Liste der Autoren
  publisher?: string;               // Verlag
  publicationDate?: string;         // Erscheinungsdatum
  isbn?: string;                    // ISBN (bei Büchern)
  doi?: string;                     // Digital Object Identifier
  edition?: string;                 // Auflage
  language?: string;                // Sprache (ISO 639-1)
  
  // Wissenschaftliche Klassifikation
  subject_areas?: string;           // Komma-separierte Liste der Fachgebiete
  keywords?: string;                // Komma-separierte Liste der Schlüsselwörter
  abstract?: string;                // Kurzzusammenfassung
  
  // Räumliche und zeitliche Einordnung
  temporal_start?: string;          // Beginn des behandelten Zeitraums
  temporal_end?: string;            // Ende des behandelten Zeitraums
  temporal_period?: string;         // Bezeichnung der Periode
  spatial_location?: string;        // Ortsname
  spatial_latitude?: number;        // Geografische Breite
  spatial_longitude?: number;       // Geografische Länge
  spatial_habitat?: string;         // Lebensraum/Biotop
  spatial_region?: string;          // Region/Gebiet
  
  // Rechte und Lizenzen
  rights_holder?: string;           // Rechteinhaber
  rights_license?: string;          // Lizenz
  rights_access?: string;           // Zugriffsrechte
  rights_usage?: string;            // Komma-separierte Liste der Nutzungsbedingungen
  rights_attribution?: string;       // Erforderliche Namensnennung
  rights_commercial?: boolean;       // Kommerzielle Nutzung erlaubt
  rights_modifications?: boolean;    // Modifikationen erlaubt
  
  // Medienspezifische Metadaten
  resource_type?: string;           // Art der Ressource
  resource_format?: string;         // Physisches/digitales Format
  resource_extent?: string;         // Umfang
  
  // Quellenangaben
  source_title?: string;            // Titel der Quelle
  source_type?: string;             // Art der Quelle
  source_identifier?: string;        // Eindeutige Kennung der Quelle
  
  // Digitale Plattform
  platform_type?: string;           // Art der Plattform
  platform_url?: string;            // URL zur Ressource
  platform_id?: string;             // Plattform-spezifische ID
  platform_uploader?: string;        // Uploader/Kanal
  platform_category?: string;        // Plattform-Kategorie
  platform_language?: string;        // Komma-separierte Liste der unterstützten Sprachen
  platform_region?: string;          // Komma-separierte Liste der verfügbaren Regionen
  platform_age_rating?: string;      // Altersfreigabe
  platform_subscription?: string;    // Erforderliches Abonnement
  
  // Event-spezifische Details
  event_type?: string;              // Art der Veranstaltung
  event_start?: string;             // Startzeit (ISO 8601)
  event_end?: string;               // Endzeit (ISO 8601)
  event_timezone?: string;          // Zeitzone
  event_format?: string;            // Veranstaltungsformat
  event_platform?: string;          // Verwendete Plattform
  event_recording_url?: string;      // Link zur Aufzeichnung
  
  // Social Media spezifisch
  social_platform?: string;         // Plattform
  social_handle?: string;           // Benutzername/Handle
  social_post_id?: string;          // Original Post-ID
  social_post_url?: string;         // Permalink zum Beitrag
  social_metrics_likes?: number;    // Anzahl der Likes
  social_metrics_shares?: number;   // Anzahl der Shares
  social_metrics_comments?: number; // Anzahl der Kommentare
  social_metrics_views?: number;    // Anzahl der Aufrufe
  social_thread?: string;          // Komma-separierte Liste der IDs verknüpfter Beiträge
  
  // Blog/Artikel spezifisch
  blog_url?: string;               // Permalink zum Artikel
  blog_section?: string;           // Rubrik/Kategorie
  blog_series?: string;            // Zugehörige Serie/Reihe
  blog_reading_time?: number;      // Geschätzte Lesezeit in Minuten
  blog_tags?: string;              // Komma-separierte Liste der Blog-spezifischen Tags
  blog_comments_url?: string;      // Link zu Kommentaren
  
  // Community und Engagement
  community_target?: string;       // Komma-separierte Liste der Zielgruppen
  community_hashtags?: string;     // Komma-separierte Liste der verwendeten Hashtags
  community_mentions?: string;     // Komma-separierte Liste der erwähnten Accounts/Personen
  community_context?: string;      // Kontext/Anlass
  
  // Qualitätssicherung
  quality_review_status?: string;  // Review-Status
  quality_fact_checked?: boolean;  // Faktencheck durchgeführt
  quality_peer_reviewed?: boolean; // Peer-Review durchgeführt
  quality_verified_by?: string;    // Komma-separierte Liste der Verifizierer
  
  // Wissenschaftliche Zusatzinformationen
  citations?: string;              // Komma-separierte Liste der zitierten Werke
  methodology?: string;            // Verwendete Methodik
  funding?: string;                // Förderung/Finanzierung
  
  // Verwaltung
  collection?: string;             // Zugehörige Sammlung
  archival_number?: string;        // Archivnummer
  status?: string;                 // Status
  
  // Digitale Publikationsdetails
  digital_published?: string;      // Erstveröffentlichung online (ISO 8601)
  digital_modified?: string;       // Letzte Online-Aktualisierung (ISO 8601)
  digital_version?: string;        // Versionsnummer/Stand
  digital_status?: string;         // Publikationsstatus
}
```

## 3. YAML-Implementierung

Die Metadaten werden in YAML-Format im Header von Markdown-Dateien gespeichert:

### 3.1 Grundregeln
- Flache Struktur mit Präfixen zur Gruppierung
- Klare Trennung durch Kommentare
- Konsistente Einrückung
- UTF-8 Kodierung
- Listen werden als komma-separierte Strings gespeichert

### 3.2 Beispiel für ein wissenschaftliches Buch:

```yaml
---
# Bibliographische Grunddaten
title: "Ökosysteme der Nordsee"
subtitle: "Eine Bestandsaufnahme"
authors: "Dr. Maria Schmidt, Prof. Hans Meyer"
publisher: "Wissenschaftsverlag"
publicationDate: "2023-05-15"
isbn: "978-3-12345-678-9"
language: "de"

# Wissenschaftliche Klassifikation
subject_areas: "Meeresbiologie, Ökologie"
keywords: "Nordsee, Wattenmeer, Biodiversität"
abstract: "Eine umfassende Analyse der Ökosysteme im Wattenmeer..."

# Räumliche und zeitliche Einordnung
temporal_start: "2020-01"
temporal_end: "2022-12"
spatial_location: "Sylt"
spatial_latitude: 54.8985
spatial_longitude: 8.3125
spatial_habitat: "Wattenmeer"
spatial_region: "Nordsee"

# Rechte und Lizenzen
rights_holder: "Wissenschaftsverlag GmbH"
rights_license: "CC BY-SA 4.0"

# Medienspezifische Metadaten
resource_type: "Book"
resource_format: "PDF"
resource_extent: "342 Seiten"

# Verwaltung
collection: "Meeresökologie"
status: "verified"
---
```

### 3.3 Beispiel: Social Media Beitrag

```yaml
---
# Basis-Metadaten
type: "social_media_post"
created: "2024-03-15T14:30:00Z"
modified: "2024-03-15T14:30:00Z"
id: "post_2024_03_15_001"

# Technische Metadaten
file_size: 2048576
file_mime: "video/mp4"
file_created: "2024-03-15T14:25:00Z"
file_modified: "2024-03-15T14:28:00Z"
media_duration: "00:02:45"
media_quality: "1080p"
media_framerate: "30fps"
media_codec: "h264"

# Content Metadaten
title: "Klimawandel in den Alpen: Gletscherrückgang 2024"
authors: "Dr. Sarah Schmidt"
language: "de"
subject_areas: "Klimatologie, Glaziologie"
keywords: "Klimawandel, Gletscher, Alpen, Umweltmonitoring"
abstract: "Zeitrafferaufnahmen zeigen den dramatischen Rückgang des Hintereisferners im Vergleich zum Vorjahr."

# Räumliche und zeitliche Einordnung
temporal_start: "2023-03-15"
temporal_end: "2024-03-14"
spatial_location: "Hintereisferner"
spatial_latitude: 46.798333
spatial_longitude: 10.770556
spatial_region: "Ötztaler Alpen"

# Rechte und Lizenzen
rights_holder: "Universität Innsbruck"
rights_license: "CC BY-SA 4.0"
rights_usage: "Bildungszwecke, Wissenschaftliche Nutzung"
rights_attribution: "© Universität Innsbruck - Institut für Atmosphären- und Kryosphärenwissenschaften"

# Social Media spezifisch
social_platform: "twitter"
social_handle: "@GlacierScience"
social_post_id: "170125847392158720"
social_post_url: "https://twitter.com/GlacierScience/status/170125847392158720"
social_metrics_likes: 2453
social_metrics_shares: 1876
social_metrics_comments: 342
social_metrics_views: 45678
social_thread: "170125847392158721, 170125847392158722"

# Community und Engagement
community_target: "Wissenschaftler, Umweltinteressierte, Klimaaktivisten"
community_hashtags: "#Klimawandel, #Gletscher, #Klimaforschung, #Alpen"
community_mentions: "@UniInnsbruck, @Klimaforschung"
community_context: "Jährliche Dokumentation der Gletscherveränderungen"

# Qualitätssicherung
quality_review_status: "verified"
quality_fact_checked: true
quality_verified_by: "Institut für Atmosphären- und Kryosphärenwissenschaften"

# Plattform-Details
platform_type: "twitter"
platform_url: "https://twitter.com/GlacierScience/status/170125847392158720"
platform_category: "Wissenschaftskommunikation"
platform_language: "de, en"
platform_region: "AT, DE, CH"
---
```

### 3.4 Beispiel: Konferenz-Vortrag

```yaml
---
# Basis-Metadaten
type: "conference_talk"
created: "2025-02-02T12:10:00+01:00"
modified: "2025-02-02T12:10:00+01:00"
id: "fosdem_2025_5972"

# Content Metadaten
title: "Disrupting the destruction of our natural world with openness"
authors: ["Tobias Augspurger"]
language: "en"
subject_areas: ["Open Source", "Umweltschutz", "Nachhaltigkeit"]
keywords: ["FOSS", "Klimawandel", "Biodiversität", "Open Science", "Nachhaltigkeit"]
abstract: "Despite the transformative power of free and open-source software (FOSS) across various sectors, its impact on environmental preservation remains largely invisible. The Open Sustainable Technology community has developed strategies to make FOSS essential in fighting climate change and biodiversity loss."

# Event-spezifische Details
event_type: "Lightning Talk"
event_start: "2025-02-02T12:10:00+01:00"
event_end: "2025-02-02T12:25:00+01:00"
event_timezone: "Europe/Brussels"
event_format: "physical"
event_platform: "FOSDEM 2025"
event_recording_url: "https://video.fosdem.org/2025/H.2215/"
event_room: "H.2215 (Ferrer)"

# Räumliche Einordnung
spatial_location: "ULB Solbosch Campus"
spatial_latitude: 50.8137
spatial_longitude: 4.3843
spatial_region: "Brussels, Belgium"

# Rechte und Lizenzen
rights_holder: "FOSDEM"
rights_license: "CC BY 2.0 BE"
rights_usage: ["Bildungszwecke", "Öffentliche Vorführung"]
rights_attribution: "FOSDEM 2025"

# Community und Engagement
community_target: ["Entwickler", "Umweltaktivisten", "Open Source Community"]
community_hashtags: ["#FOSDEM2025", "#OpenSource", "#Sustainability"]
community_context: "FOSDEM 2025 Lightning Talk"

# Qualitätssicherung
quality_review_status: "accepted"
quality_verified_by: ["FOSDEM Program Committee"]

# Plattform-Details
platform_type: "conference"
platform_url: "https://fosdem.org/2025/schedule/event/fosdem-2025-5972-disrupting-the-destruction-of-our-natural-world-with-openness/"
platform_category: "Lightning Talks"
platform_language: ["en"]
platform_region: ["BE", "EU"]

# Verwandte Ressourcen
related_resources:
  - name: "Open Sustainable Technology"
    url: "https://opensustain.tech/"
  - name: "OSS for Climate Podcast"
    url: "https://ossforclimatepodcast.org/"
  - name: "ClimateTriage"
    url: "https://climatetriage.com/"
---
```

### 3.5 Beispiel: YouTube Video

```yaml
---
# Basis-Metadaten
type: "video"
created: "2025-01-20T10:00:00Z"
modified: "2025-01-20T10:00:00Z"
id: "yt_WneT4gliSbY"

# Technische Metadaten
file_mime: "video/mp4"
media_duration: "00:13:37"
media_quality: "1080p"
media_framerate: "30fps"
media_codec: "h264"

# Content Metadaten
title: "NFL Sunday Ticket"
authors: ["NFL"]
language: "en"
subject_areas: ["Sport", "American Football"]
keywords: ["NFL", "Football", "Sunday Ticket", "Sport"]

# Rechte und Lizenzen
rights_holder: "NFL"
rights_license: "Standard YouTube License"
rights_usage: ["Nur Ansicht"]
rights_attribution: "© 2025 NFL"

# Plattform-Details
platform_type: "youtube"
platform_url: "https://www.youtube.com/watch?v=WneT4gliSbY"
platform_id: "WneT4gliSbY"
platform_uploader: "NFL"
platform_category: "Sport"
platform_language: ["en"]
platform_region: ["US", "INT"]
platform_age_rating: "Alle"

# Social Media Metriken
social_metrics_likes: 0
social_metrics_views: 0
social_metrics_comments: 0

# Community und Engagement
community_target: ["NFL Fans", "Sportinteressierte"]
community_hashtags: ["#NFL", "#Football", "#SundayTicket"]
community_context: "NFL Programm-Ankündigung"

# Qualitätssicherung
quality_review_status: "verified"
quality_verified_by: ["YouTube Content ID"]

# Verwaltung
status: "published"
digital_published: "2025-01-20T10:00:00Z"
digital_modified: "2025-01-20T10:00:00Z"
digital_status: "published"
---
```

### 3.6 Beispiel: Online-Nachrichtenartikel

```yaml
---
# Basis-Metadaten
type: "article"
created: "2025-01-22T00:00:00+01:00"
modified: "2025-01-22T00:00:00+01:00"
id: "salto_2025_01_22_inklusion"

# Content Metadaten
title: "Inklusion wird belohnt"
subtitle: "Geld als Gegenleistung für Inklusion"
authors: ["Lukas Kafmann"]
language: "de"
subject_areas: ["Gesellschaft", "Arbeitsmarkt", "Sozialpolitik"]
keywords: ["Inklusion", "Arbeitsmarkt", "Südtirol", "ProAbility", "Behinderung"]
abstract: "Mit einem neuen Prämiensystem will das Land Südtirol Unternehmen unterstützen, die Menschen mit Beeinträchtigung einstellen. "ProAbility" startet im Februar."

# Digitale Publikationsdetails
digital_published: "2025-01-22T00:00:00+01:00"
digital_modified: "2025-01-22T00:00:00+01:00"
digital_status: "published"

# Blog/Artikel spezifisch
blog_url: "https://salto.bz/de/article/22012025/geld-als-gegenleistung-fur-inklusion"
blog_section: "Gesellschaft"
blog_tags: ["Arbeitsmarkt", "Gesellschaft", "Südtirol"]
blog_reading_time: 5

# Räumliche Einordnung
spatial_location: "Südtirol"
spatial_region: "Autonome Provinz Bozen"

# Rechte und Lizenzen
rights_holder: "Demos 2.0 Gen./Soc.coop."
rights_license: "© 2025 by Demos 2.0"
rights_attribution: "salto.bz"

# Plattform-Details
platform_type: "news"
platform_url: "https://salto.bz"
platform_category: "Nachrichten"
platform_language: ["de"]
platform_region: ["IT-BZ"]

# Quellenangaben
source_title: "salto.bz"
source_type: "Online-Nachrichtenportal"
source_identifier: "MwSt.-Nr 02765230210 ISSN 2704-6672"

# Community und Engagement
community_target: ["Allgemeine Öffentlichkeit", "Arbeitgeber", "Sozialarbeiter"]
community_context: "Arbeitsmarktpolitische Maßnahme in Südtirol"

# Qualitätssicherung
quality_review_status: "published"
quality_fact_checked: true

# Verwaltung
status: "published"
collection: "Gesellschaft"

# Verwandte Artikel
related_resources:
  - name: "Der Schulbus, der nicht kommt"
    url: "https://salto.bz/de/article/transport-behinderung"
  - name: "Inklusion, ein Privileg?"
    url: "https://salto.bz/de/article/bildung"
---
```

## 4. Validierung und Qualitätssicherung

### 4.1 Pflichtfelder
- `title`: Titel des Werks
- `authors`: Liste der Autoren
- `language`: ISO 639-1 Sprachcode
- `resource_type`: Art der Ressource

### 4.2 Formatvorgaben
- Datumsangaben: ISO 8601 (YYYY-MM-DD)
- Sprachen: ISO 639-1
- Koordinaten: Dezimalgrad
- URLs: Vollständige URLs mit Protokoll

### 4.3 Validierungsregeln
- Typ-Überprüfung aller Felder
- Formatvalidierung für spezielle Felder
- Konsistenzprüfung zusammenhängender Felder

## 5. Erweiterbarkeit

### 5.1 Neue Medientypen
- Erweiterung der technischen Metadaten
- Spezifische Formatangaben
- Zusätzliche Qualitätsmetriken

### 5.2 Zusätzliche Standards
- Integration weiterer Bibliotheksstandards
- Fachspezifische Erweiterungen
- Plattformspezifische Metadaten

### 5.3 Versionierung
- Semantic Versioning für Schemaänderungen
- Abwärtskompatibilität beachten
- Migrationspfade definieren 