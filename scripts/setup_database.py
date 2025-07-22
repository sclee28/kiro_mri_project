#!/usr/bin/env python3
"""
Database setup script for the healthcare image analysis system.

This script handles initial database setup, migration application,
and database health checks for RDS deployment.
"""

import sys
import os
import logging
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from shared.utils.database import (
    db_manager, create_all_tables, check_database_health
)
from shared.migrations.migration_manager import apply_all_migrations, get_migration_status

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_database():
    """
    Set up the database with tables and initial data.
    
    This function:
    1. Checks database connectivity
    2. Applies any pending migrations
    3. Creates tables if they don't exist
    4. Verifies the setup
    """
    logger.info("Starting database setup...")
    
    try:
        # Check database connectivity
        logger.info("Checking database connectivity...")
        if not check_database_health():
            logger.error("Database health check failed")
            return False
        logger.info("Database connectivity verified")
        
        # Apply migrations
        logger.info("Applying database migrations...")
        if not apply_all_migrations():
            logger.error("Failed to apply migrations")
            return False
        
        # Get migration status
        status = get_migration_status()
        logger.info(f"Migration status: {status['applied_count']} applied, {status['pending_count']} pending")
        
        # Create tables using SQLAlchemy (fallback if migrations didn't work)
        logger.info("Ensuring all tables exist...")
        create_all_tables()
        
        # Final health check
        logger.info("Performing final health check...")
        if not check_database_health():
            logger.error("Final health check failed")
            return False
        
        logger.info("Database setup completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Database setup failed: {e}")
        return False


def check_setup():
    """Check if the database is properly set up."""
    logger.info("Checking database setup...")
    
    try:
        # Health check
        if not check_database_health():
            logger.error("Database is not accessible")
            return False
        
        # Check migration status
        status = get_migration_status()
        logger.info(f"Applied migrations: {status['applied_count']}")
        logger.info(f"Pending migrations: {status['pending_count']}")
        
        if status['pending_count'] > 0:
            logger.warning(f"There are {status['pending_count']} pending migrations")
            return False
        
        logger.info("Database setup is valid")
        return True
        
    except Exception as e:
        logger.error(f"Setup check failed: {e}")
        return False


def reset_database():
    """
    Reset the database by dropping and recreating all tables.
    
    WARNING: This will delete all data!
    """
    logger.warning("Resetting database - this will delete all data!")
    
    try:
        # Drop all tables
        logger.info("Dropping all tables...")
        db_manager.drop_tables()
        
        # Recreate tables
        logger.info("Recreating tables...")
        create_all_tables()
        
        # Apply migrations
        logger.info("Applying migrations...")
        apply_all_migrations()
        
        logger.info("Database reset completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Database reset failed: {e}")
        return False


def main():
    """Main entry point for the database setup script."""
    if len(sys.argv) < 2:
        print("Usage: python setup_database.py <command>")
        print("Commands:")
        print("  setup   - Set up the database with tables and migrations")
        print("  check   - Check if the database is properly set up")
        print("  reset   - Reset the database (WARNING: deletes all data)")
        print("  status  - Show migration status")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "setup":
        success = setup_database()
        sys.exit(0 if success else 1)
    
    elif command == "check":
        success = check_setup()
        sys.exit(0 if success else 1)
    
    elif command == "reset":
        # Require confirmation for reset
        if len(sys.argv) < 3 or sys.argv[2] != "--confirm":
            print("WARNING: This will delete all data!")
            print("Use: python setup_database.py reset --confirm")
            sys.exit(1)
        
        success = reset_database()
        sys.exit(0 if success else 1)
    
    elif command == "status":
        try:
            status = get_migration_status()
            print(f"Applied migrations: {status['applied_count']}")
            print(f"Pending migrations: {status['pending_count']}")
            
            if status['applied_migrations']:
                print("\nApplied migrations:")
                for migration in status['applied_migrations']:
                    print(f"  - {migration}")
            
            if status['pending_migrations']:
                print("\nPending migrations:")
                for migration in status['pending_migrations']:
                    print(f"  - {migration}")
            
            sys.exit(0)
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()