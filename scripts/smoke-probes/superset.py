from pathlib import Path
from sqlalchemy.engine import URL
from superset.app import create_app

Path('/tmp/alias-trino-ca.pem').write_text(SMOKE['ca'])
uri = URL.create('trino', username=SMOKE['user'], password=SMOKE['password'],
                 host='trino.trino.svc.cluster.local', port=8443, database='pinot/default',
                 query={'protocol': 'https'}).render_as_string(hide_password=False)
extra = {'engine_params': {'connect_args': {'verify': '/tmp/alias-trino-ca.pem'}}}
app = create_app()
with app.app_context():
    from superset import db
    from superset.extensions import cache_manager
    from superset.models.core import Database, Slice, Dashboard
    from superset.connectors.sqla.models import SqlaTable
    database = Database(database_name='alias_smoke_trino', sqlalchemy_uri=uri,
                        extra=json.dumps(extra), expose_in_sqllab=True)
    db.session.add(database)
    db.session.flush()
    # Use Superset's configured database connection, including its TLS options.
    with database.get_sqla_engine() as engine:
        with engine.connect() as connection:
            from sqlalchemy import text
            row = connection.execute(text('SELECT count(*), sum(amount) FROM alias_smoke')).fetchone()
            assert list(row) == [3, 60], row
    table = SqlaTable(table_name='alias_smoke', schema='default', database=database)
    db.session.add(table)
    db.session.flush()
    chart = Slice(slice_name='Alias smoke count', datasource_id=table.id, datasource_type='table',
                  viz_type='table', params=json.dumps({'all_columns': ['id', 'amount'], 'row_limit': 10}))
    dashboard = Dashboard(dashboard_title='Alias smoke dashboard', published=True)
    dashboard.slices = [chart]
    db.session.add_all([chart, dashboard])
    db.session.commit()
    assert db.session.query(Dashboard).filter_by(dashboard_title='Alias smoke dashboard').one().slices[0].id == chart.id
    cache_manager.cache.set('alias_smoke_probe', 'roundtrip', timeout=60)
    assert cache_manager.cache.get('alias_smoke_probe') == 'roundtrip'
    cache_manager.cache.delete('alias_smoke_probe')
request('http://127.0.0.1:8088/health')
print('PASS: Superset -> Trino -> Pinot query, Redis cache and saved dataset/chart/dashboard')
