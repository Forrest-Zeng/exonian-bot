# Overview

The Exonian Article Workflow Bot is a Discord bot designed to manage article writing workflows for The Exonian publication. The bot provides a structured system for creating, managing, and archiving article discussions through Discord channels. It automates the workflow from article creation to publication by organizing channels into categories, managing deadlines, and providing role-based permissions for editors and writers.

## Current Status
✅ **Ready to Use**: The bot is fully configured and running in Replit. The Discord bot token has been securely set up via environment variables and the bot is successfully connected to Discord's Gateway.

## Recent Changes (Sept 16, 2025)
- Migrated from hardcoded token to environment variable (`DISCORD_BOT_TOKEN`)
- Added `requirements.txt` with discord.py>=2.0.0 dependency
- Configured Replit workflow to run the bot automatically
- Successfully tested connection to Discord Gateway

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Bot Framework
The system is built using the discord.py library (v2.0+) with slash commands for user interaction. The bot follows an event-driven architecture where users trigger commands that manipulate Discord server structure and permissions.

## Data Management
The bot uses a simple file-based configuration system with JSON storage. Configuration data is managed through a `BotConfig` dataclass that handles:
- Guild (server) identification
- Category naming conventions
- Role management settings
- Persistent storage to `exonian_config.json`

## Channel Organization
The architecture implements a two-tier categorization system:
- **Active Articles Category**: Houses ongoing article discussions
- **Archived Articles Category**: Stores completed or past-deadline articles

This separation provides clear workflow states and helps manage channel visibility.

## Permission Model
The bot implements role-based access control using Discord's native permission system:
- **Editors Role**: Full access to all channels and administrative functions
- **General Users**: Limited access based on channel-specific permissions
- **Archive State**: Read-only access for non-editors

## Command Structure
The bot exposes functionality through Discord slash commands:
- Administrative commands for setup and synchronization
- Article lifecycle management (creation, archiving)
- Utility commands for listing and monitoring

## Automation Layer
An auto-sweeper task runs on a 5-minute interval to automatically archive articles past their deadlines, providing a safety net for workflow management.

# External Dependencies

## Discord Platform
- **discord.py library**: Primary framework for Discord API interaction
- **Discord Developer Portal**: Bot registration and token management
- **Discord Permissions API**: Role and channel permission management

## Runtime Environment
- **Python 3.x**: Core runtime environment
- **Environment Variables**: Bot token storage via `DISCORD_BOT_TOKEN`
- **Local File System**: JSON configuration persistence

## Development Tools
- **Replit Environment**: Deployment and hosting platform
- **pip**: Package management for Python dependencies