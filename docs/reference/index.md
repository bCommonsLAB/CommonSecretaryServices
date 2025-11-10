# Reference Manual

Complete reference documentation for Common Secretary Services. This section provides comprehensive documentation for developers and administrators.

## Overview

The reference manual is organized into the following sections:

- **Code Reference**: Complete index of all documented Python files and module hierarchy
- **API Reference**: Complete API documentation with examples
- **Data Models**: Documentation of all dataclasses and Pydantic models
- **Configuration**: Complete configuration reference
- **Environment Variables**: All environment variables documented

## Code Reference

### [Code Index](code-index.md)

Automatically generated index of all documented Python files. Provides an overview of:
- All documented modules with descriptions
- Exported classes and functions
- Module dependencies
- Usage contexts

**Total**: 105+ documented files

### [Module Hierarchy](architecture/module-hierarchy.md)

Architectural overview showing:
- Module structure and organization
- Dependency relationships
- Data flow between modules
- Entry points and initialization

## API Reference

### [API Overview](api/overview.md)

Complete overview of all available API endpoints organized by processor type.

### [OpenAPI / Swagger](api/openapi.md)

Interactive API documentation via Swagger UI. Access at `/api/doc` when the server is running.

## Data Models

### [Data Models Index](data-models/index.md)

Complete documentation of all dataclasses and Pydantic models used throughout the application.

## Configuration

### [Configuration Reference](configuration.md)

Complete documentation of all `config.yaml` options including:
- Cache configuration
- Worker settings
- Processor-specific settings
- Logging configuration
- MongoDB settings

### [Environment Variables](environment-variables.md)

Documentation of all environment variables required for the application.

## Quick Links

- [Code Index](code-index.md) - Browse all documented files
- [Module Hierarchy](architecture/module-hierarchy.md) - Understand the architecture
- [API Overview](api/overview.md) - Explore API endpoints
- [Configuration](configuration.md) - Configure the application
- [Environment Variables](environment-variables.md) - Set up environment

## Related Documentation

- [Architecture Overview](../explanations/architecture/overview.md) - High-level architecture
- [Processor Documentation](../processors/) - Individual processor guides
- [Development Guidelines](../guide/getting-started/) - Coding standards

