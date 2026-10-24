"""Explicit setup and bounded HTTP server; never auto-migrate at startup."""
import argparse
import os
from uuid import UUID

from platform_backend_core import Database, MigrationRunner, TokenVerifier

from .app import create_app
from .migrations import MIGRATIONS


def main():
    parser = argparse.ArgumentParser(description='Workspace data service')
    parser.add_argument('command', choices=('serve', 'migrate'))
    args = parser.parse_args()
    dsn = os.environ.get('DATABASE_URL')
    if not dsn:
        parser.error('DATABASE_URL is required')
    try:
        if args.command == 'migrate':
            count = len(MigrationRunner(dsn, namespace='data').apply(MIGRATIONS))
            print(f'applied {count} data migrations')
            return
        issuer = os.environ.get('JWT_ISSUER')
        audience = os.environ.get('JWT_AUDIENCE')
        if not issuer or not audience:
            raise ValueError('missing JWT configuration')
        verifier = TokenVerifier(issuer=issuer, audience=audience,
                                 public_key=os.environ.get('JWT_PUBLIC_KEY'),
                                 jwks_url=os.environ.get('JWT_JWKS_URL'))
        port = int(os.environ.get('PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError('invalid port')
        import uvicorn
        system = os.environ.get('PLATFORM_SYSTEM_WORKSPACE_ID')
        app = create_app(Database(dsn), verifier, system_workspace=UUID(system) if system else None)
    except Exception:
        parser.exit(1, 'data configuration or migration failed; inspect trusted configuration and database history\n')
    uvicorn.run(app, host='0.0.0.0', port=port, access_log=False,
                limit_concurrency=64, timeout_keep_alive=5, timeout_graceful_shutdown=30)


if __name__ == '__main__':
    main()
