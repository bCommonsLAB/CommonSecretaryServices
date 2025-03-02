@bp.route('/api/dashboard/event-monitor/batches/<batch_id>', methods=['DELETE'])
def delete_batch(batch_id):
    """
    Löscht einen Batch über die API.
    """
    logger.info(f"Lösche Batch: {batch_id}")
    
    if not batch_id:
        return jsonify({"status": "error", "message": "Batch ID ist erforderlich"}), 400

    # Überprüfen, ob die API-Basis-URL konfiguriert ist
    api_base_url = current_app.config.get('API_BASE_URL')
    if not api_base_url:
        logger.error("API_BASE_URL ist nicht konfiguriert")
        return jsonify({"status": "error", "message": "API-Konfiguration fehlt"}), 500
    
    # API-Anfrage zum Löschen des Batches
    try:
        response = requests.delete(
            f"{api_base_url}/api/event-job/batch/{batch_id}",
            headers={"Authorization": f"Bearer {get_api_token()}"}
        )
        
        # Antwort überprüfen
        if response.status_code == 404:
            logger.warning(f"Batch nicht gefunden: {batch_id}")
            return jsonify({"status": "error", "message": "Batch nicht gefunden"}), 404
        
        if not response.ok:
            logger.error(f"API-Fehler beim Löschen des Batches {batch_id}: {response.status_code}, {response.text}")
            return jsonify({
                "status": "error", 
                "message": f"Fehler beim Löschen des Batches: {response.status_code}",
                "details": response.text
            }), response.status_code
        
        # Erfolgreiche Antwort zurückgeben
        result = response.json()
        logger.info(f"Batch {batch_id} erfolgreich gelöscht")
        return jsonify({
            "status": "success",
            "message": "Batch erfolgreich gelöscht",
            "data": result
        })
    
    except requests.RequestException as e:
        logger.error(f"Netzwerkfehler beim Löschen des Batches {batch_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Verbindungsfehler: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Löschen des Batches {batch_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Interner Serverfehler: {str(e)}"
        }), 500 