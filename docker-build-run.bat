@echo off
echo Starting Docker build and run process...

REM Stop and remove existing container if it exists
echo Stopping and removing existing container...
docker rm -f secretary-services 2>nul

REM Build the Docker image
echo Building Docker image...
docker build -t secretary-services .

REM Copy .env.example to temporary .env file for Docker
echo Preparing environment file...
copy .env.example .env.docker

REM Update Docker configuration
echo Updating Docker configuration...
REM powershell -Command "(Get-Content docker\config\config.yaml) -replace 'port: 5000', 'port: 5001' -replace 'api_port: 5000', 'api_port: 5001' | Set-Content docker\config\config.yaml"

REM Run the container
echo Starting container...
docker run -d ^
    -p 5001:5001 ^
    --name secretary-services ^
    --env-file .env.docker ^
    -v "%CD%/logs:/app/logs" ^
    -v "%CD%/temp-processing:/app/temp-processing" ^
    -v "%CD%/config/config.yaml:/app/config/config.yaml" ^
    secretary-services

REM Clean up temporary files
del .env.docker

REM Check container status
echo Checking container status...
docker ps | findstr secretary-services
echo.
echo Checking container logs...
timeout /t 2 > nul
docker logs secretary-services

echo.
echo Process completed. Container is running on port 5001.
echo You can access the application at http://localhost:5001
pause 