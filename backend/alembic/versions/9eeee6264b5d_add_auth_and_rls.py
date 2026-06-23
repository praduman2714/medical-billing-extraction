"""add_auth_and_rls

Revision ID: 9eeee6264b5d
Revises: 0de1443cd0f2
Create Date: 2026-06-23 15:56:32.622566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9eeee6264b5d'
down_revision: Union[str, Sequence[str], None] = '0de1443cd0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create Better Auth tables
    op.create_table(
        'user',
        sa.Column('id', sa.String(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False, unique=True),
        sa.Column('emailVerified', sa.Boolean(), nullable=False),
        sa.Column('image', sa.String(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=False),
    )
    
    op.create_table(
        'session',
        sa.Column('id', sa.String(), nullable=False, primary_key=True),
        sa.Column('expiresAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('token', sa.String(), nullable=False, unique=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ipAddress', sa.String(), nullable=True),
        sa.Column('userAgent', sa.String(), nullable=True),
        sa.Column('userId', sa.String(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
    )
    
    op.create_table(
        'account',
        sa.Column('id', sa.String(), nullable=False, primary_key=True),
        sa.Column('accountId', sa.String(), nullable=False),
        sa.Column('providerId', sa.String(), nullable=False),
        sa.Column('userId', sa.String(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('accessToken', sa.String(), nullable=True),
        sa.Column('refreshToken', sa.String(), nullable=True),
        sa.Column('idToken', sa.String(), nullable=True),
        sa.Column('accessTokenExpiresAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refreshTokenExpiresAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scope', sa.String(), nullable=True),
        sa.Column('password', sa.String(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=False),
    )
    
    op.create_table(
        'verification',
        sa.Column('id', sa.String(), nullable=False, primary_key=True),
        sa.Column('identifier', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('expiresAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updatedAt', sa.DateTime(timezone=True), nullable=True),
    )

    # Alter jobs table to add user_id, cache, and metrics columns
    op.add_column('jobs', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('token_usage', sa.JSON(), nullable=True))
    op.add_column('jobs', sa.Column('cost_usd', sa.Float(), nullable=True))
    op.add_column('jobs', sa.Column('processing_duration_seconds', sa.Float(), nullable=True))
    op.add_column('jobs', sa.Column('pdf_hash', sa.String(), nullable=True))
    
    # Add foreign key constraint
    op.create_foreign_key('fk_jobs_user', 'jobs', 'user', ['user_id'], ['id'], ondelete='CASCADE')
    
    # Add index for fast caching lookup
    op.create_index('idx_jobs_user_pdf_hash', 'jobs', ['user_id', 'pdf_hash'])

    # Setup roles and RLS
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'billing_app') THEN
            CREATE ROLE billing_app WITH LOGIN PASSWORD 'billing_app';
        ELSE
            ALTER ROLE billing_app WITH LOGIN PASSWORD 'billing_app';
        END IF;
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'billing_worker') THEN
            CREATE ROLE billing_worker WITH LOGIN PASSWORD 'billing_worker';
        ELSE
            ALTER ROLE billing_worker WITH LOGIN PASSWORD 'billing_worker';
        END IF;
    END
    $$;
    """)

    # Grant permissions to roles on current and future tables
    op.execute("GRANT USAGE ON SCHEMA public TO billing_app;")
    op.execute("GRANT USAGE ON SCHEMA public TO billing_worker;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO billing_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO billing_worker;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO billing_app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO billing_worker;")

    # Enable RLS
    op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;")
    
    # Drop existing policies if they somehow exist, and create them
    op.execute("DROP POLICY IF EXISTS job_app_policy ON jobs;")
    op.execute("DROP POLICY IF EXISTS job_worker_policy ON jobs;")
    
    # Policy for web API (can only view/modify their own jobs)
    op.execute("""
    CREATE POLICY job_app_policy ON jobs
        FOR ALL
        TO billing_app
        USING (user_id = current_setting('app.current_user_id', true))
        WITH CHECK (user_id = current_setting('app.current_user_id', true));
    """)
    
    # Policy for worker (can select/update pending/processing jobs, or any jobs where current_user_id matches)
    op.execute("""
    CREATE POLICY job_worker_policy ON jobs
        FOR ALL
        TO billing_worker
        USING (status = 'pending' OR status = 'processing' OR user_id = current_setting('app.current_user_id', true))
        WITH CHECK (status = 'pending' OR status = 'processing' OR user_id = current_setting('app.current_user_id', true));
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Disable RLS and drop policies
    op.execute("ALTER TABLE jobs DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS job_app_policy ON jobs;")
    op.execute("DROP POLICY IF EXISTS job_worker_policy ON jobs;")
    
    # Drop index
    op.drop_index('idx_jobs_user_pdf_hash', 'jobs')
    
    # Drop foreign key constraint
    op.drop_constraint('fk_jobs_user', 'jobs', type_='foreignkey')
    
    # Remove columns from jobs
    op.drop_column('jobs', 'pdf_hash')
    op.drop_column('jobs', 'processing_duration_seconds')
    op.drop_column('jobs', 'cost_usd')
    op.drop_column('jobs', 'token_usage')
    op.drop_column('jobs', 'user_id')
    
    # Drop tables
    op.drop_table('verification')
    op.drop_table('account')
    op.drop_table('session')
    op.drop_table('user')

