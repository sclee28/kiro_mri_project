"""
Database migration management utilities.

This module provides utilities for managing database schema migrations,
including creating, applying, and rolling back migrations.
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from sqlalchemy import text, MetaData, Table, Column, String, DateTime, Integer
from sqlalchemy.exc import SQLAlchemyError

from ..utils.database import db_manager, db_session_scope

logger = logging.getLogger(__name__)


class MigrationManager:
    """
    Manages database schema migrations.
    
    This class handles the creation, application, and tracking of
    database schema changes.
    """
    
    def __init__(self):
        self.migrations_dir = Path(__file__).parent / "scripts"
        self.migrations_dir.mkdir(exist_ok=True)
        
    def _ensure_migration_table(self) -> None:
        """Ensure the migration tracking table exists."""
        try:
            with db_session_scope() as session:
                # Create migration tracking table if it doesn't exist
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        id SERIAL PRIMARY KEY,
                        version VARCHAR(255) NOT NULL UNIQUE,
                        applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        description TEXT
                    )
                """))
                logger.info("Migration tracking table ensured")
        except SQLAlchemyError as e:
            logger.error(f"Failed to create migration tracking table: {e}")
            raise
    
    def get_applied_migrations(self) -> List[str]:
        """Get list of applied migration versions."""
        self._ensure_migration_table()
        
        try:
            with db_session_scope() as session:
                result = session.execute(text(
                    "SELECT version FROM schema_migrations ORDER BY applied_at"
                ))
                return [row[0] for row in result.fetchall()]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get applied migrations: {e}")
            return []
    
    def get_pending_migrations(self) -> List[Dict[str, Any]]:
        """Get list of pending migrations that need to be applied."""
        applied = set(self.get_applied_migrations())
        all_migrations = self._get_all_migrations()
        
        pending = []
        for migration in all_migrations:
            if migration['version'] not in applied:
                pending.append(migration)
        
        return sorted(pending, key=lambda x: x['version'])
    
    def _get_all_migrations(self) -> List[Dict[str, Any]]:
        """Get all available migration files."""
        migrations = []
        
        if not self.migrations_dir.exists():
            return migrations
        
        for file_path in self.migrations_dir.glob("*.sql"):
            # Extract version from filename (format: YYYYMMDD_HHMMSS_description.sql)
            filename = file_path.stem
            parts = filename.split('_', 2)
            
            if len(parts) >= 2:
                version = f"{parts[0]}_{parts[1]}"
                description = parts[2] if len(parts) > 2 else "No description"
                
                migrations.append({
                    'version': version,
                    'description': description.replace('_', ' '),
                    'file_path': file_path
                })
        
        return migrations
    
    def apply_migration(self, migration: Dict[str, Any]) -> bool:
        """Apply a single migration."""
        try:
            with open(migration['file_path'], 'r') as f:
                sql_content = f.read()
            
            with db_session_scope() as session:
                # Execute the migration SQL
                for statement in sql_content.split(';'):
                    statement = statement.strip()
                    if statement:
                        session.execute(text(statement))
                
                # Record the migration as applied
                session.execute(text("""
                    INSERT INTO schema_migrations (version, description)
                    VALUES (:version, :description)
                """), {
                    'version': migration['version'],
                    'description': migration['description']
                })
            
            logger.info(f"Applied migration {migration['version']}: {migration['description']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply migration {migration['version']}: {e}")
            return False
    
    def apply_all_pending(self) -> bool:
        """Apply all pending migrations."""
        pending = self.get_pending_migrations()
        
        if not pending:
            logger.info("No pending migrations to apply")
            return True
        
        logger.info(f"Applying {len(pending)} pending migrations")
        
        for migration in pending:
            if not self.apply_migration(migration):
                logger.error(f"Migration failed at {migration['version']}")
                return False
        
        logger.info("All pending migrations applied successfully")
        return True
    
    def create_migration(self, description: str, sql_content: str) -> str:
        """Create a new migration file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_description = description.lower().replace(' ', '_').replace('-', '_')
        version = f"{timestamp}"
        filename = f"{version}_{clean_description}.sql"
        
        file_path = self.migrations_dir / filename
        
        with open(file_path, 'w') as f:
            f.write(f"-- Migration: {description}\n")
            f.write(f"-- Created: {datetime.now().isoformat()}\n\n")
            f.write(sql_content)
        
        logger.info(f"Created migration file: {filename}")
        return version
    
    def get_migration_status(self) -> Dict[str, Any]:
        """Get the current migration status."""
        applied = self.get_applied_migrations()
        pending = self.get_pending_migrations()
        
        return {
            'applied_count': len(applied),
            'pending_count': len(pending),
            'applied_migrations': applied,
            'pending_migrations': [m['version'] for m in pending],
            'last_applied': applied[-1] if applied else None
        }


# Global migration manager instance
migration_manager = MigrationManager()


# Convenience functions
def apply_all_migrations() -> bool:
    """Apply all pending database migrations."""
    return migration_manager.apply_all_pending()


def get_migration_status() -> Dict[str, Any]:
    """Get the current migration status."""
    return migration_manager.get_migration_status()


def create_migration(description: str, sql_content: str) -> str:
    """Create a new migration file."""
    return migration_manager.create_migration(description, sql_content)