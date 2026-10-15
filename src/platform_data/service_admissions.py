"""Actor-bound composite quota admission with durable, replayable leg operations.

Each short transaction uses core's verified workspace binding. No transaction
switches tenants. Committed intent plus immutable leg keys makes interruptions
conservative and recoverable without holding a pooled connection across legs.
"""
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import Field
from platform_backend_core import AuthenticationError, Principal, require_scope

from .app import Body, Reservation, Settlement, one


class ServiceReservation(Reservation):
    global_policy: str = Field(min_length=1, max_length=200, pattern=r'^[^\x00]+$')


def register_service_admissions(app, database, verifier, reserve_leg, finish_leg,
                                system_workspace):
    def pair(request: Request,
             service: Principal = Depends(require_scope('quotas:service'))):
        if system_workspace is None:
            raise HTTPException(503, 'Service admission is not configured')
        if service.workspace != system_workspace:
            raise HTTPException(403, 'Service workspace is not authorized')
        try:
            caller = verifier.verify(request.headers.get('x-workspace-authorization'))
        except AuthenticationError:
            raise HTTPException(401, 'Caller authorization required') from None
        if 'ai:generate' not in caller.scopes:
            raise HTTPException(403, 'Caller scope is not authorized')
        return service, caller

    def authorize(row, service, caller):
        if row is None:
            raise HTTPException(404, 'Admission not found')
        if (row['service_workspace'], row['service_actor'], row['caller_actor']) != (
                service.workspace, service.actor, caller.actor):
            raise HTTPException(403, 'Admission actor is not authorized')

    def response(row):
        return dict(id=str(row['id']), status=row['status'], units=row['units'],
                    expires_at=row['expires_at'], available=row['available_units'])

    def read(conn, id, lock=False):
        return one(conn, 'SELECT *, expires_at<=clock_timestamp() AS expired '
                   'FROM data_service_admissions WHERE id=%s' +
                   (' FOR UPDATE' if lock else ''), (id,))

    @app.post('/v1/service/admissions')
    def reserve(body: ServiceReservation, principals=Depends(pair)):
        service, caller = principals
        with database.transaction(caller.workspace) as conn:
            conn.execute('''INSERT INTO data_service_admissions
            (workspace_id,id,service_workspace,service_actor,caller_actor,
             policy,global_policy,units,ttl_seconds,idempotency_key)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(workspace_id,idempotency_key) DO NOTHING''',
                         (caller.workspace, uuid4(), service.workspace, service.actor,
                          caller.actor, body.policy, body.global_policy, body.units,
                          body.ttl_seconds, body.idempotency_key))
            row = one(conn, 'SELECT * FROM data_service_admissions '
                      'WHERE idempotency_key=%s', (body.idempotency_key,))
            authorize(row, service, caller)
            if (row['policy'], row['global_policy'], row['units'], row['ttl_seconds']) != (
                    body.policy, body.global_policy, body.units, body.ttl_seconds):
                raise HTTPException(409, 'Idempotency payload differs')
            if row['operation'] is not None:
                raise HTTPException(409, 'Admission is already being finalized')
            mapping_id = row['id']

        # The durable mapping commits before either leg. Any interruption is
        # recovered using the same UUID-derived keys; no ambiguous leg is freed.
        global_leg = reserve_leg(Reservation(
            policy=body.global_policy, units=body.units,
            idempotency_key='service:global:' + str(mapping_id),
            ttl_seconds=body.ttl_seconds), service)
        if global_leg['status'] != 'pending':
            raise HTTPException(409, 'Global reservation is no longer pending')
        with database.transaction(caller.workspace) as conn:
            conn.execute('UPDATE data_service_admissions SET global_reservation_id=%s '
                         'WHERE id=%s', (UUID(global_leg['id']), mapping_id))

        tenant_leg = reserve_leg(Reservation(
            policy=body.policy, units=body.units,
            idempotency_key='service:tenant:' + str(mapping_id),
            ttl_seconds=body.ttl_seconds), caller)
        if tenant_leg['status'] != 'pending':
            raise HTTPException(409, 'Tenant reservation is no longer pending')
        with database.transaction(caller.workspace) as conn:
            row = read(conn, mapping_id, lock=True)
            if row['operation'] is not None:
                raise HTTPException(409, 'Admission is already being finalized')
            row = one(conn, '''UPDATE data_service_admissions SET
                tenant_reservation_id=%s, status='pending', expires_at=%s,
                available_units=%s WHERE id=%s
                RETURNING *,expires_at<=clock_timestamp() AS expired''',
                      (UUID(tenant_leg['id']),
                       min(global_leg['expires_at'], tenant_leg['expires_at']),
                       min(global_leg['available'], tenant_leg['available']), mapping_id))
            if row['expired']:
                raise HTTPException(409, 'Admission has expired')
            return response(row)

    def finish(id, actual, release, principals):
        service, caller = principals
        operation = 'release' if release else 'settle'
        with database.transaction(caller.workspace) as conn:
            row = read(conn, id, lock=True)
            authorize(row, service, caller)
            if row['status'] == 'preparing':
                raise HTTPException(503, 'Admission is not fully reserved')
            if row['operation'] is not None:
                if row['operation'] != operation or row['actual_units'] != actual:
                    raise HTTPException(409, 'Admission finalization differs')
            elif release and row['expired']:
                # No refund after an ambiguous expiry. Late settlement remains
                # possible because this no-op does not commit a release intent.
                row = one(conn, "UPDATE data_service_admissions SET status='expired',"
                          'available_units=0 WHERE id=%s RETURNING *', (id,))
                return response(row)
            else:
                row = one(conn, 'UPDATE data_service_admissions SET operation=%s,'
                          'actual_units=%s WHERE id=%s RETURNING *',
                          (operation, actual, id))

        # Intent is durable before effects. Retrying the same intent may repeat
        # calls, but each underlying reservation finalizes only once.
        global_leg = finish_leg(row['global_reservation_id'], actual, release, service)
        tenant_leg = finish_leg(row['tenant_reservation_id'], actual, release, caller)
        status = ('expired' if release and 'expired' in (
            global_leg['status'], tenant_leg['status']) else
            ('released' if release else 'settled'))
        with database.transaction(caller.workspace) as conn:
            row = one(conn, 'UPDATE data_service_admissions SET status=%s,'
                      'available_units=%s WHERE id=%s RETURNING *',
                      (status, min(global_leg['available'], tenant_leg['available']), id))
            return response(row)

    @app.post('/v1/service/admissions/{id}/settle')
    def settle(id: UUID, body: Settlement, principals=Depends(pair)):
        return finish(id, body.actual_units, False, principals)

    @app.post('/v1/service/admissions/{id}/release')
    def release(id: UUID, body: Body, principals=Depends(pair)):
        return finish(id, 0, True, principals)
