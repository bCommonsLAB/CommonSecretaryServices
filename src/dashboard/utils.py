"""
Utility functions for the dashboard application.
Contains helper functions used across different routes.
"""
import psutil
import platform
import sys

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