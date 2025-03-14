#!/usr/bin/env python3
"""
Command-Line-Tool zur Initialisierung und Verwaltung der MongoDB-Cache-Collections.
"""
import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta, UTC
from typing import List, Dict, Any, Optional, cast

from pymongo.collection import Collection
from pymongo.command_cursor import CommandCursor
from pymongo.database import Database

from utils.logger import ProcessingLogger

# Pfad zum Projektverzeichnis hinzufügen
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.insert(0, project_dir)

from src.core.mongodb.cache_setup import setup_mongodb_caching
from src.core.mongodb.connection import get_mongodb_database, close_mongodb_connection
from src.utils.logger import get_logger
from pymongo.results import DeleteResult

async def init_cache(force_recreate: bool = False) -> None:
    """
    Initialisiert die Cache-Collections und -Indizes.
    
    Args:
        force_recreate: Ob Collections neu erstellt werden sollen
    """
    logger: ProcessingLogger = get_logger(process_id="init-cache")
    logger.info(f"Initialisiere Cache-Collections (force_recreate={force_recreate})...")
    
    # Setup-Funktion aufrufen
    await setup_mongodb_caching(force_recreate)
    
    # MongoDB-Verbindung schließen
    close_mongodb_connection()
    logger.info("Cache-Initialisierung abgeschlossen.")

async def clear_cache(older_than_days: Optional[int] = None, collection: Optional[str] = None) -> None:
    """
    Löscht Cache-Einträge, optional nur ältere als eine bestimmte Anzahl von Tagen
    und/oder nur in einer bestimmten Collection.
    
    Args:
        older_than_days: Optional, Alter in Tagen, ab dem Einträge gelöscht werden sollen
        collection: Optional, Name der zu löschenden Collection
    """
    logger = get_logger(process_id="clear-cache")
    db = get_mongodb_database()
    
    # Bestimme die zu löschenden Collections
    collections: List[str] = []
    if collection:
        collections = [collection]
    else:
        # Alle Cache-Collections auflisten
        all_collections = cast(List[str], await db.list_collection_names())
        collections = [c for c in all_collections if c.endswith("_cache")]
    
    if not collections:
        logger.info("Keine Cache-Collections gefunden.")
        return
    
    # Filter vorbereiten
    delete_filter: Dict[str, Any] = {}
    if older_than_days:
        # Datum berechnen, vor dem Einträge gelöscht werden sollen
        cutoff_date = datetime.now(UTC) - timedelta(days=older_than_days)
        delete_filter["created_at"] = {"$lt": cutoff_date}
        logger.info(f"Lösche Einträge älter als {older_than_days} Tage (vor {cutoff_date.isoformat()})")
    else:
        logger.info("Lösche alle Cache-Einträge")
    
    # Einträge zählen und löschen
    total_deleted = 0
    
    for coll_name in collections:
        # Hier müssen wir dem Linter helfen zu verstehen, dass coll_name ein string ist
        # und wir eine Collection aus der Datenbank holen
        coll: Collection[Any] = db[coll_name]
        
        # Anzahl der Einträge prüfen
        count: int = cast(int, await coll.count_documents(delete_filter))
        
        if count == 0:
            logger.info(f"Keine zu löschenden Einträge in '{coll_name}' gefunden")
            continue
            
        # Einträge löschen
        result: DeleteResult = cast(DeleteResult, await coll.delete_many(delete_filter))
        deleted_count = int(result.deleted_count)
        logger.info(f"{deleted_count} Einträge aus '{coll_name}' gelöscht")
        total_deleted += deleted_count
    
    # MongoDB-Verbindung schließen
    close_mongodb_connection()
    logger.info(f"Cache-Bereinigung abgeschlossen: {total_deleted} Einträge gelöscht")

async def show_cache_stats() -> None:
    """
    Zeigt Statistiken zu den Cache-Collections an.
    """
    logger: ProcessingLogger = get_logger(process_id="cache-stats")
    db: Database[Any] = get_mongodb_database()
    
    # Alle Cache-Collections auflisten
    all_collections: List[str] = cast(List[str], await db.list_collection_names())
    cache_collections: List[str] = [c for c in all_collections if c.endswith("_cache")]
    
    if not cache_collections:
        logger.info("Keine Cache-Collections gefunden.")
        return
    
    print(f"\n{'Cache-Collection':<20} | {'Einträge':<10} | {'Größe (MB)':<12} | {'Ältester Eintrag':<20} | {'Neuester Eintrag':<20}")
    print("-" * 90)
    
    total_entries: int = 0
    total_size_mb: float = 0.0
    
    for coll_name in cache_collections:
        coll: Collection[Any] = db[coll_name]
        
        # Anzahl der Einträge
        count: int = cast(int, await coll.count_documents({}))
        
        # Aggregation für Statistiken
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_size_bytes": {"$sum": "$size_bytes"},
                    "oldest": {"$min": "$created_at"},
                    "newest": {"$max": "$created_at"}
                }
            }
        ]
        
        # Aggregation ausführen und Ergebnisse sammeln
        cursor: CommandCursor[Any] = coll.aggregate(pipeline)
        agg_results: List[Dict[str, Any]] = []
        async for doc in cursor:  # type: ignore
            agg_results.append(cast(Dict[str, Any], doc))
        
        if agg_results and len(agg_results) > 0:
            agg_stats: Dict[str, Any] = agg_results[0]
            # Größe in MB umrechnen
            size_bytes = int(agg_stats.get("total_size_bytes", 0))
            size_mb = round(size_bytes / (1024 * 1024), 2)
            
            # Datum-Formatierung
            oldest: Any = agg_stats.get("oldest", "N/A")
            newest: Any = agg_stats.get("newest", "N/A")
            
            if isinstance(oldest, datetime):
                oldest = oldest.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(newest, datetime):
                newest = newest.strftime("%Y-%m-%d %H:%M:%S")
                
            print(f"{coll_name:<20} | {count:<10} | {size_mb:<12} | {oldest:<20} | {newest:<20}")
            
            total_entries += count
            total_size_mb += size_mb
        else:
            print(f"{coll_name:<20} | {count:<10} | {'N/A':<12} | {'N/A':<20} | {'N/A':<20}")
            total_entries += count
    
    print("-" * 90)
    print(f"{'GESAMT':<20} | {total_entries:<10} | {total_size_mb:<12} | {'':<20} | {'':<20}")
    
    # MongoDB-Verbindung schließen
    close_mongodb_connection()

def main():
    """Hauptfunktion"""
    parser = argparse.ArgumentParser(description="MongoDB-Cache-Verwaltung")
    
    # Subparser für verschiedene Befehle
    subparsers = parser.add_subparsers(dest="command", help="Befehl")
    
    # Befehl: init
    init_parser: argparse.ArgumentParser = subparsers.add_parser("init", help="Cache-Collections initialisieren")
    init_parser.add_argument("--force", action="store_true", help="Collections neu erstellen")
    
    # Befehl: clear
    clear_parser: argparse.ArgumentParser = subparsers.add_parser("clear", help="Cache-Einträge löschen")
    clear_parser.add_argument("--days", type=int, help="Nur Einträge älter als X Tage löschen")
    clear_parser.add_argument("--collection", help="Nur in der angegebenen Collection löschen")
    
    # Befehl: stats
    subparsers.add_parser("stats", help="Cache-Statistiken anzeigen")
    
    args: argparse.Namespace = parser.parse_args()
    
    # Befehl ausführen
    if args.command == "init":
        asyncio.run(init_cache(args.force))
    elif args.command == "clear":
        asyncio.run(clear_cache(args.days, args.collection))
    elif args.command == "stats":
        asyncio.run(show_cache_stats())
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 