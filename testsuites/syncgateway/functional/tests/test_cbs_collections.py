import uuid
import pytest
from keywords.ClusterKeywords import ClusterKeywords
from keywords.MobileRestClient import MobileRestClient
from keywords import couchbaseserver
from libraries.testkit.cluster import Cluster
from keywords.constants import RBAC_FULL_ADMIN
from libraries.testkit.admin import Admin
from keywords.exceptions import RestError
from requests.auth import HTTPBasicAuth
from keywords import document

# test file shared variables
bucket = "data-bucket"
sg_password = "password"
admin_client = cb_server = sg_username = channels = client_auth = sg_url = None
admin_auth = [RBAC_FULL_ADMIN['user'], RBAC_FULL_ADMIN['pwd']]
is_using_views = False


@pytest.fixture
def teardown_doc_fixture():
    def _delete_doc_if_exist(sg_client, url, db, doc_id, auth, scope, collection):
        if sg_client.does_doc_exist(url, db, doc_id, scope=scope, collection=collection) is True:
            sg_client.delete_doc(url, db, doc_id, auth=auth, scope=scope, collection=collection)
    yield _delete_doc_if_exist


@pytest.fixture
def scopes_collections_tests_fixture(params_from_base_test_setup, params_from_base_suite_setup):
    # get/set the parameters
    global admin_client
    global cb_server
    global sg_username
    global channels
    global client_auth
    global sg_url
    global is_using_views
    is_using_views = params_from_base_suite_setup["use_views"]

    try:  # To be able to teardon in case of a setup error
        pre_test_db_exists = pre_test_user_exists = sg_client = sg_url = sg_admin_url = None
        random_suffix = str(uuid.uuid4())[:8]
        db_prefix = "db_"
        scope_prefix = "scope_"
        collection_prefix = "collection_"
        db = db_prefix + random_suffix
        scope = scope_prefix + random_suffix
        collection = collection_prefix + random_suffix
        sg_username = "scopes_collections_user" + random_suffix
        client_auth = HTTPBasicAuth(sg_username, sg_password)
        channels = ["ABC"]
        data = {"bucket": bucket, "scopes": {scope: {"collections": {collection: {}}}}, "num_index_replicas": 0}
        cluster_config = params_from_base_test_setup["cluster_config"]
        sg_admin_url = params_from_base_test_setup["sg_admin_url"]
        cluster_helper = ClusterKeywords(cluster_config)
        topology = cluster_helper.get_cluster_topology(cluster_config)
        cbs_url = topology["couchbase_servers"][0]
        sg_url = topology["sync_gateways"][0]["public"]
        cluster = Cluster(config=cluster_config)
        sg_client = MobileRestClient()
        cb_server = couchbaseserver.CouchbaseServer(cbs_url)
        admin_client = Admin(cluster.sync_gateways[0])
        sg_url = params_from_base_test_setup["sg_url"]

        # Scope creation on the Couchbase server
        does_scope_exist = cb_server.does_scope_exist(bucket, scope)
        if does_scope_exist is False:
            cb_server.create_scope(bucket, scope)
        cb_server.create_collection(bucket, scope, collection)

        # SGW database creation
        pre_test_db_exists = admin_client.does_db_exist(db)
        test_bucket_db = admin_client.get_bucket_db(bucket)
        if test_bucket_db is not None:
            admin_client.delete_db(test_bucket_db)
        if pre_test_db_exists is False:
            admin_client.create_db(db, data)

        # Create a user
        pre_test_user_exists = admin_client.does_user_exist(db, sg_username)
        if pre_test_user_exists is False:
            sg_client.create_user(sg_admin_url, db, sg_username, sg_password, auth=admin_auth)

        yield sg_client, sg_admin_url, db, scope, collection
    except Exception as e:
        raise e
    finally:
        # Cleanup everything that was created
        if (pre_test_user_exists is not None) and (pre_test_user_exists is False):
            admin_client.delete_user_if_exists(db, sg_username)
        if (pre_test_db_exists is not None) and (pre_test_db_exists is False):
            if admin_client.does_db_exist(db) is True:
                admin_client.delete_db(db)
        cb_server.delete_scope_if_exists(bucket, scope)


@pytest.mark.syncgateway
@pytest.mark.collections
def test_document_only_under_named_scope(scopes_collections_tests_fixture, teardown_doc_fixture):
    if is_using_views:
        pytest.skip("""It is not necessary to run scopes and collections tests with views.
                When it is enabled, there is a problem that affects the rest of the tests suite.""")

    # setup
    doc_prefix = "scp_tests_doc"
    doc_id = doc_prefix + "_0"
    sg_client, sg_admin_url, db, scope, collection = scopes_collections_tests_fixture
    if sg_client.does_doc_exist(sg_admin_url, db, doc_id, scope=scope, collection=collection) is False:
        sg_client.add_docs(sg_url, db, 1, doc_prefix, auth=client_auth, scope=scope, collection=collection)
    teardown_doc_fixture(sg_client, sg_admin_url, db, doc_id, auth=client_auth, scope=scope, collection=collection)

    # exercise + verification
    try:
        sg_client.get_doc(sg_admin_url, db, doc_id, scope=scope, collection=collection)
    except Exception as e:
        pytest.fail("There was a problem reading the document from a collection when specifying the scope in the endpoint. The error: " + str(e))

    # exercise + verification
    try:
        sg_client.get_doc(sg_admin_url, db, doc_id, collection=collection)
    except Exception as e:
        pytest.fail("There was a problem reading the document from a collection WITHOUT specifying the scope in the endoint. The error: " + str(e))

    #  exercise + verification
    with pytest.raises(Exception) as e:  # HTTPError doesn't work, for some  reason, but would be preferable
        sg_client.get_doc(sg_admin_url, db, doc_id, scope="_default", collection=collection)
    e.match("Not Found")


@pytest.mark.syncgateway
@pytest.mark.collections
def test_change_scope_or_collection_name(scopes_collections_tests_fixture):
    """
    1. Upload a document to a collection
    2. Rename the collection by updating the config
    3. Check that the document is not accessiable in the new collection
    4. Rename the collection to the original collection
    5. Verify that the document is accessible again
    6. Change the scope name and expect a "Bad Rquest" error
    """
    if is_using_views:
        pytest.skip("""It is not necessary to run scopes and collections tests with views.
                When it is enabled, there is a problem that affects the rest of the tests suite.""")

    # setup
    sg_client, sg_admin_url, db, scope, collection = scopes_collections_tests_fixture
    doc_prefix = "scp_tests_doc"
    doc_id = doc_prefix + "_0"
    new_collection_name = "new_collection_test"

    # 1. Upload a document to a collection
    if sg_client.does_doc_exist(sg_admin_url, db, doc_id, scope=scope, collection=collection) is False:
        sg_client.add_docs(sg_admin_url, db, 1, doc_prefix, scope=scope, collection=collection)

    # 2. Rename the collection by updating the config
    cb_server.create_collection(bucket, scope, new_collection_name)
    rename_a_single_scope_or_collection(db, scope, new_collection_name)

    #  exercise + verification
    with pytest.raises(Exception) as e:  # HTTPError doesn't work, for some reason, but would be preferable
        sg_client.get_doc(sg_admin_url, db, doc_id, scope=scope, collection=new_collection_name)
    e.match("Not Found")

    # 4. Rename the collection to the original collection
    rename_a_single_scope_or_collection(db, scope, collection)

    # 5. Verify that the document is accessible again
    try:
        sg_client.get_doc(sg_admin_url, db, doc_id, scope=scope, collection=collection)
    except Exception as e:
        pytest.fail("The document could not be read from the collection after it was renamed and renamed back. The error: " + str(e))
    # 6. Change the scope name and expect a "Bad Rquest" error
    with pytest.raises(Exception) as e:
        rename_a_single_scope_or_collection(db, "new_scope", collection)
    e.match("Bad Request")


@pytest.mark.syncgateway
@pytest.mark.collections
def test_collection_channels(scopes_collections_tests_fixture):
    """
    1. Create 3 users with different channels, one is in the wildcard channel
    2. Upload the documents to the collection, under the user's channels and one to the public channel
    3. Get all the documents using _all_docs
    4. Check that the users can only see the documents in their channel
    5. Check that the users see the shared document in the channel
    6. Check that _bulk_get cannot get documents that are not in the user's channel
    7. Check that _bulk_get can get documents that are in the user's channel
    8. Check that _bulk_get cannot get a document from the "right" channel but the wrong collection
    """
    if is_using_views:
        pytest.skip("""It is not necessary to run scopes and collections tests with views.
                When it is enabled, there is a problem that affects the rest of the tests suite.""")

    # setup
    sg_client, sg_admin_url, db, scope, collection = scopes_collections_tests_fixture
    random_str = str(uuid.uuid4())[:6]
    test_user_1 = "cu1_" + random_str
    test_user_2 = "cu2_" + random_str
    test_wildcard_user = "wu_" + random_str
    user_1_doc_prefix = "user_1_doc_" + random_str
    user_2_doc_prefix = "user_2_doc_" + random_str
    shared_doc_prefix = "shared_" + random_str
    channels_user_1 = ["USER1_CHANNEL"]
    channels_user_2 = ["USER2_CHANNEL"]
    auth_user_1 = test_user_1, sg_password
    auth_user_2 = test_user_2, sg_password
    auth_wildcard_user = test_wildcard_user, sg_password

    # 1. Create 3 users with different channels, one is in the wildcard channel
    sg_client.create_user(sg_admin_url, db, test_user_1, sg_password, channels=channels_user_1, auth=admin_auth)
    sg_client.create_user(sg_admin_url, db, test_user_2, sg_password, channels=channels_user_2, auth=admin_auth)
    sg_client.create_user(sg_admin_url, db, test_wildcard_user, sg_password, channels=["*"], auth=admin_auth)

    # 2. Upload the documents to the collection
    sg_client.add_docs(sg_url, db, 3, user_1_doc_prefix, auth=auth_user_1, channels=channels_user_1, scope=scope, collection=collection)
    sg_client.add_docs(sg_url, db, 3, user_2_doc_prefix, auth=auth_user_2, channels=channels_user_2, scope=scope, collection=collection)
    shared_doc = sg_client.add_docs(sg_admin_url, db, 1, shared_doc_prefix, auth=client_auth, channels=["!"], scope=scope, collection=collection)

    # 3. Get all the documents using _all_docs
    user_1_docs = sg_client.get_all_docs(url=sg_url, db=db, auth=auth_user_1, include_docs=True, scope=scope, collection=collection)
    user_2_docs = sg_client.get_all_docs(url=sg_url, db=db, auth=auth_user_2, include_docs=True, scope=scope, collection=collection)
    wildcard_user_docs = sg_client.get_all_docs(url=sg_url, db=db, auth=auth_wildcard_user, include_docs=True, scope=scope, collection=collection)

    user_1_docs_ids = [doc["id"] for doc in user_1_docs["rows"]]
    user_2_docs_ids = [doc["id"] for doc in user_2_docs["rows"]]
    wildcard_user_docs_ids = [doc["id"] for doc in wildcard_user_docs["rows"]]
    shared_found_user_1 = False
    shared_found_user_2 = False

    # 4. Check that the users can only see the documents in their channels
    for doc in user_1_docs_ids:
        if user_2_doc_prefix in doc:
            pytest.fail("A document is available in a channel that it was not assigned to. Document prefix: " + user_2_doc_prefix + ". The document: " + doc)
        if shared_doc_prefix in doc:
            shared_found_user_1 = True
        if doc not in wildcard_user_docs_ids:
            pytest.fail("The document " + doc + " was not accessible even though the user was given all documents access")
    for doc in user_2_docs_ids:
        if user_1_doc_prefix in doc:
            pytest.fail("A document is available in a channel that it was not assigned to. Document prefix: " + user_1_doc_prefix + ". The document: " + doc)
        if shared_doc_prefix in doc:
            shared_found_user_2 = True
        if doc not in wildcard_user_docs_ids:
            pytest.fail("The document " + doc + " was not accessible even though the user was given all documents access")

    # 5. Check that the users see the shared document in their channels
    assert (shared_found_user_1 and shared_found_user_2), "The shared document was not found for one of the users. user1: " + str(shared_found_user_1) + " user2: " + str(shared_found_user_2)
    assert (shared_doc[0]["id"] in wildcard_user_docs_ids), "The shared document was not accessiable VIA the wildcard channel"

    # 6. Check that _bulk_get cannot get documents that are not in the user's channel
    with pytest.raises(RestError) as e:  # HTTPError doesn't work, for some  reason, but would be preferable
        sg_client.get_bulk_docs(url=sg_url, db=db, doc_ids=user_2_docs_ids, auth=auth_user_1, scope=scope, collection=collection)
    assert "'status': 403" in str(e)
    # 7. Check that _bulk_get can get documents that are in the user's channel
    sg_client.get_bulk_docs(url=sg_url, db=db, doc_ids=user_1_docs_ids, auth=auth_user_1, scope=scope, collection=collection)

    # 8. Check that _bulk_get cannot get a document from the "right" channel but the wrong collection
    with pytest.raises(Exception) as e:
        sg_client.get_bulk_docs(url=sg_url, db=db, doc_ids=user_1_docs_ids, auth=auth_user_1, scope=scope, collection="fake_collection")
    e.match("Not Found")


@pytest.mark.syncgateway
@pytest.mark.collections
def test_restricted_collection(scopes_collections_tests_fixture):
    """
    1. Create two more collections on CB server
    2. Add documents to the collections on CB server
    3. Sync two out of three collections to SGW
    4. Check that documents that are in the server restricted collection are not accessible via SGW
    """

    if is_using_views:
        pytest.skip("""It is not necessary to run scopes and collections tests with views.
                When it is enabled, there is a problem that affects the rest of the tests suite.""")

    sg_client, sg_admin_url, db, scope, collection = scopes_collections_tests_fixture
    # 1. Create two more collections on CB server
    random_suffix = str(uuid.uuid4())[:8]
    second_collection = "collection_2" + random_suffix
    third_collection = "collection_3" + random_suffix
    cb_server.create_collection(bucket, scope, second_collection)
    cb_server.create_collection(bucket, scope, third_collection)

    doc_1_key = "doc_1" + random_suffix
    doc_2_key = "doc_2" + random_suffix
    doc_3_key = "doc_3" + random_suffix

    # 2. Add a document to each collection
    cb_server.add_simple_document(doc_1_key, bucket, scope, collection)
    cb_server.add_simple_document(doc_2_key, bucket, scope, second_collection)
    cb_server.add_simple_document(doc_3_key, bucket, scope, third_collection)

    assert(cb_server.get_document(doc_1_key, bucket, scope, collection)["id"] == doc_1_key), "Error in test setup: failed to add document to server under " + bucket + "." + scope + "." + collection
    assert(cb_server.get_document(doc_2_key, bucket, scope, second_collection)["id"] == doc_2_key), "Error in test setup: failed to add document to server under " + bucket + "." + scope + "." + second_collection
    assert(cb_server.get_document(doc_3_key, bucket, scope, third_collection)["id"] == doc_3_key), "Error in test setup: failed to add document to server under " + bucket + "." + scope + "." + third_collection

    # 3. Sync two collections to SGW
    db_config = {"bucket": bucket, "scopes": {scope: {"collections": {collection: {}, second_collection: {}}}}, "num_index_replicas": 0,
                 "import_docs": True, "enable_shared_bucket_access": True}
    admin_client.post_db_config(db, db_config)
    admin_client.wait_for_db_online(db, 60)

    # 4. Check that documents in the server restricted collection are not accesible via SGW
    all_docs_ids = []

    for row in (sg_client.get_all_docs(sg_admin_url, db, scope=scope, collection=collection)["rows"]):
        all_docs_ids.append(row["id"])
    for row in (sg_client.get_all_docs(sg_admin_url, db, scope=scope, collection=second_collection)["rows"]):
        all_docs_ids.append(row["id"])

    assert(len(all_docs_ids) == 2), "Number of expected documents in Sync Gateway database does not match expected. Expected 2; Found " + str(len(all_docs_ids))
    assert(doc_3_key not in all_docs_ids), "Sync Gateway contains document from server restricted collection. Document ID " + doc_3_key + "under " + bucket + "." + scope + "." + third_collection


@pytest.mark.syncgateway
@pytest.mark.collections
def test_user_collections_access(scopes_collections_tests_fixture):

    if is_using_views:
        pytest.skip("""It is not necessary to run scopes and collections tests with views.
                When it is enabled, there is a problem that affects the rest of the tests suite.""")

    sg_client, sg_admin_url, db, scope, collection = scopes_collections_tests_fixture

    users = sg_client.get_users(sg_admin_url, db)
    for user in users:
        print(user)


@pytest.mark.syncgateway
@pytest.mark.collections
def test_apis_support_collections(scopes_collections_tests_fixture):
    """
    Specifically test various APIs:
    1.  Add documents using bulk_docs
    2.  Purge one of the documents
    3.  Get a raw document
    """
    if is_using_views:
        pytest.skip("""It is not necessary to run scopes and collections tests with views.
                When it is enabled, there is a problem that affects the rest of the tests suite.""")

    sg_client, sg_admin_url, db, scope, collection = scopes_collections_tests_fixture
    user_session = sg_client.create_session(url=sg_admin_url, db=db, name=sg_username)
    created_docs = document.create_docs(doc_id_prefix='collections_api_docs', number=3, channels=channels)
    created_doc_ids = []
    for doc_info in created_docs:
        created_doc_ids.append(doc_info["_id"])
    # 1. Add documents using bulk_docs
    sg_docs = sg_client.add_bulk_docs(url=sg_url, db=db, docs=created_docs, auth=user_session, scope=scope, collection=collection)
    uplodad_docs = sg_client.get_all_docs(url=sg_admin_url, db=db, include_docs=True, scope=scope, collection=collection)

    # Check that the document was added
    for doc_key in uplodad_docs["rows"]:
        if doc_key["id"] not in created_doc_ids:
            assert False, "The document " + doc_key["id"] + " was not uploaded using POST add_bulk"

    # 2. Purge one document
    bulk_doc = sg_client.get_doc(sg_admin_url, db, sg_docs[0]["id"], scope=scope, collection=collection)
    sg_client.purge_doc(sg_admin_url, db, bulk_doc, scope=scope, collection=collection)
    # Check that the document was purged
    with pytest.raises(Exception) as e:
        sg_client.get_doc(sg_admin_url, db, sg_docs[0]["id"], scope=scope, collection=collection)
    e.match("Not Found")

    # 3.  Get a raw document
    raw_doc = sg_client.get_raw_doc(sg_admin_url, db, sg_docs[1]["id"], auth=user_session, scope=scope, collection=collection)
    assert uplodad_docs["rows"][1]["value"]["rev"] == raw_doc["_sync"]["rev"], "The wrong raw document was fetched"


def rename_a_single_scope_or_collection(db, scope, new_name):
    data = {"bucket": bucket, "scopes": {scope: {"collections": {new_name: {}}}}, "num_index_replicas": 0}
    admin_client.post_db_config(db, data)
    admin_client.wait_for_db_online(db, 60)
