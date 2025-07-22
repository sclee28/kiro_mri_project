"""
Unit tests for database utilities.

This module contains tests for database connection management,
session handling, and migration utilities.
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from shared.utils.database import (
    DatabaseConfig, DatabaseManager, db_manager,
    get_db_session, db_session_scope, create_all_tables,
    drop_all_tables, check_database_health
)
from shared.migrations.migration_manager import (
    MigrationManager, migration_manager, apply_all_migrations,
    get_migration_status, create_migration
)


class TestDatabaseConfig:
    """Test the DatabaseConfig class."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = DatabaseConfig()
        
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "healthcare_analysis"
        assert config.username == "postgres"
        assert config.password == ""
        assert config.ssl_mode == "prefer"
        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_timeout == 30
        assert config.pool_recycle == 3600
    
    def test_config_from_environment(self):
        """Test configuration from environment variables."""
        env_vars = {
            'DB_HOST': 'test-host',
            'DB_PORT': '5433',
            'DB_NAME': 'test_db',
            'DB_USERNAME': 'test_user',
            'DB_PASSWORD': 'test_pass',
            'DB_SSL_MODE': 'require',
            'DB_POOL_SIZE': '10',
            'DB_MAX_OVERFLOW': '20',
            'DB_POOL_TIMEOUT': '60',
            'DB_POOL_RECYCLE': '7200'
        }
        
        with patch.dict(os.environ, env_vars):
            config = DatabaseConfig()
            
            assert config.host == 'test-host'
            assert config.port == 5433
            assert config.database == 'test_db'
            assert config.username == 'test_user'
            assert config.password == 'test_pass'
            assert config.ssl_mode == 'require'
            assert config.pool_size == 10
            assert config.max_overflow == 20
            assert config.pool_timeout == 60
            assert config.pool_recycle == 7200
    
    def test_database_url_generation(self):
        """Test database URL generation."""
        config = DatabaseConfig()
        config.host = "localhost"
        config.port = 5432
        config.database = "test_db"
        config.username = "user"
        config.password = "pass"
        config.ssl_mode = "prefer"
        
        expected_url = "postgresql://user:pass@localhost:5432/test_db?sslmode=prefer"
        assert config.database_url == expected_url
    
    def test_database_url_with_special_characters(self):
        """Test database URL generation with special characters in password."""
        config = DatabaseConfig()
        config.host = "localhost"
        config.port = 5432
        config.database = "test_db"
        config.username = "user"
        config.password = "p@ss!w0rd#"
        config.ssl_mode = "prefer"
        
        # Password should be URL encoded
        expected_url = "postgresql://user:p%40ss%21w0rd%23@localhost:5432/test_db?sslmode=prefer"
        assert config.database_url == expected_url


class TestDatabaseManager:
    """Test the DatabaseManager class."""
    
    def test_singleton_pattern(self):
        """Test that DatabaseManager implements singleton pattern."""
        manager1 = DatabaseManager()
        manager2 = DatabaseManager()
        
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
    
    @patch('shared.utils.database.create_engine')
    @patch('shared.utils.database.sessionmaker')
    def test_engine_initialization(self, mock_sessionmaker, mock_create_engine):
        """Test database engine initialization."""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_session_factory = MagicMock()
        mock_sessionmaker.return_value = mock_session_factory
        
        # Create new manager instance
        manager = DatabaseManager()
        manager._engine = None  # Reset to trigger initialization
        manager._session_factory = None
        
        # Access engine property to trigger initialization
        engine = manager.engine
        
        assert mock_create_engine.called
        assert mock_sessionmaker.called
        assert engine == mock_engine
    
    @patch('shared.utils.database.Base')
    def test_create_tables(self, mock_base):
        """Test table creation."""
        mock_metadata = MagicMock()
        mock_base.metadata = mock_metadata
        
        with patch.object(db_manager, 'engine') as mock_engine:
            db_manager.create_tables()
            mock_metadata.create_all.assert_called_once_with(bind=mock_engine)
    
    @patch('shared.utils.database.Base')
    def test_drop_tables(self, mock_base):
        """Test table dropping."""
        mock_metadata = MagicMock()
        mock_base.metadata = mock_metadata
        
        with patch.object(db_manager, 'engine') as mock_engine:
            db_manager.drop_tables()
            mock_metadata.drop_all.assert_called_once_with(bind=mock_engine)
    
    def test_get_session(self):
        """Test session creation."""
        with patch.object(db_manager, 'session_factory') as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value = mock_session
            
            session = db_manager.get_session()
            
            mock_factory.assert_called_once()
            assert session == mock_session
    
    def test_session_scope_success(self):
        """Test successful session scope context manager."""
        mock_session = MagicMock()
        
        with patch.object(db_manager, 'get_session', return_value=mock_session):
            with db_manager.session_scope() as session:
                assert session == mock_session
                # Simulate some work
                session.add(MagicMock())
            
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()
            mock_session.rollback.assert_not_called()
    
    def test_session_scope_exception(self):
        """Test session scope context manager with exception."""
        mock_session = MagicMock()
        
        with patch.object(db_manager, 'get_session', return_value=mock_session):
            with pytest.raises(ValueError):
                with db_manager.session_scope() as session:
                    assert session == mock_session
                    raise ValueError("Test exception")
            
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()
            mock_session.commit.assert_not_called()
    
    def test_health_check_success(self):
        """Test successful database health check."""
        mock_session = MagicMock()
        
        with patch.object(db_manager, 'session_scope') as mock_scope:
            mock_scope.return_value.__enter__.return_value = mock_session
            mock_scope.return_value.__exit__.return_value = None
            
            result = db_manager.health_check()
            
            assert result is True
            mock_session.execute.assert_called_once_with("SELECT 1")
    
    def test_health_check_failure(self):
        """Test failed database health check."""
        with patch.object(db_manager, 'session_scope') as mock_scope:
            mock_scope.side_effect = Exception("Connection failed")
            
            result = db_manager.health_check()
            
            assert result is False


class TestConvenienceFunctions:
    """Test convenience functions for database operations."""
    
    def test_get_db_session(self):
        """Test get_db_session convenience function."""
        with patch.object(db_manager, 'get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            
            session = get_db_session()
            
            mock_get_session.assert_called_once()
            assert session == mock_session
    
    def test_db_session_scope(self):
        """Test db_session_scope convenience function."""
        mock_session = MagicMock()
        
        with patch.object(db_manager, 'session_scope') as mock_scope:
            mock_scope.return_value.__enter__.return_value = mock_session
            mock_scope.return_value.__exit__.return_value = None
            
            with db_session_scope() as session:
                assert session == mock_session
    
    def test_create_all_tables(self):
        """Test create_all_tables convenience function."""
        with patch.object(db_manager, 'create_tables') as mock_create:
            create_all_tables()
            mock_create.assert_called_once()
    
    def test_drop_all_tables(self):
        """Test drop_all_tables convenience function."""
        with patch.object(db_manager, 'drop_tables') as mock_drop:
            drop_all_tables()
            mock_drop.assert_called_once()
    
    def test_check_database_health(self):
        """Test check_database_health convenience function."""
        with patch.object(db_manager, 'health_check') as mock_health:
            mock_health.return_value = True
            
            result = check_database_health()
            
            mock_health.assert_called_once()
            assert result is True


class TestMigrationManager:
    """Test the MigrationManager class."""
    
    def test_migration_manager_singleton(self):
        """Test that migration_manager is accessible."""
        assert migration_manager is not None
        assert isinstance(migration_manager, MigrationManager)
    
    @patch('shared.migrations.migration_manager.db_session_scope')
    def test_ensure_migration_table(self, mock_session_scope):
        """Test migration table creation."""
        mock_session = MagicMock()
        mock_session_scope.return_value.__enter__.return_value = mock_session
        mock_session_scope.return_value.__exit__.return_value = None
        
        manager = MigrationManager()
        manager._ensure_migration_table()
        
        mock_session.execute.assert_called_once()
        # Check that the SQL contains CREATE TABLE IF NOT EXISTS
        call_args = mock_session.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS schema_migrations" in str(call_args)
    
    @patch('shared.migrations.migration_manager.db_session_scope')
    def test_get_applied_migrations(self, mock_session_scope):
        """Test getting applied migrations."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('20250121_120000',), ('20250122_130000',)]
        mock_session.execute.return_value = mock_result
        mock_session_scope.return_value.__enter__.return_value = mock_session
        mock_session_scope.return_value.__exit__.return_value = None
        
        manager = MigrationManager()
        applied = manager.get_applied_migrations()
        
        assert applied == ['20250121_120000', '20250122_130000']
    
    def test_create_migration(self):
        """Test creating a new migration file."""
        manager = MigrationManager()
        
        with patch('builtins.open', create=True) as mock_open:
            with patch('shared.migrations.migration_manager.datetime') as mock_datetime:
                mock_datetime.now.return_value.strftime.return_value = "20250121_120000"
                mock_datetime.now.return_value.isoformat.return_value = "2025-01-21T12:00:00"
                
                mock_file = MagicMock()
                mock_open.return_value.__enter__.return_value = mock_file
                
                version = manager.create_migration("test migration", "CREATE TABLE test;")
                
                assert version == "20250121_120000"
                mock_open.assert_called_once()
                mock_file.write.assert_called()
    
    @patch('shared.migrations.migration_manager.apply_all_migrations')
    def test_apply_all_migrations_convenience(self, mock_apply):
        """Test apply_all_migrations convenience function."""
        mock_apply.return_value = True
        
        result = apply_all_migrations()
        
        mock_apply.assert_called_once()
        assert result is True
    
    @patch('shared.migrations.migration_manager.migration_manager')
    def test_get_migration_status_convenience(self, mock_manager):
        """Test get_migration_status convenience function."""
        expected_status = {
            'applied_count': 2,
            'pending_count': 1,
            'applied_migrations': ['20250121_120000'],
            'pending_migrations': ['20250122_130000'],
            'last_applied': '20250121_120000'
        }
        mock_manager.get_migration_status.return_value = expected_status
        
        result = get_migration_status()
        
        mock_manager.get_migration_status.assert_called_once()
        assert result == expected_status
    
    @patch('shared.migrations.migration_manager.migration_manager')
    def test_create_migration_convenience(self, mock_manager):
        """Test create_migration convenience function."""
        mock_manager.create_migration.return_value = "20250121_120000"
        
        version = create_migration("test", "CREATE TABLE test;")
        
        mock_manager.create_migration.assert_called_once_with("test", "CREATE TABLE test;")
        assert version == "20250121_120000"


# Integration tests for migration functionality
@pytest.mark.integration
class TestMigrationIntegration:
    """Integration tests for migration functionality."""
    
    @pytest.fixture(autouse=True)
    def setup_test_env(self):
        """Set up test environment."""
        with patch.dict('os.environ', {
            'DB_NAME': 'test_healthcare_analysis',
            'DB_HOST': 'localhost',
            'DB_USERNAME': 'test_user',
            'DB_PASSWORD': 'test_password'
        }):
            yield
    
    def test_migration_workflow(self):
        """Test complete migration workflow."""
        # This would require a real database connection
        # For now, we'll mock the key components
        
        with patch('shared.migrations.migration_manager.db_session_scope') as mock_scope:
            mock_session = MagicMock()
            mock_scope.return_value.__enter__.return_value = mock_session
            mock_scope.return_value.__exit__.return_value = None
            
            manager = MigrationManager()
            
            # Test ensuring migration table
            manager._ensure_migration_table()
            assert mock_session.execute.called
            
            # Test getting applied migrations
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            mock_session.execute.return_value = mock_result
            
            applied = manager.get_applied_migrations()
            assert applied == []