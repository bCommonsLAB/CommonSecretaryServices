#!/bin/bash

# Get the directory name this script is in
dirName=$(dirname "$0")

# Path to the AssemblyInfos.cs file
file_path="$dirName/../../VERSION"

version=$(cat "$file_path")
echo $version; exit