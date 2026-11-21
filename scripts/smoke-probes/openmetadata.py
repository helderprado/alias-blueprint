base = 'http://openmetadata.openmetadata.svc.cluster.local:8585/api/v1'
headers = {'Authorization': 'Bearer ' + SMOKE['token']}
mlflow = 'http://mlflow.mlflow.svc.cluster.local:5000'
model = request(mlflow + '/api/2.0/mlflow/registered-models/get?name=' + SMOKE['model'])['registered_model']
service = request(base + '/services/mlmodelServices', 'POST', {
    'name': 'alias_smoke_mlflow', 'serviceType': 'Mlflow',
    'connection': {'config': {'type': 'Mlflow', 'trackingUri': mlflow, 'registryUri': mlflow}}}, headers)
entity = request(base + '/mlmodels', 'PUT', {'name': model['name'], 'algorithm': 'synthetic',
    'service': service['fullyQualifiedName'], 'description': 'Synthetic MLflow API import'}, headers)
assert request(base + '/mlmodels/' + entity['id'], headers=headers)['name'] == SMOKE['model']
def indexed():
    result = request(base + '/search/query?' + urllib.parse.urlencode({'q': SMOKE['model'], 'index': 'mlmodel_search_index'}), headers=headers)
    return any(hit['_source']['name'] == SMOKE['model'] for hit in result.get('hits', {}).get('hits', []))
wait_for(indexed, 'MLflow model indexed in OpenMetadata/OpenSearch')
print('PASS: API import of MLflow model, catalog persistence and search (OIDC/ingestion connector excluded)')
