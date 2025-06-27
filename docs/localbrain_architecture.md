# Local Brain Architecture

## Systemübersicht

Das Local Brain System besteht aus drei Hauptkomponenten:
- **Local Brains**: Linux-basierte Verarbeitungseinheiten
- **Knowledge Scouts**: Intelligente Wissensvermittler
- **Storage**: Verschiedene Cloud-Speicherlösungen

## Architektur-Diagramm

```mermaid
graph LR
    subgraph Local Brains
        LB1[LB1<br>Linux Box]
        LB2[LB2<br>Linux Box]
        LB3[LB3<br>Linux Box]
        LB4[LB4<br>Linux Box]
        LB5[LB5<br>Linux Box]
    end
    
    subgraph Knowledge Scouts
        KS1[KS1<br>Knowledge-Scout]
        KS2[KS2<br>Knowledge-Scout]
        KS3[KS3<br>Knowledge-Scout]
    end
    
    subgraph Storage
        GDrive[Google Drive]
        OneDrive[OneDrive]
        NextCloud[NextCloud]
    end
    
    LB1 --> KS1
    LB2 --> KS1
    LB3 --> KS2
    LB4 --> KS3
    LB5 --> KS2
    KS1 --> GDrive
    KS2 --> OneDrive
    KS3 --> NextCloud
```

## Komponenten-Beschreibung

### Local Brains (LB1-LB5)
- Linux-basierte Verarbeitungseinheiten
- Lokale Datenverarbeitung und Analyse
- Dezentrale Intelligenz

### Knowledge Scouts (KS1-KS3)
- Intelligente Wissensvermittler
- Koordinieren die Datenflüsse
- Optimieren Speicherzuweisungen

### Storage-Systeme
- **Google Drive**: Cloud-Speicher für KS1
- **OneDrive**: Cloud-Speicher für KS2  
- **NextCloud**: Cloud-Speicher für KS3

## Datenfluss

1. Local Brains verarbeiten lokale Daten
2. Knowledge Scouts sammeln und strukturieren die Informationen
3. Daten werden in entsprechende Cloud-Speicher übertragen
4. Zentrale Koordination durch Knowledge Scouts