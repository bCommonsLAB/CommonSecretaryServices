"""
@fileoverview RAG Processor - Embedding-Prozessor für RAG

@description
RAG Processor für das Einbetten von Markdown-Dokumenten in Vektoren.
This processor handles:
- Markdown document chunking with structure awareness
- Embedding generation using a configurable embedding model (default: voyage-context-3)

Features:
- Contextualized chunk embeddings with voyage-context-3 (oder konfiguriertem Modell)
- Markdown-aware chunking (respects headings, paragraphs)
- Configurable chunk size, overlap, and embedding dimensions

@module processors.rag_processor

@exports
- RAGProcessor: Class - RAG embedding processor

@usedIn
- src.api.routes.rag_routes: API endpoint für RAG-Embedding-Operationen

@dependencies
- External: voyageai - Voyage API client
- Internal: src.processors.base_processor - BaseProcessor base class
- Internal: src.core.models.rag - RAG models (RAGChunk, RAGEmbeddingResult, etc.)
- Internal: src.core.config - Configuration
- Internal: src.core.llm - LLM config infrastructure
"""
# pyright: reportMissingImports=false, reportUnknownMemberType=false

import os
import re
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
import time

try:
    import voyageai
except ImportError:
    voyageai = None

from src.core.models.rag import RAGChunk, RAGEmbeddingResult
from src.core.models.base import ProcessInfo
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.processors.base_processor import BaseProcessor
from src.core.config import Config
from src.core.llm import LLMConfigManager


class RAGProcessor(BaseProcessor[RAGEmbeddingResult]):
    """
    RAG-Prozessor für Embedding von Markdown-Dokumenten.
    
    Verarbeitet Markdown-Dokumente, erstellt Embeddings mit einem konfigurierten
    Embedding-Modell (Standard: voyage-context-3) und gibt die Chunks mit
    Embeddings zurück. Es findet keine Speicherung in MongoDB und keine Query-
    Verarbeitung mehr statt.
    """
    
    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        process_id: Optional[str] = None,
        parent_process_info: Optional[ProcessInfo] = None
    ):
        """
        Initialisiert den RAGProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(
            resource_calculator=resource_calculator,
            process_id=process_id,
            parent_process_info=parent_process_info
        )
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            rag_config = processor_config.get('rag', {})
            
            # Voyage API Konfiguration
            voyage_api_key = os.getenv('VOYAGE_API_KEY') or rag_config.get('voyage_api_key')
            if not voyage_api_key:
                raise ProcessingError(
                    "VOYAGE_API_KEY nicht gefunden. Bitte setzen Sie die Umgebungsvariable "
                    "oder konfigurieren Sie 'processors.rag.voyage_api_key' in config.yaml"
                )
            
            # Voyage Client initialisieren
            if voyageai is None:
                raise ProcessingError(
                    "voyageai Paket nicht installiert. Bitte installieren Sie es mit: pip install voyageai"
                )
            
            self.voyage_client = voyageai.Client(api_key=voyage_api_key)
            
            # RAG-spezifische Konfiguration
            # Embedding-Defaults aus LLM-Config (Use-Case EMBEDDING) lesen und mit
            # processors.rag.* zusammenführen.
            self.llm_config_manager = LLMConfigManager()
            default_embedding_model, _default_embedding_provider, default_embedding_dims = (
                self.llm_config_manager.get_embedding_defaults()
            )

            self.embedding_model: str = rag_config.get(
                'embedding_model',
                default_embedding_model or 'voyage-context-3'
            )
            self.embedding_dimensions: int = rag_config.get(
                'embedding_dimensions',
                default_embedding_dims or 2048
            )
            self.chunk_size: int = rag_config.get('chunk_size', 1000)
            self.chunk_overlap: int = rag_config.get('chunk_overlap', 200)
            
            self.logger.info("RAGProcessor initialisiert", extra={
                "embedding_model": self.embedding_model,
                "embedding_dimensions": self.embedding_dimensions,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap
            })
            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des RAGProcessors", error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")
    
    def _chunk_markdown(
        self,
        text: str,
        document_id: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> List[RAGChunk]:
        """
        Zerlegt Markdown-Text in Chunks unter Berücksichtigung der Struktur.
        
        Args:
            text: Der Markdown-Text
            document_id: Die Dokument-ID
            chunk_size: Größe der Chunks (Standard aus Config)
            chunk_overlap: Overlap zwischen Chunks (Standard aus Config)
            
        Returns:
            List[RAGChunk]: Liste der Chunks
        """
        chunk_size = chunk_size or self.chunk_size
        chunk_overlap = chunk_overlap or self.chunk_overlap
        
        if chunk_size <= 0:
            raise ValueError("Chunk-Größe muss positiv sein")
        if chunk_overlap < 0:
            raise ValueError("Chunk-Overlap darf nicht negativ sein")
        if chunk_overlap >= chunk_size:
            raise ValueError("Chunk-Overlap muss kleiner als Chunk-Größe sein")
        
        chunks: List[RAGChunk] = []
        
        # Teile Text in Absätze auf (doppelte Zeilenumbrüche)
        paragraphs = re.split(r'\n\n+', text)
        
        current_chunk_text: List[str] = []
        current_chunk_length = 0
        current_heading: Optional[str] = None
        chunk_index = 0
        start_char = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # Prüfe ob Absatz eine Überschrift ist
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', para)
            if heading_match:
                # Überschrift gefunden - speichere als Kontext
                current_heading = heading_match.group(2).strip()
                # Überschrift zum aktuellen Chunk hinzufügen
                if current_chunk_text:
                    # Überschrift am Anfang des nächsten Chunks einfügen
                    para = f"{para}\n\n"
                else:
                    para = f"{para}\n\n"
            
            para_length = len(para)
            
            # Wenn Absatz allein zu groß ist, teile ihn weiter
            if para_length > chunk_size:
                # Speichere aktuellen Chunk falls vorhanden
                if current_chunk_text:
                    chunk_text = '\n\n'.join(current_chunk_text)
                    end_char = start_char + len(chunk_text)
                    chunks.append(RAGChunk(
                        text=chunk_text,
                        chunk_index=chunk_index,
                        document_id=document_id,
                        heading_context=current_heading,
                        start_char=start_char,
                        end_char=end_char,
                        metadata={}
                    ))
                    chunk_index += 1
                    start_char = end_char
                    current_chunk_text = []
                    current_chunk_length = 0
                
                # Teile großen Absatz in kleinere Teile
                words = para.split()
                temp_text: List[str] = []
                temp_length = 0
                
                for word in words:
                    word_with_space = word + ' '
                    word_length = len(word_with_space)
                    
                    if temp_length + word_length > chunk_size:
                        if temp_text:
                            chunk_text = ' '.join(temp_text)
                            end_char = start_char + len(chunk_text)
                            chunks.append(RAGChunk(
                                text=chunk_text,
                                chunk_index=chunk_index,
                                document_id=document_id,
                                heading_context=current_heading,
                                start_char=start_char,
                                end_char=end_char,
                                metadata={}
                            ))
                            chunk_index += 1
                            start_char = end_char
                            temp_text = []
                            temp_length = 0
                    
                    temp_text.append(word)
                    temp_length += word_length
                
                # Rest als neuen Chunk
                if temp_text:
                    current_chunk_text = temp_text
                    current_chunk_length = temp_length
                continue
            
            # Prüfe ob Absatz in aktuellen Chunk passt
            if current_chunk_length + para_length + 2 <= chunk_size:  # +2 für \n\n
                current_chunk_text.append(para)
                current_chunk_length += para_length + 2
            else:
                # Aktuellen Chunk speichern
                if current_chunk_text:
                    chunk_text = '\n\n'.join(current_chunk_text)
                    end_char = start_char + len(chunk_text)
                    chunks.append(RAGChunk(
                        text=chunk_text,
                        chunk_index=chunk_index,
                        document_id=document_id,
                        heading_context=current_heading,
                        start_char=start_char,
                        end_char=end_char,
                        metadata={}
                    ))
                    chunk_index += 1
                    
                    # Overlap: Nimm letzten Teil des vorherigen Chunks
                    if chunk_overlap > 0 and len(chunk_text) > chunk_overlap:
                        overlap_text = chunk_text[-chunk_overlap:]
                        current_chunk_text = [overlap_text, para]
                        current_chunk_length = len(overlap_text) + para_length + 2
                        start_char = end_char - chunk_overlap
                    else:
                        current_chunk_text = [para]
                        current_chunk_length = para_length
                        start_char = end_char
                else:
                    current_chunk_text = [para]
                    current_chunk_length = para_length
        
        # Letzten Chunk speichern
        if current_chunk_text:
            chunk_text = '\n\n'.join(current_chunk_text)
            end_char = start_char + len(chunk_text)
            chunks.append(RAGChunk(
                text=chunk_text,
                chunk_index=chunk_index,
                document_id=document_id,
                heading_context=current_heading,
                start_char=start_char,
                end_char=end_char,
                metadata={}
            ))
        
        return chunks
    
    def _generate_embeddings(
        self,
        texts: List[str],
        input_type: str = "document",
        model: Optional[str] = None
    ) -> List[List[float]]:
        """
        Generiert Embeddings für eine Liste von Texten mit dem konfigurierten Embedding-Modell.
        
        Args:
            texts: Liste der Texte zum Einbetten
            input_type: Typ des Inputs ("document" oder "query")
            
        Returns:
            List[List[float]]: Liste der Embeddings
        """
        if not texts:
            return []
        
        try:
            # Effektives Embedding-Modell wählen: explizit angefordert oder Default.
            effective_model: str = model or self.embedding_model

            # Voyage API unterstützt Batch-Processing
            # Für voyage-context-3 müssen alle Chunks eines Dokuments zusammen verarbeitet werden
            if input_type == "document":
                # Batch-Embedding für alle Chunks
                response: Any = self.voyage_client.embed(  # type: ignore
                    texts=texts,
                    model=effective_model,
                    input_type=input_type
                )
                return response.embeddings  # type: ignore
            else:
                # Query-Embedding
                response = self.voyage_client.embed(  # type: ignore
                    texts=texts,
                    model=effective_model,
                    input_type=input_type
                )
                return response.embeddings  # type: ignore
                
        except Exception as e:
            self.logger.error("Fehler bei der Embedding-Generierung", error=e)
            raise ProcessingError(f"Fehler bei der Embedding-Generierung: {str(e)}")
    
    async def embed_document_for_client(
        self,
        text: str,
        document_id: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        embedding_model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RAGEmbeddingResult:
        """
        Bettet ein Markdown-Dokument ein und gibt das Ergebnis zurück.
        
        Diese Methode ist für Clients gedacht, die die Chunks und Embeddings selbst
        persistieren möchten (z.B. in einer eigenen Vector-Datenbank). Es findet
        keine Speicherung im Backend statt.
        """
        start_time = time.time()
        
        try:
            # Effektives Embedding-Modell bestimmen (Client-Wahl oder Default).
            effective_embedding_model: str = embedding_model or self.embedding_model
            # Dokument-ID generieren falls nicht vorhanden
            if not document_id:
                document_id = str(uuid.uuid4())
            
            # Chunking durchführen
            self.logger.info("Starte Chunking (client)", extra={"document_id": document_id})
            chunks = self._chunk_markdown(text, document_id, chunk_size, chunk_overlap)
            self.logger.info(f"Chunking abgeschlossen (client): {len(chunks)} Chunks erstellt")
            
            if not chunks:
                raise ProcessingError("Keine Chunks erstellt")
            
            # Embeddings generieren
            self.logger.info("Starte Embedding-Generierung (client)", extra={"chunk_count": len(chunks)})
            chunk_texts = [chunk.text for chunk in chunks]
            embeddings = self._generate_embeddings(
                chunk_texts,
                input_type="document",
                model=effective_embedding_model
            )
            
            if len(embeddings) != len(chunks):
                raise ProcessingError(
                    f"Anzahl der Embeddings ({len(embeddings)}) stimmt nicht mit "
                    f"Anzahl der Chunks ({len(chunks)}) überein"
                )
            
            # Embeddings zu Chunks hinzufügen
            chunks_with_embeddings: List[RAGChunk] = []
            for i, chunk in enumerate(chunks):
                chunk_dict = chunk.to_dict()
                chunk_dict['embedding'] = embeddings[i]
                chunks_with_embeddings.append(RAGChunk.from_dict(chunk_dict))
            
            # Ergebnis erstellen (nur in-memory, keine DB)
            result = RAGEmbeddingResult(
                document_id=document_id,
                chunks=chunks_with_embeddings,
                total_chunks=len(chunks_with_embeddings),
                embedding_dimensions=self.embedding_dimensions,
                embedding_model=effective_embedding_model,
                created_at=datetime.now().isoformat(),
                metadata=metadata or {}
            )
            
            duration = time.time() - start_time
            self.logger.info(
                "Embedding (client) abgeschlossen",
                extra={
                    "document_id": document_id,
                    "chunks": len(chunks_with_embeddings),
                    "duration_seconds": duration
                }
            )
            
            return result
        
        except Exception as e:
            self.logger.error("Fehler beim Embedding (client)", error=e)
            raise ProcessingError(f"Fehler beim Embedding (client): {str(e)}")
    

