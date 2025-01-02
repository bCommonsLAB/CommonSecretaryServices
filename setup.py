from setuptools import setup, find_packages

setup(
    name="common-secretary-services",
    version="0.1",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        # Ihre Abhängigkeiten aus requirements.txt
        "pydub",
        "flask",
        "flask-restx",
        "requests",
        # ... weitere Abhängigkeiten
    ],
) 