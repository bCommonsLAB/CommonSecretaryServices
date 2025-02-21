#!/bin/bash

# Fail if any command fails
set -e

# Get the directory name this script is in
dirName=$(dirname "$0")

# Get the current version
current_version=$(bash $dirName/currentVersion.sh)

# Split the version into an array
IFS='.' read -ra version_parts <<< "$current_version"

# Get the major and minor version numbers
major=${version_parts[0]}
minor=${version_parts[1]}

# Construct the new branch name
new_branch="release/$major.$minor.x"

# Output the new branch name
echo $new_branch