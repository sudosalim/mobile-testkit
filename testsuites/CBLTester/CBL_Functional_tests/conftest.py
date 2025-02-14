import time
import pytest
import datetime
import zipfile
import os
import io

from utilities.cluster_config_utils import persist_cluster_config_environment_prop, get_cluster
from keywords.utils import log_info
from keywords.utils import host_for_url, clear_resources_pngs
from keywords.ClusterKeywords import ClusterKeywords
from keywords.couchbaseserver import CouchbaseServer
from keywords.constants import CLUSTER_CONFIGS_DIR
from keywords.MobileRestClient import MobileRestClient
from keywords.TestServerFactory import TestServerFactory
from keywords.SyncGateway import sync_gateway_config_path_for_mode
from keywords.SyncGateway import SyncGateway
from keywords.exceptions import ProvisioningError
from keywords.tklogging import Logging
from keywords.constants import RESULTS_DIR

from CBLClient.FileLogging import FileLogging
from CBLClient.Replication import Replication
from CBLClient.Collection import Collection
from CBLClient.Scope import Scope
from CBLClient.BasicAuthenticator import BasicAuthenticator
from CBLClient.Database import Database
from CBLClient.Document import Document
from CBLClient.Array import Array
from CBLClient.Dictionary import Dictionary
from CBLClient.DataTypeInitiator import DataTypeInitiator
from CBLClient.SessionAuthenticator import SessionAuthenticator
from CBLClient.Utils import Utils
from CBLClient.ReplicatorConfiguration import ReplicatorConfiguration
from utilities.cluster_config_utils import get_load_balancer_ip
from libraries.testkit import prometheus


def pytest_addoption(parser):
    parser.addoption("--mode",
                     action="store",
                     help="Sync Gateway mode to run the test in, 'cc' for channel cache or 'di' for distributed index")

    parser.addoption("--skip-provisioning",
                     action="store_true",
                     help="Skip cluster provisioning at setup",
                     default=False)

    parser.addoption("--use-local-testserver",
                     action="store_true",
                     help="Skip download and launch TestServer, use local debug build",
                     default=False)

    parser.addoption("--server-version",
                     action="store",
                     help="server-version: Couchbase Server version to install (ex. 4.5.0 or 4.5.0-2601)")

    parser.addoption("--sync-gateway-version",
                     action="store",
                     help="sync-gateway-version: Sync Gateway version to install "
                          "(ex. 1.3.1-16 or 590c1c31c7e83503eff304d8c0789bdd268d6291)")

    parser.addoption("--liteserv-platform",
                     action="store",
                     help="liteserv-platform: the platform to assign to the liteserv")

    parser.addoption("--liteserv-version",
                     action="store",
                     help="liteserv-version: the version to download / install for the liteserv")

    parser.addoption("--liteserv-host",
                     action="store",
                     help="liteserv-host: the host to start liteserv on")

    parser.addoption("--liteserv-port",
                     action="store",
                     help="liteserv-port: the port to assign to liteserv")

    parser.addoption("--enable-sample-bucket",
                     action="store",
                     help="enable-sample-bucket: Enable a sample server bucket")

    parser.addoption("--xattrs",
                     action="store_true",
                     help="xattrs: Enable xattrs for sync gateway")

    parser.addoption("--create-db-per-test",
                     action="store",
                     help="create-db-per-test: Creates/deletes client DB for every test")

    parser.addoption("--create-db-per-suite",
                     action="store",
                     help="create-db-per-suite: Creates/deletes client DB per suite")

    parser.addoption("--no-conflicts",
                     action="store_true",
                     help="If set, allow_conflicts is set to false in sync-gateway config")

    parser.addoption("--device", action="store_true",
                     help="Enable device if you want to run it on device", default=False)

    parser.addoption("--cbl-ce", action="store_true",
                     help="If set, community edition will get picked up , default is enterprise", default=False)

    parser.addoption("--cbs-ce", action="store_true",
                     help="If set, community edition will get picked up , default is enterprise", default=False)

    parser.addoption("--sg-ce", action="store_true",
                     help="If set, community edition will get picked up , default is enterprise", default=False)

    parser.addoption("--sg-ssl",
                     action="store_true",
                     help="If set, will enable SSL communication between Sync Gateway and CBL")

    parser.addoption("--flush-memory-per-test",
                     action="store_true",
                     help="If set, will flush server memory per test")

    parser.addoption("--sg-lb",
                     action="store_true",
                     help="If set, will enable load balancer for Sync Gateway")

    parser.addoption("--ci",
                     action="store_true",
                     help="If set, will target larger cluster (3 backing servers instead of 1, 2 accels if in di mode)")

    parser.addoption("--debug-mode", action="store_true",
                     help="Enable debug mode for the app ", default=False)

    parser.addoption("--use-views",
                     action="store_true",
                     help="If set, uses views instead of GSI - SG 2.1 and above only")

    parser.addoption("--number-replicas",
                     action="store",
                     help="Number of replicas for the indexer node - SG 2.1 and above only",
                     default=0)

    parser.addoption("--enable-file-logging",
                     action="store_true",
                     help="If set, CBL file logging would enable. Supported only cbl2.5 onwards")

    parser.addoption("--delta-sync",
                     action="store_true",
                     help="delta-sync: Enable delta-sync for sync gateway")

    parser.addoption("--cbl-log-decoder-platform",
                     action="store",
                     help="cbl-log-decoder-platform: the platform to assign to the cbl-log-decoder platform")

    parser.addoption("--cbl-log-decoder-build",
                     action="store",
                     help="cbl-log-decoder-build: the platform to assign to the cbl-log-decoder build")

    parser.addoption("--disable-encryption",
                     action="store_true",
                     help="Encryption will be enabled for CBL db",
                     default=False)

    parser.addoption("--encryption-password",
                     action="store",
                     help="Encryption will be enabled for CBL db",
                     default="password")

    parser.addoption("--prometheus-enable",
                     action="store",
                     help="Starts the prometheus metrics",
                     default=False)

    parser.addoption("--hide-product-version",
                     action="store_true",
                     help="Hides SGW product version when you hit SGW url",
                     default=False)

    parser.addoption("--skip-couchbase-provision",
                     action="store_true",
                     help="skip the couchbase provision step")

    parser.addoption("--enable-cbs-developer-preview",
                     action="store_true",
                     help="Enabling CBS developer preview",
                     default=False)

    parser.addoption("--server-ssl",
                     action="store_true",
                     help="If set, will enable SSL communication between server and Sync Gateway")

    parser.addoption("--magma-storage",
                     action="store_true",
                     help="magma-storage: Enable magma storage on couchbase server")

    parser.addoption("--disable-persistent-config",
                     action="store_true",
                     help="Disable Centralized Persistent Config")

    parser.addoption("--enable-server-tls-skip-verify",
                     action="store_true",
                     help="Enable Server tls skip verify config")

    parser.addoption("--disable-tls-server",
                     action="store_true",
                     help="Disable tls server")

    parser.addoption("--disable-admin-auth",
                     action="store_true",
                     help="Disable Admin auth")

    parser.addoption("--liteserv-android-serial-number",
                     action="store",
                     help="liteserv-android-serial-number: the serial number of the android device to be used")

    parser.addoption("--android-id",
                     action="store",
                     help="android-id: the serial number of the android device to be used")

    parser.addoption("--scope-on-bucket",
                     action="store",
                     help="scope will be create on bucket",
                     default="default")
    parser.addoption("--scope-name",
                     action="store",
                     help="default scope name is _default",
                     default="_default")
    parser.addoption("--collection-name",
                     action="store",
                     help="default collection name is _default",
                     default="_default")

    parser.addoption("--collection-on-default-scope",
                     action="store",
                     help="collection will be create on default scope _default",
                     default="_default")


# Pass liteserv_version to testsuite
def pytest_configure(config):
    pytest.liteserv_version = config.getoption("--liteserv-version")


# This will get called once before the first test that
# runs with this as input parameters in this file
# This setup will be called once for all tests in the
# testsuites/CBLTester/CBL_Functional_tests/ directory
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
@pytest.fixture(scope="session")
def params_from_base_suite_setup(request):
    liteserv_platform = request.config.getoption("--liteserv-platform")
    liteserv_version = request.config.getoption("--liteserv-version")
    liteserv_host = request.config.getoption("--liteserv-host")
    liteserv_port = request.config.getoption("--liteserv-port")

    skip_provisioning = request.config.getoption("--skip-provisioning")
    use_local_testserver = request.config.getoption("--use-local-testserver")
    sync_gateway_version = request.config.getoption("--sync-gateway-version")
    disable_tls_server = request.config.getoption("--disable-tls-server")
    mode = request.config.getoption("--mode")
    server_version = request.config.getoption("--server-version")
    enable_sample_bucket = request.config.getoption("--enable-sample-bucket")
    xattrs_enabled = request.config.getoption("--xattrs")
    create_db_per_test = request.config.getoption("--create-db-per-test")
    create_db_per_suite = request.config.getoption("--create-db-per-suite")
    device_enabled = request.config.getoption("--device")
    cbl_ce = request.config.getoption("--cbl-ce")
    cbs_ce = request.config.getoption("--cbs-ce")
    sg_ce = request.config.getoption("--sg-ce")
    sg_ssl = request.config.getoption("--sg-ssl")
    flush_memory_per_test = request.config.getoption("--flush-memory-per-test")
    sg_lb = request.config.getoption("--sg-lb")
    ci = request.config.getoption("--ci")
    debug_mode = request.config.getoption("--debug-mode")
    no_conflicts_enabled = request.config.getoption("--no-conflicts")
    use_views = request.config.getoption("--use-views")
    number_replicas = request.config.getoption("--number-replicas")
    delta_sync_enabled = request.config.getoption("--delta-sync")
    enable_file_logging = request.config.getoption("--enable-file-logging")
    cbl_log_decoder_platform = request.config.getoption("--cbl-log-decoder-platform")
    cbl_log_decoder_build = request.config.getoption("--cbl-log-decoder-build")
    prometheus_enable = request.config.getoption("--prometheus-enable")
    disable_encryption = request.config.getoption("--disable-encryption")
    encryption_password = request.config.getoption("--encryption-password")
    hide_product_version = request.config.getoption("--hide-product-version")
    skip_couchbase_provision = request.config.getoption("--skip-couchbase-provision")
    enable_cbs_developer_preview = request.config.getoption("--enable-cbs-developer-preview")
    cbs_ssl = request.config.getoption("--server-ssl")
    magma_storage_enabled = request.config.getoption("--magma-storage")
    disable_persistent_config = request.config.getoption("--disable-persistent-config")
    enable_server_tls_skip_verify = request.config.getoption("--enable-server-tls-skip-verify")
    disable_tls_server = request.config.getoption("--disable-tls-server")

    disable_admin_auth = request.config.getoption("--disable-admin-auth")
    liteserv_android_serial_number = request.config.getoption("--liteserv-android-serial-number")
    android_id = request.config.getoption("--android-id")


    scope_name = request.config.getoption("--scope-name")
    collection_name = request.config.getoption("--collection-name")

    test_name = request.node.name

    testserver = TestServerFactory.create(platform=liteserv_platform,
                                          version_build=liteserv_version,
                                          host=liteserv_host,
                                          port=liteserv_port,
                                          community_enabled=cbl_ce,
                                          debug_mode=debug_mode)

    if not use_local_testserver:
        log_info("Downloading TestServer ...")
        # Download TestServer app
        testserver.download()

        # Install TestServer app
        if device_enabled:
            if "android" in liteserv_platform:
                if liteserv_android_serial_number:
                    testserver.serial_number = liteserv_android_serial_number
                if android_id:
                    testserver.android_id = android_id
            testserver.install_device()
        else:
            testserver.install()

    base_url = "http://{}:{}".format(liteserv_host, liteserv_port)
    sg_config = sync_gateway_config_path_for_mode("sync_gateway_travel_sample", mode)

    sg_db = "db"
    suite_cbl_db = None

    # use base_(lb_)cc cluster config if mode is "cc" or base_(lb_)di cluster config if mode is "di"
    if ci:
        cluster_config = "{}/ci_{}".format(CLUSTER_CONFIGS_DIR, mode)
        if sg_lb:
            cluster_config = "{}/ci_lb_{}".format(CLUSTER_CONFIGS_DIR, mode)
    else:
        cluster_config = "{}/base_{}".format(CLUSTER_CONFIGS_DIR, mode)
        if sg_lb:
            cluster_config = "{}/base_lb_{}".format(CLUSTER_CONFIGS_DIR, mode)

    cluster_utils = ClusterKeywords(cluster_config)
    cluster_topology = cluster_utils.get_cluster_topology(cluster_config)

    sg_url = cluster_topology["sync_gateways"][0]["public"]
    sg_ip = host_for_url(sg_url)

    persist_cluster_config_environment_prop(cluster_config, 'sync_gateway_ssl', False)
    target_url = "ws://{}:4984/{}".format(sg_ip, sg_db)
    target_admin_url = "ws://{}:4985/{}".format(sg_ip, sg_db)

    if sg_ssl:
        log_info("Enabling SSL on sync gateway")
        persist_cluster_config_environment_prop(cluster_config, 'sync_gateway_ssl', True)
        target_url = "wss://{}:4984/{}".format(sg_ip, sg_db)
        target_admin_url = "wss://{}:4985/{}".format(sg_ip, sg_db)

    if sg_lb:
        persist_cluster_config_environment_prop(cluster_config, 'sg_lb_enabled', True)
        log_info("Running tests with load balancer enabled: {}".format(get_load_balancer_ip(cluster_config)))
    else:
        log_info("Running tests with load balancer disabled")
        persist_cluster_config_environment_prop(cluster_config, 'sg_lb_enabled', False)

    try:
        server_version
    except NameError:
        log_info("Server version is not provided")
        persist_cluster_config_environment_prop(cluster_config, 'server_version', "")
    else:
        log_info("Running test with server version {}".format(server_version))
        persist_cluster_config_environment_prop(cluster_config, 'server_version', server_version)

    try:
        sync_gateway_version
    except NameError:
        log_info("Sync gateway version is not provided")
        persist_cluster_config_environment_prop(cluster_config, 'sync_gateway_version', "")
    else:
        log_info("Running test with sync_gateway version {}".format(sync_gateway_version))
        persist_cluster_config_environment_prop(cluster_config, 'sync_gateway_version', sync_gateway_version)

    try:
        cbl_log_decoder_platform
    except NameError:
        log_info("cbl_log_decoder_platform is not provided")
        persist_cluster_config_environment_prop(cluster_config, 'cbl_log_decoder_platform', "macos",
                                                property_name_check=False)
    else:
        log_info("Running test with cbl_log_decoder_platform {}".format(cbl_log_decoder_platform))
        persist_cluster_config_environment_prop(cluster_config, 'cbl_log_decoder_platform', cbl_log_decoder_platform,
                                                property_name_check=False)

    try:
        cbl_log_decoder_build
    except NameError:
        log_info("cbl_log_decoder_build is not provided")
        persist_cluster_config_environment_prop(cluster_config, 'cbl_log_decoder_build', "", property_name_check=False)
    else:
        log_info("Running test with cbl_log_decoder_platform {}".format(cbl_log_decoder_platform))
        persist_cluster_config_environment_prop(cluster_config, 'cbl_log_decoder_platform', cbl_log_decoder_platform,
                                                property_name_check=False)

    if xattrs_enabled:
        log_info("Running test with xattrs for sync meta storage")
        persist_cluster_config_environment_prop(cluster_config, 'xattrs_enabled', True)
    else:
        log_info("Using document storage for sync meta data")
        persist_cluster_config_environment_prop(cluster_config, 'xattrs_enabled', False)

    if no_conflicts_enabled:
        log_info("Running with no conflicts")
        persist_cluster_config_environment_prop(cluster_config, 'no_conflicts_enabled', True)
    else:
        log_info("Running with allow conflicts")
        persist_cluster_config_environment_prop(cluster_config, 'no_conflicts_enabled', False)

    if use_views:
        log_info("Running SG tests using views")
        # Enable sg views in cluster configs
        persist_cluster_config_environment_prop(cluster_config, 'sg_use_views', True)
    else:
        log_info("Running tests with cbs <-> sg ssl disabled")
        # Disable sg views in cluster configs
        persist_cluster_config_environment_prop(cluster_config, 'sg_use_views', False)

    if delta_sync_enabled:
        log_info("Running with delta sync")
        persist_cluster_config_environment_prop(cluster_config, 'delta_sync_enabled', True)
    else:
        log_info("Running without delta sync")
        persist_cluster_config_environment_prop(cluster_config, 'delta_sync_enabled', False)

    if hide_product_version:
        log_info("Suppress the SGW product Version")
        persist_cluster_config_environment_prop(cluster_config, 'hide_product_version', True)
    else:
        log_info("Running without suppress SGW product Version")
        persist_cluster_config_environment_prop(cluster_config, 'hide_product_version', False)

    if enable_cbs_developer_preview:
        log_info("Enable CBS developer preview")
        persist_cluster_config_environment_prop(cluster_config, 'cbs_developer_preview', True)
    else:
        log_info("Running without CBS developer preview")
        persist_cluster_config_environment_prop(cluster_config, 'cbs_developer_preview', False)

    if cbs_ssl:
        log_info("Running tests with cbs <-> sg ssl enabled")
        # Enable ssl in cluster configs
        persist_cluster_config_environment_prop(cluster_config, 'cbs_ssl_enabled', True)
    else:
        log_info("Running tests with cbs <-> sg ssl disabled")
        # Disable ssl in cluster configs
        persist_cluster_config_environment_prop(cluster_config, 'cbs_ssl_enabled', False)

    if magma_storage_enabled:
        log_info("Running with magma storage")
        persist_cluster_config_environment_prop(cluster_config, 'magma_storage_enabled', True, False)
    else:
        log_info("Running without magma storage")
        persist_cluster_config_environment_prop(cluster_config, 'magma_storage_enabled', False, False)

    if disable_persistent_config:
        log_info(" disable persistent config")
        persist_cluster_config_environment_prop(cluster_config, 'disable_persistent_config', True)
    else:
        log_info("Running without Centralized Persistent Config")
        persist_cluster_config_environment_prop(cluster_config, 'disable_persistent_config', False)

    if enable_server_tls_skip_verify:
        log_info("Enable server tls skip verify flag")
        persist_cluster_config_environment_prop(cluster_config, 'server_tls_skip_verify', True)
    else:
        log_info("Running without server_tls_skip_verify Config")
        persist_cluster_config_environment_prop(cluster_config, 'server_tls_skip_verify', False)

    if disable_tls_server:
        log_info("Disable tls server flag")
        persist_cluster_config_environment_prop(cluster_config, 'disable_tls_server', True)
    else:
        log_info("Enable tls server flag")
        persist_cluster_config_environment_prop(cluster_config, 'disable_tls_server', False)

    if disable_admin_auth:
        log_info("Disabled Admin Auth")
        persist_cluster_config_environment_prop(cluster_config, 'disable_admin_auth', True)
    else:
        log_info("Enabled Admin Auth")
        persist_cluster_config_environment_prop(cluster_config, 'disable_admin_auth', False)

    # As cblite jobs run with on Centos platform, adding by default centos to environment config
    persist_cluster_config_environment_prop(cluster_config, 'sg_platform', "centos", False)

    # Write the number of replicas to cluster config
    persist_cluster_config_environment_prop(cluster_config, 'number_replicas', number_replicas)
    cluster_utils = ClusterKeywords(cluster_config)
    cluster_topology = cluster_utils.get_cluster_topology(cluster_config)
    cbs_url = cluster_topology['couchbase_servers'][0]
    cbs_ip = host_for_url(cbs_url)

    if sync_gateway_version < "2.0":
        pytest.skip('Does not work with sg < 2.0 , so skipping the test')

    if not skip_provisioning:
        log_info("Installing Sync Gateway + Couchbase Server + Accels ('di' only)")

        try:
            cluster_utils.provision_cluster(
                cluster_config=cluster_config,
                server_version=server_version,
                sync_gateway_version=sync_gateway_version,
                sync_gateway_config=sg_config,
                cbs_ce=cbs_ce,
                sg_ce=sg_ce,
                skip_couchbase_provision=skip_couchbase_provision
            )
        except ProvisioningError as e:
            error = str(e)
            log_info(error)
            logging_helper = Logging()
            logging_helper.fetch_and_analyze_logs(cluster_config=cluster_config, test_name=request.node.name)
            raise

    # Hit this installed running services to verify the correct versions are installed
    cluster_utils.verify_cluster_versions(
        cluster_config,
        expected_server_version=server_version,
        expected_sync_gateway_version=sync_gateway_version
    )

    need_sgw_admin_auth = (not disable_admin_auth) and sync_gateway_version >= "3.0"
    log_info("need_sgw_admin_auth setting: {}".format(need_sgw_admin_auth))

    if enable_sample_bucket and not create_db_per_suite:
        # if enable_sample_bucket and not create_db_per_test:
        raise Exception("enable_sample_bucket has to be used with create_db_per_suite")

    # Start Test server which needed for suite level set up like query tests
    if not use_local_testserver and create_db_per_suite:
        log_info("Starting TestServer...")
        testserver.stop()
        test_name_cp = test_name.replace("/", "-")
        log_filename = "{}/logs/{}-{}-{}.txt".format(RESULTS_DIR, type(testserver).__name__, test_name_cp, datetime.datetime.now())
        if device_enabled:
            testserver.start_device(log_filename)
        else:
            testserver.start(log_filename)
        time.sleep(2)

    suite_source_db = None
    suite_db = None
    suite_db_log_files = None
    suite_cbllog = FileLogging(base_url)
    if create_db_per_suite:
        if enable_file_logging and liteserv_version >= "2.5.0":
            suite_cbllog.configure(log_level="verbose", max_rotate_count=2,
                                   max_size=1000000 * 512, plain_text=True)
            suite_db_log_files = suite_cbllog.get_directory()
            log_info("Log files available at - {}".format(suite_db_log_files))
        # Create CBL database
        suite_cbl_db = create_db_per_suite
        suite_db = Database(base_url)

        log_info("Creating a Database {} at the suite setup".format(suite_cbl_db))
        if disable_encryption:
            db_config = suite_db.configure()
        else:
            db_config = suite_db.configure(password=encryption_password)
        suite_source_db = suite_db.create(suite_cbl_db, db_config)
        log_info("Getting the database name")
        db_name = suite_db.getName(suite_source_db)
        assert db_name == suite_cbl_db

    if enable_sample_bucket:
        server_url = cluster_topology["couchbase_servers"][0]
        server = CouchbaseServer(server_url)
        buckets = server.get_bucket_names()
        if enable_sample_bucket in buckets:
            log_info("Deleting existing {} bucket".format(enable_sample_bucket))
            server.delete_bucket(enable_sample_bucket)
            time.sleep(5)

        log_info("Loading sample bucket {}".format(enable_sample_bucket))
        server.load_sample_bucket(enable_sample_bucket)
        # we trying 5 times in the rbac bucket user api
        server._create_internal_rbac_bucket_user(enable_sample_bucket, cluster_config=cluster_config)

        # Restart SG after the bucket deletion
        sync_gateways = cluster_topology["sync_gateways"]
        sg_obj = SyncGateway()

        for sg in sync_gateways:
            sg_ip = host_for_url(sg["admin"])
            log_info("Restarting sync gateway {}".format(sg_ip))
            sg_obj.restart_sync_gateways(cluster_config=cluster_config, url=sg_ip)
            # Giving time to SG to load all docs into it's cache
            time.sleep(20)

        if mode == "di":
            ac_obj = SyncGateway()
            sg_accels = cluster_topology["sg_accels"]
            for ac in sg_accels:
                ac_ip = host_for_url(ac)
                log_info("Restarting sg accel {}".format(ac_ip))
                ac_obj.restart_sync_gateways(cluster_config=cluster_config, url=ac_ip)
                time.sleep(5)

        sdk_client = get_cluster('couchbase://{}'.format(cbs_ip), enable_sample_bucket)
        n1ql_query = 'create primary index on {}'.format(enable_sample_bucket)
        log_info(n1ql_query)
        sdk_client.query(n1ql_query)

        # Start continuous replication
        repl_obj = Replication(base_url)
        auth_obj = BasicAuthenticator(base_url)
        authenticator = auth_obj.create("travel-sample", "password")
        repl_config = repl_obj.configure(source_db=suite_source_db,
                                         target_url=target_admin_url,
                                         replication_type="PUSH_AND_PULL",
                                         continuous=True,
                                         replicator_authenticator=authenticator)
        repl = repl_obj.create(repl_config)
        repl_obj.start(repl)
        # max_times is 3000 to give more time to replicate travel sample as it is huge
        repl_obj.wait_until_replicator_idle(repl, max_times=3000)
        log_info("Stopping replication")
        repl_obj.stop(repl)
    if prometheus_enable:
        if not prometheus.is_prometheus_installed:
            prometheus.install_prometheus
        prometheus.start_prometheus(sg_ip, sg_ssl, need_sgw_admin_auth)

    yield {
        "cluster_config": cluster_config,
        "mode": mode,
        "xattrs_enabled": xattrs_enabled,
        "liteserv_platform": liteserv_platform,
        "cluster_topology": cluster_topology,
        "liteserv_version": liteserv_version,
        "liteserv_host": liteserv_host,
        "liteserv_port": liteserv_port,
        "target_url": target_url,
        "sg_ip": sg_ip,
        "sg_db": sg_db,
        "no_conflicts_enabled": no_conflicts_enabled,
        "sync_gateway_version": sync_gateway_version,
        "disable_tls_server": disable_tls_server,
        "target_admin_url": target_admin_url,
        "base_url": base_url,
        "enable_sample_bucket": enable_sample_bucket,
        "create_db_per_test": create_db_per_test,
        "suite_source_db": suite_source_db,
        "suite_cbl_db": suite_cbl_db,
        "suite_db": suite_db,
        "sg_config": sg_config,
        "testserver": testserver,
        "device_enabled": device_enabled,
        "flush_memory_per_test": flush_memory_per_test,
        "delta_sync_enabled": delta_sync_enabled,
        "enable_file_logging": enable_file_logging,
        "cbl_log_decoder_platform": cbl_log_decoder_platform,
        "cbl_log_decoder_build": cbl_log_decoder_build,
        "suite_db_log_files": suite_db_log_files,
        "disable_encryption": disable_encryption,
        "encryption_password": encryption_password,
        "cbs_ce": cbs_ce,
        "sg_ce": sg_ce,
        "cbl_ce": cbl_ce,
        "prometheus_enable": prometheus_enable,
        "ssl_enabled": cbs_ssl,
        "need_sgw_admin_auth": need_sgw_admin_auth,
        "scope_name": scope_name,
        "collection_name": collection_name
    }

    if request.node.testsfailed != 0 and enable_file_logging and create_db_per_suite is not None:
        tests_list = request.node.items
        failed_test_list = []
        for test in tests_list:
            if test.rep_call.failed:
                failed_test_list.append(test.rep_call.nodeid)
        zip_data = suite_cbllog.get_logs_in_zip()
        suite_log_zip_file = "Suite_test_log.zip"

        if os.path.exists(suite_log_zip_file):
            log_info("Log file for failed Suite tests is: {}".format(suite_log_zip_file))
            target_zip = zipfile.ZipFile(suite_log_zip_file, 'w')
            with zipfile.ZipFile(io.BytesIO(zip_data)) as thezip:
                for zipinfo in thezip.infolist():
                    target_zip.writestr(zipinfo.filename, thezip.read(zipinfo.filename))
            target_zip.close()
        else:
            log_info("Cannot find log file for failed Suite tests")

    if create_db_per_suite:
        # Delete CBL database
        log_info("Deleting the database {} at the suite teardown".format(create_db_per_suite))
        time.sleep(2)
        suite_db.deleteDB(suite_source_db)
        time.sleep(1)
    if create_db_per_suite:
        # Flush all the memory contents on the server app
        log_info("Flushing server memory")
        utils_obj = Utils(base_url)
        utils_obj.flushMemory()
        if not use_local_testserver:
            log_info("Stopping the test server per suite")
            testserver.stop()
    # Delete png files under resources/data
    clear_resources_pngs()
    if prometheus_enable:
        prometheus.stop_prometheus(sg_ip, sg_ssl, need_sgw_admin_auth)


@pytest.fixture(scope="function")
def params_from_base_test_setup(request, params_from_base_suite_setup):
    cluster_config = params_from_base_suite_setup["cluster_config"]
    xattrs_enabled = params_from_base_suite_setup["xattrs_enabled"]
    liteserv_host = params_from_base_suite_setup["liteserv_host"]
    liteserv_port = params_from_base_suite_setup["liteserv_port"]
    create_db_per_test = params_from_base_suite_setup["create_db_per_test"]
    no_conflicts_enabled = params_from_base_suite_setup["no_conflicts_enabled"]
    target_admin_url = params_from_base_suite_setup["target_admin_url"]
    suite_source_db = params_from_base_suite_setup["suite_source_db"]
    suite_cbl_db = params_from_base_suite_setup["suite_cbl_db"]
    test_name = request.node.name
    cluster_topology = params_from_base_suite_setup["cluster_topology"]
    mode = params_from_base_suite_setup["mode"]
    target_url = params_from_base_suite_setup["target_url"]
    base_url = params_from_base_suite_setup["base_url"]
    sg_ip = params_from_base_suite_setup["sg_ip"]
    sg_db = params_from_base_suite_setup["sg_db"]
    sync_gateway_version = params_from_base_suite_setup["sync_gateway_version"]
    disable_tls_server = params_from_base_suite_setup["disable_tls_server"]
    sg_config = params_from_base_suite_setup["sg_config"]
    liteserv_platform = params_from_base_suite_setup["liteserv_platform"]
    testserver = params_from_base_suite_setup["testserver"]
    device_enabled = params_from_base_suite_setup["device_enabled"]
    enable_sample_bucket = params_from_base_suite_setup["enable_sample_bucket"]
    liteserv_version = params_from_base_suite_setup["liteserv_version"]
    delta_sync_enabled = params_from_base_suite_setup["delta_sync_enabled"]
    enable_file_logging = params_from_base_suite_setup["enable_file_logging"]
    cbl_log_decoder_platform = params_from_base_suite_setup["cbl_log_decoder_platform"]
    cbl_log_decoder_build = params_from_base_suite_setup["cbl_log_decoder_build"]
    encryption_password = params_from_base_suite_setup["encryption_password"]
    disable_encryption = params_from_base_suite_setup["disable_encryption"]
    use_local_testserver = request.config.getoption("--use-local-testserver")
    cbl_ce = params_from_base_suite_setup["cbl_ce"]
    cbs_ce = params_from_base_suite_setup["cbs_ce"]
    sg_ce = params_from_base_suite_setup["sg_ce"]
    prometheus_enable = request.config.getoption("--prometheus-enable")
    cbs_ssl = params_from_base_suite_setup["ssl_enabled"]
    need_sgw_admin_auth = params_from_base_suite_setup["need_sgw_admin_auth"]
    scope_name = params_from_base_suite_setup["scope_name"]
    collection_name = params_from_base_suite_setup["collection_name"]

    source_db = None
    test_name_cp = test_name.replace("/", "-")
    log_filename = "{}/logs/{}-{}-{}.txt".format(RESULTS_DIR, type(testserver).__name__,
                                                 test_name_cp,
                                                 datetime.datetime.now())

    if not use_local_testserver and create_db_per_test:
        log_info("Starting TestServer...")
        testserver.stop()
        if device_enabled:
            testserver.start_device(log_filename)
        else:
            testserver.start(log_filename)
        time.sleep(2)

    cluster_helper = ClusterKeywords(cluster_config)
    cluster_hosts = cluster_helper.get_cluster_topology(cluster_config=cluster_config)
    sg_url = cluster_hosts["sync_gateways"][0]["public"]
    sg_admin_url = cluster_hosts["sync_gateways"][0]["admin"]

    log_info("Running test '{}'".format(test_name))
    log_info("cluster_config: {}".format(cluster_config))
    log_info("cluster_topology: {}".format(cluster_topology))
    log_info("mode: {}".format(mode))
    log_info("xattrs_enabled: {}".format(xattrs_enabled))
    db_config = None

    db = None
    cbl_db = None
    test_db_log_file = None
    path = None
    test_cbllog = FileLogging(base_url)
    if create_db_per_test:
        if enable_file_logging and liteserv_version >= "2.5.0":
            test_cbllog.configure(log_level="verbose", max_rotate_count=2,
                                  max_size=100000 * 512, plain_text=True)
            test_db_log_file = test_cbllog.get_directory()
            log_info("Log files available at - {}".format(test_db_log_file))
        cbl_db = create_db_per_test + str(time.time())
        # Create CBL database
        db = Database(base_url)

        log_info("Creating a Database {} at test setup".format(cbl_db))
        if disable_encryption:
            db_config = db.configure()
        else:
            db_config = db.configure(password=encryption_password)
        source_db = db.create(cbl_db, db_config)
        log_info("Getting the database name")
        db_name = db.getName(source_db)
        assert db_name == cbl_db
        path = db.getPath(source_db).rstrip("/\\")
        if '\\' in path:
            path = '\\'.join(path.split('\\')[:-1])
        else:
            path = '/'.join(path.split('/')[:-1])

    # This dictionary is passed to each test
    yield {
        "cluster_config": cluster_config,
        "cluster_topology": cluster_topology,
        "mode": mode,
        "sg_url": sg_url,
        "sg_admin_url": sg_admin_url,
        "xattrs_enabled": xattrs_enabled,
        "liteserv_host": liteserv_host,
        "liteserv_port": liteserv_port,
        "liteserv_platform": liteserv_platform,
        "target_url": target_url,
        "target_admin_url": target_admin_url,
        "sg_ip": sg_ip,
        "sg_db": sg_db,
        "no_conflicts_enabled": no_conflicts_enabled,
        "sync_gateway_version": sync_gateway_version,
        "disable_tls_server": disable_tls_server,
        "source_db": source_db,
        "cbl_db": cbl_db,
        "suite_source_db": suite_source_db,
        "suite_cbl_db": suite_cbl_db,
        "base_url": base_url,
        "sg_config": sg_config,
        "db": db,
        "device_enabled": device_enabled,
        "testserver": testserver,
        "db_config": db_config,
        "enable_sample_bucket": enable_sample_bucket,
        "log_filename": log_filename,
        "test_db_log_file": test_db_log_file,
        "liteserv_version": liteserv_version,
        "delta_sync_enabled": delta_sync_enabled,
        "cbl_log_decoder_platform": cbl_log_decoder_platform,
        "cbl_log_decoder_build": cbl_log_decoder_build,
        "disable_encryption": disable_encryption,
        "encryption_password": encryption_password,
        "enable_file_logging": enable_file_logging,
        "test_cbllog": test_cbllog,
        "cbs_ce": cbs_ce,
        "sg_ce": sg_ce,
        "cbl_ce": cbl_ce,
        "prometheus_enable": prometheus_enable,
        "ssl_enabled": cbs_ssl,
        "need_sgw_admin_auth": need_sgw_admin_auth,
        "scope_name": scope_name,
        "collection_name": collection_name
    }

    if request.node.rep_call.failed and enable_file_logging and create_db_per_test is not None:
        test_id = request.node.nodeid
        log_info("\n Collecting logs for failed test: {}".format(test_id))
        zip_data = test_cbllog.get_logs_in_zip()
        log_directory = "results/logs"
        if not os.path.exists(log_directory):
            os.mkdir(log_directory)
        test_log_zip_file = "{}.zip".format(test_id.split("::")[-1])
        test_log = os.path.join(log_directory, test_log_zip_file)
        if not os.path.exists(test_log):
            target_zip = zipfile.ZipFile(test_log, 'w')
            with zipfile.ZipFile(io.BytesIO(zip_data)) as thezip:
                for zipinfo in thezip.infolist():
                    target_zip.writestr(zipinfo.filename, thezip.read(zipinfo.filename))
            target_zip.close()

    log_info("Tearing down test")
    if create_db_per_test:
        # Delete CBL database
        log_info("Deleting the database {} at test teardown".format(create_db_per_test))
        time.sleep(1)
        try:
            if db.exists(cbl_db, path):
                db.deleteDB(source_db)
                log_info("not deleting")
            log_info("Flushing server memory")
            utils_obj = Utils(base_url)
            utils_obj.flushMemory()
            if not use_local_testserver:
                log_info("Stopping the test server per test")
                testserver.stop()
        except Exception as err:
            log_info("Exception occurred: {}".format(err))


@pytest.fixture(scope="class")
def class_init(request, params_from_base_suite_setup):
    base_url = params_from_base_suite_setup["base_url"]
    liteserv_platform = params_from_base_suite_setup["liteserv_platform"]
    liteserv_version = params_from_base_suite_setup["liteserv_version"]
    disable_encryption = params_from_base_suite_setup["disable_encryption"]
    encryption_password = params_from_base_suite_setup["encryption_password"]
    db_obj = Database(base_url)
    scope_obj = Scope(base_url)
    collection_obj = Collection(base_url)
    doc_obj = Document(base_url)
    datatype = DataTypeInitiator(base_url)
    repl_obj = Replication(base_url)
    array_obj = Array(base_url)
    dict_obj = Dictionary(base_url)
    repl_config_obj = ReplicatorConfiguration(base_url)
    scope_obj = Scope(base_url)
    collection_obj = Collection(base_url)
    base_auth_obj = BasicAuthenticator(base_url)
    session_auth_obj = SessionAuthenticator(base_url)
    sg_client = MobileRestClient()

    if disable_encryption:
        db_config = db_obj.configure()
    else:
        db_config = db_obj.configure(password=encryption_password)
    db = db_obj.create("cbl-init-db", db_config)

    request.cls.db_obj = db_obj
    request.cls.collection_obj = collection_obj
    request.cls.doc_obj = doc_obj
    request.cls.scope_obj = scope_obj
    request.cls.dict_obj = dict_obj
    request.cls.datatype = datatype
    request.cls.collection_obj = collection_obj
    request.cls.scope_obj = scope_obj
    request.cls.repl_obj = repl_obj
    request.cls.repl_config_obj = repl_config_obj
    request.cls.array_obj = array_obj
    request.cls.dict_obj = dict_obj
    request.cls.array_obj = array_obj
    request.cls.datatype = datatype
    request.cls.repl_obj = repl_obj
    request.cls.base_auth_obj = base_auth_obj
    request.cls.session_auth_obj = session_auth_obj
    request.cls.sg_client = sg_client
    request.cls.db_obj = db_obj
    request.cls.db = db
    request.cls.liteserv_platform = liteserv_platform
    request.cls.liteserv_version = liteserv_version

    yield
    db_obj.deleteDB(db)


@pytest.fixture(scope="function")
def setup_customized_teardown_test(request, params_from_base_test_setup):
    cbl_db_name1 = "cbl_db1" + str(time.time())
    cbl_db_name2 = "cbl_db2" + str(time.time())
    cbl_db_name3 = "cbl_db3" + str(time.time())
    base_url = params_from_base_test_setup["base_url"]
    disable_encryption = params_from_base_test_setup["disable_encryption"]
    encryption_password = params_from_base_test_setup["encryption_password"]
    db = Database(base_url)
    if disable_encryption:
        db_config = db.configure()
    else:
        db_config = db.configure(password=encryption_password)
    cbl_db1 = db.create(cbl_db_name1, db_config)
    cbl_db2 = db.create(cbl_db_name2, db_config)
    cbl_db3 = db.create(cbl_db_name3, db_config)
    log_info("setting up all 3 dbs")

    yield{
        "db": db,
        "cbl_db_name1": cbl_db_name1,
        "cbl_db_name2": cbl_db_name2,
        "cbl_db_name3": cbl_db_name3,
        "cbl_db1": cbl_db1,
        "cbl_db2": cbl_db2,
        "cbl_db3": cbl_db3,
    }
    log_info("Tearing down test")
    db.deleteDB(cbl_db1)
    db.deleteDB(cbl_db2)
    db.deleteDB(cbl_db3)
