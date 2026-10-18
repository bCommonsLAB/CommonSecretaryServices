"""
@fileoverview Dashboard Utilities - Helper functions for dashboard application

@description
Utility functions for the dashboard application. This module provides helper
functions used across different dashboard routes, including system information
retrieval and common utilities.

Main functionality:
- System information retrieval (version, OS, CPU, memory, disk)
- Platform information gathering
- System resource monitoring

Features:
- System version detection
- Platform information (OS, Python version)
- Resource usage monitoring (CPU, memory, disk)
- Cross-platform support

@module dashboard.utils

@exports
- get_system_info(): Dict[str, Any] - Get system information dictionary

@usedIn
- src.dashboard.routes.main_routes: Uses get_system_info for dashboard display

@dependencies
- External: psutil - System and process utilities
- Standard: platform - Platform identification
- Standard: sys - System-specific parameters
"""
import psutil
import platform
import sys
import os
from typing import Dict

def get_system_info():
    """
    Get system information for the dashboard
    
    Returns:
        dict: A dictionary containing system information including:
            - version: Application version
            - python_version: Python version being used
            - os: Operating system information
            - cpu_usage: Current CPU usage percentage
            - memory_usage: Current memory usage percentage
            - disk_usage: Current disk usage percentage
    """
    return {
        'version': '1.0.0',  # Replace with actual version
        'python_version': sys.version.split()[0],
        'os': platform.platform(),
        'cpu_usage': psutil.cpu_percent(),
        'memory_usage': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage('/').percent
    } 

def service_auth_headers() -> Dict[str, str]:
    """
    Header fuer Aufrufe des Dashboards an die eigene API (AP-01/AP-02).

    Die API verlangt den Service-Token; die Dashboard-Testrouten senden ihn deshalb mit,
    statt sich auf eine Auth-Ausnahme zu verlassen.
    """
    token = (os.environ.get("SECRETARY_SERVICE_API_KEY") or "").strip()
    return {"X-Secretary-Api-Key": token} if token else {}
