-- Cloudflare HTTP request Logpush -> ADS Iceberg sink. Three fact tables joined on ray_id plus one reference table:
-- cf_request_log (33 columns), cf_request_security (29), cf_request_detail (44), ref_edge_colo (3). One row per request.
-- Written in the dialect of the SDK's own Iceberg example (ads-dataflow-sdk, branch csv-iceberg-example,
-- examples/pipeline-py-csv-iceberg/csv_iceberg/sink.ddl): VARCHAR, BIGINT, BOOLEAN, TIMESTAMPTZ, and
-- PARTITIONED BY (day(col)) after the column list. No USING clause, no TBLPROPERTIES, no keys or indexes.
--
-- Type mapping from the Postgres cf_request_log
--   text        -> VARCHAR
--   bigint      -> BIGINT
--   integer     -> BIGINT        (the example DDLs only use BIGINT for whole numbers; INT is not shown anywhere)
--   timestamptz -> TIMESTAMPTZ
--   inet        -> VARCHAR       (no IP type; an empty OriginIP can be NULL or '')
--
-- Rules the SDK example sets (see its README)
--   * The table name is unqualified and must equal `table = "..."` in the entry class (pipeline.py).
--   * The runtime runs this DDL only when the table is absent; a redeploy on the same table appends every row again,
--     so use a new table name for a clean run (cf_request_log_v1, _v2, ...).
--   * Rows that cannot be written land in <table>_failed with a reason.
--   * No primary key: remove duplicates by ray_id in the entry (the example keeps one row per id within a unit)
--     or at query time (ROW_NUMBER over ray_id).
--   * client_ip is PII: hash or mask it in the entry before it lands.
--   * Partitioned by day: day() is the form the example uses. hour() is not shown in the SDK, so confirm it with ADS
--     before using it for the hourly rollups; day plus a filter on the timestamp already prunes well.

CREATE TABLE IF NOT EXISTS cf_request_log (
    ray_id VARCHAR,                       -- RayID
    edge_start_timestamp TIMESTAMPTZ,     -- EdgeStartTimestamp
    edge_end_timestamp TIMESTAMPTZ,       -- EdgeEndTimestamp
    zone_name VARCHAR,                    -- ZoneName
    client_request_host VARCHAR,          -- ClientRequestHost
    client_request_method VARCHAR,        -- ClientRequestMethod
    client_request_path VARCHAR,          -- ClientRequestPath
    client_request_uri VARCHAR,           -- ClientRequestURI
    client_request_protocol VARCHAR,      -- ClientRequestProtocol
    client_request_referer VARCHAR,       -- ClientRequestReferer
    client_request_user_agent VARCHAR,    -- ClientRequestUserAgent
    client_request_bytes BIGINT,          -- ClientRequestBytes
    edge_response_status BIGINT,          -- EdgeResponseStatus
    edge_response_bytes BIGINT,           -- EdgeResponseBytes
    edge_response_body_bytes BIGINT,      -- EdgeResponseBodyBytes
    edge_response_content_type VARCHAR,   -- EdgeResponseContentType
    origin_response_status BIGINT,        -- OriginResponseStatus
    security_action VARCHAR,              -- SecurityAction
    edge_time_to_first_byte_ms BIGINT,    -- EdgeTimeToFirstByteMs
    origin_response_duration_ms BIGINT,   -- OriginResponseDurationMs
    client_tcp_rtt_ms BIGINT,             -- ClientTCPRTTMs
    cache_cache_status VARCHAR,           -- CacheCacheStatus
    cache_response_status BIGINT,         -- CacheResponseStatus
    client_asn BIGINT,                    -- ClientASN
    client_country VARCHAR,               -- ClientCountry
    client_region_code VARCHAR,           -- ClientRegionCode
    client_device_type VARCHAR,           -- ClientDeviceType
    client_ip VARCHAR,                    -- ClientIP (PII: hash or mask)
    client_ssl_protocol VARCHAR,          -- ClientSSLProtocol
    ja3_hash VARCHAR,                     -- JA3Hash
    edge_colo_id BIGINT,                  -- EdgeColoID
    edge_colo_code VARCHAR,               -- EdgeColoCode
    origin_ip VARCHAR                     -- OriginIP
) PARTITIONED BY (day(edge_start_timestamp));

-- ---------------------------------------------------------------------------------------------------------------
-- The other tables of the Postgres design (cloudflare_logs_postgres.sql), same rules and same type mapping, plus:
--   boolean          -> BOOLEAN      (the SDK example uses it)
--   double precision -> DOUBLE
--   jsonb            -> VARCHAR      (arrays and objects as JSON text; json.dumps in the entry. Cookies and the header
--                                     objects may hold secrets: skip them if unused)
-- The three fact tables are 1:1 on ray_id. The SDK runs one table per data flow (one sink.ddl and one `table = ...`),
-- so each CREATE TABLE below is its own data flow reading the same S3 files with its own field mapping.
-- ---------------------------------------------------------------------------------------------------------------

-- 2. security table
CREATE TABLE IF NOT EXISTS cf_request_security (
    ray_id VARCHAR,                            -- RayID
    edge_start_timestamp TIMESTAMPTZ,          -- EdgeStartTimestamp
    security_level VARCHAR,                    -- SecurityLevel
    security_actions VARCHAR,                  -- SecurityActions (JSON array as text)
    security_rule_id VARCHAR,                  -- SecurityRuleID
    security_rule_ids VARCHAR,                 -- SecurityRuleIDs (JSON array as text)
    security_rule_description VARCHAR,         -- SecurityRuleDescription
    security_sources VARCHAR,                  -- SecuritySources (JSON array as text)
    firewall_matches_actions VARCHAR,          -- FirewallMatchesActions (JSON array as text)
    firewall_matches_rule_ids VARCHAR,         -- FirewallMatchesRuleIDs (JSON array as text)
    firewall_matches_sources VARCHAR,          -- FirewallMatchesSources (JSON array as text)
    waf_action VARCHAR,                        -- WAFAction
    waf_flags VARCHAR,                         -- WAFFlags
    waf_matched_var VARCHAR,                   -- WAFMatchedVar
    waf_profile VARCHAR,                       -- WAFProfile
    waf_rule_id VARCHAR,                       -- WAFRuleID
    waf_rule_message VARCHAR,                  -- WAFRuleMessage
    waf_attack_score BIGINT,                   -- WAFAttackScore
    waf_rce_attack_score BIGINT,               -- WAFRCEAttackScore
    waf_sqli_attack_score BIGINT,              -- WAFSQLiAttackScore
    waf_xss_attack_score BIGINT,               -- WAFXSSAttackScore
    bot_score BIGINT,                          -- BotScore
    bot_score_src VARCHAR,                     -- BotScoreSrc
    bot_tags VARCHAR,                          -- BotTags (JSON array as text)
    bot_detection_ids VARCHAR,                 -- BotDetectionIDs (JSON array as text)
    leaked_credential_check_result VARCHAR,    -- LeakedCredentialCheckResult
    content_scan_obj_results VARCHAR,          -- ContentScanObjResults (JSON array as text)
    content_scan_obj_types VARCHAR,            -- ContentScanObjTypes (JSON array as text)
    content_scan_obj_sizes VARCHAR             -- ContentScanObjSizes (JSON array as text)
) PARTITIONED BY (day(edge_start_timestamp));

-- 3. detail table
CREATE TABLE IF NOT EXISTS cf_request_detail (
    ray_id VARCHAR,                                    -- RayID
    edge_start_timestamp TIMESTAMPTZ,                  -- EdgeStartTimestamp
    parent_ray_id VARCHAR,                             -- ParentRayID
    zone_id BIGINT,                                    -- ZoneID
    client_request_scheme VARCHAR,                     -- ClientRequestScheme
    client_request_source VARCHAR,                     -- ClientRequestSource
    client_x_requested_with VARCHAR,                   -- ClientXRequestedWith
    edge_response_compression_ratio DOUBLE,            -- EdgeResponseCompressionRatio
    origin_response_header_receive_duration_ms BIGINT, -- OriginResponseHeaderReceiveDurationMs
    origin_request_header_send_duration_ms BIGINT,     -- OriginRequestHeaderSendDurationMs
    origin_dns_response_time_ms BIGINT,                -- OriginDNSResponseTimeMs
    origin_tcp_handshake_duration_ms BIGINT,           -- OriginTCPHandshakeDurationMs
    origin_tls_handshake_duration_ms BIGINT,           -- OriginTLSHandshakeDurationMs
    origin_response_time BIGINT,                       -- OriginResponseTime
    cache_response_bytes BIGINT,                       -- CacheResponseBytes
    cache_tiered_fill BOOLEAN,                         -- CacheTieredFill
    cache_reserve_used BOOLEAN,                        -- CacheReserveUsed
    client_ip_class VARCHAR,                           -- ClientIPClass
    client_src_port BIGINT,                            -- ClientSrcPort
    client_ssl_cipher VARCHAR,                         -- ClientSSLCipher
    client_mtls_auth_cert_fingerprint VARCHAR,         -- ClientMTLSAuthCertFingerprint
    client_mtls_auth_status VARCHAR,                   -- ClientMTLSAuthStatus
    cookies VARCHAR,                                   -- Cookies (JSON object as text; may hold secrets)
    request_headers VARCHAR,                           -- RequestHeaders (JSON object as text; may hold secrets)
    edge_request_host VARCHAR,                         -- EdgeRequestHost
    edge_server_ip VARCHAR,                            -- EdgeServerIP
    edge_pathing_op VARCHAR,                           -- EdgePathingOp
    edge_pathing_src VARCHAR,                          -- EdgePathingSrc
    edge_pathing_status VARCHAR,                       -- EdgePathingStatus
    edge_rate_limit_action VARCHAR,                    -- EdgeRateLimitAction
    edge_rate_limit_id BIGINT,                         -- EdgeRateLimitID
    edge_cf_connecting_o2o BOOLEAN,                    -- EdgeCFConnectingO2O
    smart_route_colo_id BIGINT,                        -- SmartRouteColoID
    upper_tier_colo_id BIGINT,                         -- UpperTierColoID
    origin_ssl_protocol VARCHAR,                       -- OriginSSLProtocol
    origin_response_bytes BIGINT,                      -- OriginResponseBytes
    origin_response_http_expires VARCHAR,              -- OriginResponseHTTPExpires
    origin_response_http_last_modified VARCHAR,        -- OriginResponseHTTPLastModified
    response_headers VARCHAR,                          -- ResponseHeaders (JSON object as text)
    worker_cpu_time BIGINT,                            -- WorkerCPUTime
    worker_wall_time_us BIGINT,                        -- WorkerWallTimeUs
    worker_status VARCHAR,                             -- WorkerStatus
    worker_subrequest BOOLEAN,                         -- WorkerSubrequest
    worker_subrequest_count BIGINT                     -- WorkerSubrequestCount
) PARTITIONED BY (day(edge_start_timestamp));

-- 4. reference table, filled once by hand, not by a data flow (no partition: six rows)
CREATE TABLE IF NOT EXISTS ref_edge_colo (
    edge_colo_id BIGINT,                       -- EdgeColoID
    edge_colo_code VARCHAR,                    -- EdgeColoCode (several ids can share one code)
    city VARCHAR
);
INSERT INTO ref_edge_colo VALUES
    (962,  'SIN', 'Singapore'),
    (1427, 'SIN', 'Singapore'),
    (964,  'SIN', 'Singapore'),
    (786,  'YYZ', 'Toronto'),
    (556,  'AMS', 'Amsterdam'),
    (984,  'LHR', 'London');
