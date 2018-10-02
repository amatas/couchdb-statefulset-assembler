"""Helper module to connect a CouchDB Kube StatefulSet

This script grabs the list of pod names behind the headless service
associated with our StatefulSet and feeds those as `couchdb@FQDN`
nodes to mem3.
"""

import json
import requests
import time
import dns.resolver
import socket
import backoff
import os

def construct_service_record():
    # Drop our Pod's unique identity and replace with '_couchdb._tcp'
    return os.getenv('SRV_RECORD') or '.'.join(['_couchdb', '_tcp'] + socket.getfqdn().split('.')[1:])

@backoff.on_exception(
    backoff.expo,
    dns.resolver.NXDOMAIN,
    max_tries=10
)
def discover_peers(service_record):
    print ('Resolving SRV record', service_record)
    answers = dns.resolver.query(service_record, 'SRV')
    # Erlang requires that we drop the trailing period from the absolute DNS
    # name to form the hostname used for the Erlang node. This feels hacky
    # but not sure of a more official answer
    return [rdata.target.to_text()[:-1] for rdata in answers]

@backoff.on_exception(
    backoff.expo,
    requests.exceptions.ConnectionError,
    max_tries=10
)

def request(verb='get', uri='', doc='{}'):
    creds = (os.getenv("COUCHDB_USER"), os.getenv("COUCHDB_PASSWORD"))
    if verb=='put':
        if creds[0] and creds[1]:
            return requests.put(uri, data=json.dumps(doc), auth=creds)
        else:
            return requests.put(uri, data=json.dumps(doc))
    else:
        if creds[0] and creds[1]:
            return requests.get(uri, data=json.dumps(doc), auth=creds)
        else:
            return requests.get(uri, data=json.dumps(doc))

def connect_the_dots(names):
    print('Connecting the dots')
    for name in names:
        uri = "http://127.0.0.1:5986/_nodes/couchdb@{0}".format(name)
        doc = {}
        resp = request(verb='put', uri=uri, doc=doc)
        while resp.status_code == 404:
            print('Waiting for _nodes DB to be created ...')
            time.sleep(5)
            resp = request(verb='put', uri=uri, doc=doc)
        print('Adding cluster member', name, resp.status_code)

def create_initial_databases():
    print('Creeating initial databases')
    ADMIN_DBS = ('_dbs', '_users', '_replicator')
    uri = "http://127.0.0.1:5986/_all_dbs"
    # get all dbs
    existing_dbs = request(verb='get', uri=uri).json()
    # create dbs left
    dbs = [ d for d in ADMIN_DBS if not d in existing_dbs ]
    for dbname in dbs:
        uri = "http://127.0.0.1:5986/{0}".format(dbname)
        resp = request(verb='put', uri=uri)
        while resp.status_code == 404:
            print("Waiting for {0} DB to be created ...".format(dbname))
            time.sleep(1)
            resp = request(verb='put', uri=uri)

def sleep_forever():
    while True:
        time.sleep(5)

if __name__ == '__main__':
    connect_the_dots(discover_peers(construct_service_record()))
    print('Cluster membership populated!')
    create_initial_databases()
    sleep_forever()
