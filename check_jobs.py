from src.core.mongodb import get_job_repository

def check_jobs():
    # Repository holen
    repo = get_job_repository()
    
    # Alle Batches abrufen
    batches = list(repo.get_batches())
    
    print(f"Gefundene Batches: {len(batches)}")
    
    # Details für jeden Batch ausgeben
    for batch in batches:
        print(f"\nBatch ID: {batch.batch_id}")
        print(f"Status: {batch.status}")
        print(f"Erstellt am: {batch.created_at}")
        
        # Jobs für diesen Batch abrufen
        jobs = repo.get_jobs_for_batch(batch.batch_id)
        print(f"Jobs für diesen Batch: {len(jobs)}")
        
        # Details für jeden Job ausgeben
        for job in jobs:
            print(f"  - Job ID: {job.job_id}, Status: {job.status}")

if __name__ == "__main__":
    check_jobs() 