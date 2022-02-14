import pytest
import time
import json

from keywords.utils import log_info
from libraries.testkit.cluster import Cluster
from keywords.SyncGateway import sync_gateway_config_path_for_mode, SyncGateway, load_sync_gateway_config
# from keywords.utils import host_for_url, deep_dict_compare
# from couchbase.bucket import Bucket
from keywords.MobileRestClient import MobileRestClient
from keywords.ClusterKeywords import ClusterKeywords
# from libraries.testkit import cluster
# from concurrent.futures import ThreadPoolExecutor
# from libraries.testkit.prometheus import verify_stat_on_prometheus
# from libraries.testkit.syncgateway import start_sgbinary, get_buckets_from_sync_gateway_config
# from libraries.testkit.syncgateway import start_sgbinary
from utilities.cluster_config_utils import persist_cluster_config_environment_prop
from libraries.testkit.syncgateway import construct_dbconfig_json
# from CBLClient.Replication import Replication
# from CBLClient.Authenticator import Authenticator
from utilities.cluster_config_utils import is_centralized_persistent_config_disabled, copy_to_temp_conf
# from keywords.remoteexecutor import RemoteExecutor
from utilities.cluster_config_utils import copy_sgconf_to_temp, replace_string_on_sgw_config
from requests.exceptions import HTTPError


@pytest.mark.syncgateway
def test_default_config_values(params_from_base_test_setup):
    """
    @summary :
    https://docs.google.com/spreadsheets/d/19kJQ4_g6RroaoG2YYe0X11d9pU0xam-lb-n23aPLhO4/edit#gid=0
    Covered #30, #7
    "1. Set up sgw node in the SGW cluster
    2. Have default value of default_persistent_config value on SGW nodes.
    3. Have min bootstrap configuration without static system config with differrent config
    4. Verify SGW node connect to each bucket and each one has differrnent configure
    5. Verify _config rest end point and validate that static system config had default value
    6. Now have bootstrap and static config and verify default values of dynamic config
    """

    # sg_db = 'db'
    sg_conf_name = "sync_gateway_default"

    cluster_conf = params_from_base_test_setup['cluster_config']
    sync_gateway_version = params_from_base_test_setup['sync_gateway_version']
    mode = params_from_base_test_setup['mode']
    ssl_enabled = params_from_base_test_setup['ssl_enabled']

    # 1. Have prelithium config
    # 2. Have configs required fo database on prelithium config
    if sync_gateway_version < "3.0.0" and not is_centralized_persistent_config_disabled(cluster_conf):
        pytest.skip('This test can run with sgw version 3.0 and above')
    # 1. Have 3 SGW nodes: 1 node as pre-lithium and 2 nodes on lithium
    sg_conf = sync_gateway_config_path_for_mode(sg_conf_name, mode)

    cluster_util = ClusterKeywords(cluster_conf)
    topology = cluster_util.get_cluster_topology(cluster_conf)
    # sync_gateways = topology["sync_gateways"]

    # 3. Have min bootstrap configuration without static system config with differrent config
    cbs_cluster = Cluster(config=cluster_conf)
    cbs_cluster.reset(sg_config_path=sg_conf)
    debug_dict = {"enabled": True, "rotation": {}}
    sg1 = cbs_cluster.sync_gateways[0]
    cbs_url = topology["couchbase_servers"][0]
    sg1_config = sg1.admin.get_config()
    assert not sg1_config["logging"]["console"]["rotation"], "logging did not get reset"
    assert not sg1_config["logging"]["error"]["rotation"], "logging did not get reset"
    assert not sg1_config["logging"]["warn"]["rotation"], "logging did not get reset"
    assert not sg1_config["logging"]["info"]["rotation"], "logging did not get reset"
    assert sg1_config["logging"]["debug"] == debug_dict, "logging did not get reset"
    assert not sg1_config["logging"]["trace"]["rotation"], "logging did not get reset"
    assert not sg1_config["logging"]["stats"]["rotation"], "logging did not get reset"

    assert sg1_config["api"]["public_interface"] == ":4984", "public interface did not match with sgw config"
    assert sg1_config["api"]["admin_interface"] == "0.0.0.0:4985", "admin interface did not match with sgw config"
    assert sg1_config["api"]["metrics_interface"] == ":4986", "metrics interface did not match with sgw config"
    assert not sg1_config["api"]["admin_interface_authentication"], "admin_interface_authentication did not match with sgw config"
    assert not sg1_config["api"]["metrics_interface_authentication"], "metrics_interface_authentication did not match with sgw config"
    assert sg1_config["api"]["https"] == {}, "https with default value is not set"
    assert sg1_config["api"]["cors"] == {}, "cors with default value is not set"

    # We want to compare IP addresses first - since url's are in the format
    # <protocol>://<IP>:<port>, splitting the strings by colon gives us just the IP addresses
    sg1_config_url = sg1_config["bootstrap"]["server"]
    assert sg1_config_url.split(":")[1] == cbs_url.split(":")[1], "server IP addresses did not match"

    # If SSL is enabled, we want to see if both URLs are using secure protocols (https and couchbases z)
    # We can use the same trick as above and ensure that both protocols end in s (for secure)
    if ssl_enabled:
        assert sg1_config_url.split(":")[0][-1] == cbs_url.split(":")[0][-1], "server URLs were not both using secure protocol"
    assert sg1_config["bootstrap"]["username"] == "bucket-admin", "username did not match"
    assert sg1_config["bootstrap"]["server_tls_skip_verify"] == True, "server_tls_skip_verify did not match"


@pytest.mark.syncgateway
@pytest.mark.parametrize("sg_conf_name", [
    ("sync_gateway_default_invalid_bootstrap"),
    ("sync_gateway_invalid_api")
])
def test_invalid_configs(params_from_base_test_setup, sg_conf_name):
    """
    @summary :
    https://docs.google.com/spreadsheets/d/19kJQ4_g6RroaoG2YYe0X11d9pU0xam-lb-n23aPLhO4/edit#gid=0
    Covered #31
    ""1. Set up SGW node with bootstrap config and add few static config under bootstrap config
    2. Add bootstrap config under static config
    3. Verify SGW fails to restart"
    """

    # sg_db = 'db'
    # sg_conf_name = "sync_gateway_default_invalid_bootstrap"
    sg_obj = SyncGateway()

    cluster_conf = params_from_base_test_setup['cluster_config']
    sync_gateway_version = params_from_base_test_setup['sync_gateway_version']
    # sync_gateway_upgraded_version = params_from_base_test_setup['sync_gateway_upgraded_version']
    mode = params_from_base_test_setup['mode']
    """ sg_platform = params_from_base_test_setup['sg_platform']
    base_url = params_from_base_test_setup["base_url"]
    cbl_db = params_from_base_test_setup["source_db"]
    username = "autotest"
    password = "password"
    sg_channels = ["non_cpc"] """

    # 1. Have prelithium config
    # 2. Have configs required fo database on prelithium config
    temp_cluster_config = copy_to_temp_conf(cluster_conf, mode)
    # persist_cluster_config_environment_prop(temp_cluster_config, 'disable_persistent_config', False)
    if sync_gateway_version < "3.0.0" and not is_centralized_persistent_config_disabled(cluster_conf):
        pytest.skip('This test can run with sgw version 3.0 and with persistent config off')

    sg_conf = sync_gateway_config_path_for_mode(sg_conf_name, mode, cpc=True)
    non_cpc_sgconf_name = "sync_gateway_default"
    non_cpc_sg_conf = sync_gateway_config_path_for_mode(non_cpc_sgconf_name, mode)

    # sg_client = MobileRestClient()
    sg_obj = SyncGateway()
    cluster_util = ClusterKeywords(cluster_conf)
    topology = cluster_util.get_cluster_topology(cluster_conf)
    # sync_gateways = topology["sync_gateways"]
    sg_one_url = topology["sync_gateways"][0]["public"]

    # 3. Have min bootstrap configuration without static system config with differrent config
    if sg_conf_name == "sync_gateway_default":
        sgw_config = load_sync_gateway_config(sg_conf, topology["couchbase_servers"][0], cluster_conf)
        # Create temp config file in the same folder as sg_conf
        temp_conf = "/".join(sg_conf.split('/')[:-2]) + '/temp_conf.json'
        del sgw_config["bootstrap"]
        log_info("TEMP_CONF: {}".format(temp_conf))

        with open(temp_conf, 'w') as fp:
            json.dump(sgw_config, fp, indent=4)
            print("todo")
    cbs_cluster = Cluster(config=cluster_conf)
    try:
        sg_obj.start_sync_gateways(cluster_config=cluster_conf, url=sg_one_url, config=sg_conf, use_config=non_cpc_sg_conf)
        assert False, "SGW did not fail to start with bootstrap config under api config"
    except Exception as ex:
        print("SGW failed to start with bootstrap config", str(ex))


@pytest.mark.syncgateway
def test_sgw_command_line(params_from_base_test_setup):
    """
    @summary :
    https://docs.google.com/spreadsheets/d/19kJQ4_g6RroaoG2YYe0X11d9pU0xam-lb-n23aPLhO4/edit#gid=0
    Covered #33
    1. Set up sgw node in the SGW cluster
    2. Have default_persistent_config value on SGW nodes.
    3. Have min bootstrap configuration
    4. Start  sgw node by passing command line params by passing server, bucket info
    5. Verify SGW node connect to each bucket
    5. Verify _config rest end point and validate that params passed for bootstrap, static values are matching with command line params"
    """

    # sg_db = 'db'
    sg_conf_name = "sync_gateway_default_bootstrap"

    cluster_conf = params_from_base_test_setup['cluster_config']
    sync_gateway_version = params_from_base_test_setup['sync_gateway_version']
    mode = params_from_base_test_setup['mode']
    # sg_platform = params_from_base_test_setup['sg_platform']
    """ username = "autotest"
    password = "password"
    sg_channels = ["non_cpc"] """

    temp_cluster_config = copy_to_temp_conf(cluster_conf, mode)
    # 2. Have default_persistent_config value on SGW nodes
    persist_cluster_config_environment_prop(temp_cluster_config, 'disable_persistent_config', False)

    # 1. Set up sgw node in the SGW cluster
    if sync_gateway_version < "3.0.0" or not is_centralized_persistent_config_disabled(cluster_conf):
        pytest.skip('This test can run with sgw version 3.0 and above')
    sg_conf = sync_gateway_config_path_for_mode(sg_conf_name, mode, cpc=True)

    # sg_client = MobileRestClient()
    sg_obj = SyncGateway()
    # cluster_util = ClusterKeywords(temp_cluster_config)
    # topology = cluster_util.get_cluster_topology(temp_cluster_config)
    # sync_gateways = topology["sync_gateways"]
    # sg_one_url = topology["sync_gateways"][0]["public"]

    # 3. Have min bootstrap configuration
    cbs_cluster = Cluster(config=temp_cluster_config)
    cbs_cluster.reset(sg_config_path=sg_conf)

    # 4.Start sgw node by passing command line params by passing server, bucket info
    sg1 = cbs_cluster.sync_gateways[0]
    print("stopping explicetely ")
    sg_obj.stop_sync_gateways(temp_cluster_config)
    sg_obj.redeploy_sync_gateway_config(temp_cluster_config, sg_conf, url=None, sync_gateway_version=sync_gateway_version, enable_import=True, deploy_only=True)
    """ adminInterface = "5985"
    interface = "5984"
    cacertpath = ""
    certpath = ""
    configServer = ""
    dbname = ""
    defaultLogFilePath = "/tmp/sg_logs"
    disable_persistent_config = False
    keypath = ""
    log = ""
    logFilePath = ""
    profileInterface = ""
    url = ""
    std_output = start_sgbinary(sg1, sg_platform, adminInterface=adminInterface, interface=interface, defaultLogFilePath=defaultLogFilePath, disable_persistent_config=disable_persistent_config)
    """
    count = 0
    retry = 5
    errors = 1
    while count < retry and errors != 0:
        errors = cbs_cluster.verify_alive()
        time.sleep(2)
        count += 1

    sg1_config = sg1.admin.get_config()
    assert sg1_config["logging"] is None, "logging did not get reset"
    # 4. Verify default values of static config
    # 4. Add dynamic config like log_file_path or redaction_level on sgw config


@pytest.mark.syncgateway
def test_invalid_database_credentials(params_from_base_test_setup):
    """
    @summary :
    Test cases link on google drive : https://docs.google.com/spreadsheets/d/19kJQ4_g6RroaoG2YYe0X11d9pU0xam-lb-n23aPLhO4/edit#gid=0
    "1. Have bootstrap config on sgw config which has server, username, password of the bucket
    2. Start SGW
    3. Add database on sgw via rest end point with invalid credentials of the bucket on the response from rest apoi
    """

    sg_db = 'sg_db'
    sg_db2 = 'sg_db2'
    # sg_db3 = 'sg_db3'
    sg_conf_name = "sync_gateway_default"
    # sg_obj = SyncGateway()

    cluster_conf = params_from_base_test_setup['cluster_config']
    mode = params_from_base_test_setup['mode']
    sg_platform = params_from_base_test_setup['sg_platform']

    # 1. Have bootstrap config on sgw config which has server, username, password of the bucket
    # TODO: remove below 3 lines after persistent config is default to false
    temp_cluster_config = copy_to_temp_conf(cluster_conf, mode)
    # persist_cluster_config_environment_prop(temp_cluster_config, 'disable_persistent_config', False)
    cluster_conf = temp_cluster_config
    sg_config = sync_gateway_config_path_for_mode(sg_conf_name, mode, cpc=True)

    sg_client = MobileRestClient()
    """ cluster_utils = ClusterKeywords(cluster_conf)
    cluster_topology = cluster_utils.get_cluster_topology(cluster_conf)
    cbs_url = cluster_topology['couchbase_servers'][0]
    sg_one_url = cluster_topology["sync_gateways"][0]["public"]
    sg_two_url = cluster_topology["sync_gateways"][1]["public"] """
    sg_db1_username = "autotest"
    sg_password = "password"
    sg_channels = ["cpc_testing"]
    # sg_username2 = "autotest2"
    # sg_channels2 = ["cpc_testing2"]
    cbs_cluster = Cluster(config=cluster_conf)
    bucket_list = ["data-bucket"]
    cbs_cluster.reset(sg_config_path=sg_config, bucket_list=bucket_list, use_config=True)
    time.sleep(15)
    sg1 = cbs_cluster.sync_gateways[0]
    sg_db1 = "db"

    # 3. Add database config on node1 with sg_db1
    # revs_limit = 20
    # persist_cluster_config_environment_prop(cluster_conf, 'revs_limit', revs_limit, property_name_check=False)
    db_config_file = "sync_gateway_default_db"
    dbconfig = construct_dbconfig_json(db_config_file, cluster_conf, sg_platform, sg_conf_name)
    print("db config---sridevi", dbconfig)
    dbconfig  = dbconfig.replace(bucket_list[0], "invalid-bucket-name")
    print("invalid db config---sridevi", dbconfig)
    try:
        sg1.admin.create_db(sg_db1, dbconfig)
        assert False, "create db rest call did not fail with invalid bucket name"
    except HTTPError as e:
        log_info("Ignoring... caught expected Http error ")


@pytest.mark.syncgateway
@pytest.mark.oscertify
@pytest.mark.parametrize("group_type", [
    ("default"),
    ("named")
])
def test_default_named_group(params_from_base_test_setup, group_type):
    """
    @summary :
    Test cases link on google drive : https://docs.google.com/spreadsheets/d/19kJQ4_g6RroaoG2YYe0X11d9pU0xam-lb-n23aPLhO4/edit#gid=0
    1. Setup SGw node with default group on sgw config
    2. Start sync gateway
    3. Verify SGW starts successfully with default group id on CE and EE
    4. Test custom group id on CE and verify SGW starts to fail
    """

    # sg_db = 'db'
    sg_cpc_conf_name = "sync_gateway_cpc_custom_group"
    sg_conf_name = "sync_gateway_default"

    cluster_conf = params_from_base_test_setup['cluster_config']
    sync_gateway_version = params_from_base_test_setup['sync_gateway_version']
    mode = params_from_base_test_setup['mode']
    disable_persistent_config = params_from_base_test_setup['disable_persistent_config']
    sg_ce = params_from_base_test_setup['sg_ce']

    if sync_gateway_version < "3.0.0" and not disable_persistent_config:
        pytest.skip('This test can run with sgw version 3.0 and above')
    sg_conf = sync_gateway_config_path_for_mode(sg_conf_name, mode)
    cpc_sg_conf = sync_gateway_config_path_for_mode(sg_cpc_conf_name, mode, cpc=True)
    sg_obj = SyncGateway()

    # 1. Setup SGw node with default group on sgw config
    # 2. Start sync gateway
    if group_type == "default":
        replaced_group = ""
    else:
        replaced_group = '"group_id": "replaced_named_group",'
    str = '{{ groupid }}'
    temp_sg_config, _ = copy_sgconf_to_temp(cpc_sg_conf, mode)
    temp_sg_config = replace_string_on_sgw_config(temp_sg_config, str, replaced_group)
    cbs_cluster = Cluster(config=cluster_conf)
    sg1 = cbs_cluster.sync_gateways[0]
    sg_obj.stop_sync_gateways(cluster_config=cluster_conf, url=sg1.url)
    # 3. Verify SGW starts successfully with default group id on CE and EE
    # 4. Test custom group id on CE and verify SGW starts to fail
    try:
        sg_obj.start_sync_gateways(cluster_config=cluster_conf, url=sg1.url, config=temp_sg_config, use_config=sg_conf)
    except Exception as ex:
        print("Exception caught is ", str(ex))
        if group_type == "named" and not sg_ce:
            assert False, "Sync gateway failed to start with custom group id"
        if group_type == "default":
            assert False, "Sync gateway failed to start with default group id "