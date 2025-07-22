"""
Database connection utilities and session management.

This module provides utilities for connecting to the PostgreSQL database,
managing sessions, and handling database operations.
"""

import os
import logging
from contextlib import contextmanager
from typing import Generator, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import SQLAlchemyError

from ..models.database import Base

# Configure logging
logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Configuration class for database connection parameters."""
    
    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = int(os.getenv("DB_PORT", "5432"))
        self.database = os.getenv("DB_NAME", "healthcare_analysis")
        self.username = os.getenv("DB_USERNAME", "postgres")
        self.password = os.getenv("DB_PASSWORD", "")
        self.ssl_mode = os.getenv("DB_SSL_MODE", "prefer")
        
        # Connection pool settings
        self.pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        self.max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        self.pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        self.pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    
    @property
    def database_url(self) -> str:
        """Generate the database URL from configuration parameters."""
        # URL encode the password to handle special characters
        encoded_password = quote_plus(self.password)
        
        return (
            f"postgresql://{self.username}:{encoded_password}@"
            f"{self.host}:{self.port}/{self.database}?sslmode={self.ssl_mode}"
        )


class DatabaseManager:
    """
    Database manager class for handling connections and sessions.
    
    This class implements the singleton pattern to ensure only one
    database engine instance is created per application.
    """
    
    _instance: Optional['DatabaseManager'] = None
    _engine: Optional[Engine] = None
    _session_factory: Optional[sessionmaker] = None
    
    def __new__(cls) -> 'DatabaseManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._engine is None:
            self._initialize_engine()
    
    def _initialize_engine(self) -> None:
        """Initialize the database engine with connection pooling."""
        config = DatabaseConfig()
        
        try:
            self._engine = create_engine(
                config.database_url,
                poolclass=QueuePool,
                pool_size=config.pool_size,
                max_overflow=config.max_overflow,
                pool_timeout=config.pool_timeout,
                pool_recycle=config.pool_recycle,
                pool_pre_ping=True,  # Validate connections before use
                echo=os.getenv("DB_ECHO", "false").lower() == "true"
            )
            
            self._session_factory = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False
            )
            
            logger.info("Database engine initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database engine: {e}")
            raise
    
    @property
    def engine(self) -> Engine:
        """Get the database engine instance."""
        if self._engine is None:
            self._initialize_engine()
        return self._engine
    
    @property
    def session_factory(self) -> sessionmaker:
        """Get the session factory."""
        if self._session_factory is None:
            self._initialize_engine()
        return self._session_factory
    
    def create_tables(self) -> None:
        """Create all database tables."""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except SQLAlchemyError as e:
            logger.error(f"Failed to create database tables: {e}")
            raise
    
    def drop_tables(self) -> None:
        """Drop all database tables. Use with caution!"""
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.info("Database tables dropped successfully")
        except SQLAlchemyError as e:
            logger.error(f"Failed to drop database tables: {e}")
            raise
    
    def get_session(self) -> Session:
        """Create a new database session."""
        return self.session_factory()
    
    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope around a series of operations.
        
        This context manager automatically handles session creation,
        transaction management, and cleanup.
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database transaction failed: {e}")
            raise
        finally:
            session.close()
    
    def health_check(self) -> bool:
        """
        Perform a health check on the database connection.
        
        Returns:
            bool: True if the database is accessible, False otherwise.
        """
        try:
            with self.session_scope() as session:
                session.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# Global database manager instance
db_manager = DatabaseManager()


# Convenience functions for common operations
def get_db_session() -> Session:
    """Get a new database session."""
    return db_manager.get_session()


@contextmanager
def db_session_scope() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic transaction handling."""
    with db_manager.session_scope() as session:
        yield session


def create_all_tables() -> None:
    """Create all database tables."""
    db_manager.create_tables()


def drop_all_tables() -> None:
    """Drop all database tables. Use with caution!"""
    db_manager.drop_tables()


def check_database_health() -> bool:
    """Check if the database is accessible."""
    return db_manager.health_check()