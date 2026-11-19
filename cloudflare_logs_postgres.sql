-- Cloudflare HTTP request Logpush -> PostgreSQL, multi-table design (3 fact tables + 1 reference table).
-- Built from the 10 sample events: one JSON object per line, 102 fields, one row per request, keyed by RayID.
-- Every one of the 102 source fields lands in exactly one table (ray_id and edge_start_timestamp repeat as keys).
--
-- Tables
--   cf_request_log      what was asked, the outcome, latency, cache, client geo   -> ~90% of queries
--   cf_request_security WAF, bot, firewall decisions and scores                   -> threat and bot analysis
--   cf_request_detail   edge routing, origin timings, TLS, workers, headers       -> deep debugging
--   ref_edge_colo       edge location lookup (snippet: 962, 1427, 964 are all SIN)
-- The three fact tables are 1:1 on ray_id. Each is one data flow reading the same S3 files with its own field mapping.
--
-- Decisions
--   * Real Postgres types: timestamptz, boolean, jsonb for arrays and objects, inet for IPs, integer vs bigint by range
--     (ClientASN and byte counts bigint; statuses, ports, ms and scores integer).
--   * inet columns reject '' : the pipeline must send NULL for an empty OriginIP (cache hits, blocked requests).
--   * PRIMARY KEY (ray_id) makes duplicates visible. A relaunch re-reads S3 and re-sends every row, so the load needs
--     INSERT ... ON CONFLICT DO NOTHING, or a new table name per run. Remove the key if the sink only plain-inserts.
--   * No foreign keys: the three flows load independently, so a child row may arrive before its parent.
--   * client_ip is PII (the source doc says to redact). cookies and the header objects may hold secrets: skip them if unused.
--   * Growth path: at tens of millions of rows, make cf_request_log PARTITION BY RANGE (edge_start_timestamp) by day;
--     the key then becomes (ray_id, edge_start_timestamp).

-- 1. hot table
CREATE TABLE IF NOT EXISTS cf_request_log (
    ray_id text NOT NULL,                                             -- RayID
    edge_start_timestamp timestamptz NOT NULL,                        -- EdgeStartTimestamp
    edge_end_timestamp timestamptz,                                   -- EdgeEndTimestamp
    zone_name text,                                                   -- ZoneName
    client_request_host text,                                         -- ClientRequestHost
    client_request_method text,                                       -- ClientRequestMethod
    client_request_path text,                                         -- ClientRequestPath
    client_request_uri text,                                          -- ClientRequestURI
    client_request_protocol text,                                     -- ClientRequestProtocol
    client_request_referer text,                                      -- ClientRequestReferer
    client_request_user_agent text,                                   -- ClientRequestUserAgent
    client_request_bytes bigint,                                      -- ClientRequestBytes
    edge_response_status integer,                                     -- EdgeResponseStatus
    edge_response_bytes bigint,                                       -- EdgeResponseBytes
    edge_response_body_bytes bigint,                                  -- EdgeResponseBodyBytes
    edge_response_content_type text,                                  -- EdgeResponseContentType
    origin_response_status integer,                                   -- OriginResponseStatus
    security_action text,                                             -- SecurityAction
    edge_time_to_first_byte_ms integer,                               -- EdgeTimeToFirstByteMs
    origin_response_duration_ms integer,                              -- OriginResponseDurationMs
    client_tcp_rtt_ms integer,                                        -- ClientTCPRTTMs
    cache_cache_status text,                                          -- CacheCacheStatus
    cache_response_status integer,                                    -- CacheResponseStatus
    client_asn bigint,                                                -- ClientASN
    client_country text,                                              -- ClientCountry
    client_region_code text,                                          -- ClientRegionCode
    client_device_type text,                                          -- ClientDeviceType
    client_ip inet,                                                   -- ClientIP
    client_ssl_protocol text,                                         -- ClientSSLProtocol
    ja3_hash text,                                                    -- JA3Hash
    edge_colo_id integer,                                             -- EdgeColoID
    edge_colo_code text,                                              -- EdgeColoCode
    origin_ip inet,                                                   -- OriginIP
    PRIMARY KEY (ray_id)
);

-- 2. security table
CREATE TABLE IF NOT EXISTS cf_request_security (
    ray_id text NOT NULL,                                             -- RayID
    edge_start_timestamp timestamptz NOT NULL,                        -- EdgeStartTimestamp
    security_level text,                                              -- SecurityLevel
    security_actions jsonb,                                           -- SecurityActions
    security_rule_id text,                                            -- SecurityRuleID
    security_rule_ids jsonb,                                          -- SecurityRuleIDs
    security_rule_description text,                                   -- SecurityRuleDescription
    security_sources jsonb,                                           -- SecuritySources
    firewall_matches_actions jsonb,                                   -- FirewallMatchesActions
    firewall_matches_rule_ids jsonb,                                  -- FirewallMatchesRuleIDs
    firewall_matches_sources jsonb,                                   -- FirewallMatchesSources
    waf_action text,                                                  -- WAFAction
    waf_flags text,                                                   -- WAFFlags
    waf_matched_var text,                                             -- WAFMatchedVar
    waf_profile text,                                                 -- WAFProfile
    waf_rule_id text,                                                 -- WAFRuleID
    waf_rule_message text,                                            -- WAFRuleMessage
    waf_attack_score integer,                                         -- WAFAttackScore
    waf_rce_attack_score integer,                                     -- WAFRCEAttackScore
    waf_sqli_attack_score integer,                                    -- WAFSQLiAttackScore
    waf_xss_attack_score integer,                                     -- WAFXSSAttackScore
    bot_score integer,                                                -- BotScore
    bot_score_src text,                                               -- BotScoreSrc
    bot_tags jsonb,                                                   -- BotTags
    bot_detection_ids jsonb,                                          -- BotDetectionIDs
    leaked_credential_check_result text,                              -- LeakedCredentialCheckResult
    content_scan_obj_results jsonb,                                   -- ContentScanObjResults
    content_scan_obj_types jsonb,                                     -- ContentScanObjTypes
    content_scan_obj_sizes jsonb,                                     -- ContentScanObjSizes
    PRIMARY KEY (ray_id)
);

-- 3. detail table
CREATE TABLE IF NOT EXISTS cf_request_detail (
    ray_id text NOT NULL,                                             -- RayID
    edge_start_timestamp timestamptz NOT NULL,                        -- EdgeStartTimestamp
    parent_ray_id text,                                               -- ParentRayID
    zone_id bigint,                                                   -- ZoneID
    client_request_scheme text,                                       -- ClientRequestScheme
    client_request_source text,                                       -- ClientRequestSource
    client_x_requested_with text,                                     -- ClientXRequestedWith
    edge_response_compression_ratio double precision,                 -- EdgeResponseCompressionRatio
    origin_response_header_receive_duration_ms integer,               -- OriginResponseHeaderReceiveDurationMs
    origin_request_header_send_duration_ms integer,                   -- OriginRequestHeaderSendDurationMs
    origin_dns_response_time_ms integer,                              -- OriginDNSResponseTimeMs
    origin_tcp_handshake_duration_ms integer,                         -- OriginTCPHandshakeDurationMs
    origin_tls_handshake_duration_ms integer,                         -- OriginTLSHandshakeDurationMs
    origin_response_time bigint,                                      -- OriginResponseTime
    cache_response_bytes bigint,                                      -- CacheResponseBytes
    cache_tiered_fill boolean,                                        -- CacheTieredFill
    cache_reserve_used boolean,                                       -- CacheReserveUsed
    client_ip_class text,                                             -- ClientIPClass
    client_src_port integer,                                          -- ClientSrcPort
    client_ssl_cipher text,                                           -- ClientSSLCipher
    client_mtls_auth_cert_fingerprint text,                           -- ClientMTLSAuthCertFingerprint
    client_mtls_auth_status text,                                     -- ClientMTLSAuthStatus
    cookies jsonb,                                                    -- Cookies
    request_headers jsonb,                                            -- RequestHeaders
    edge_request_host text,                                           -- EdgeRequestHost
    edge_server_ip inet,                                              -- EdgeServerIP
    edge_pathing_op text,                                             -- EdgePathingOp
    edge_pathing_src text,                                            -- EdgePathingSrc
    edge_pathing_status text,                                         -- EdgePathingStatus
    edge_rate_limit_action text,                                      -- EdgeRateLimitAction
    edge_rate_limit_id integer,                                       -- EdgeRateLimitID
    edge_cf_connecting_o2o boolean,                                   -- EdgeCFConnectingO2O
    smart_route_colo_id integer,                                      -- SmartRouteColoID
    upper_tier_colo_id integer,                                       -- UpperTierColoID
    origin_ssl_protocol text,                                         -- OriginSSLProtocol
    origin_response_bytes bigint,                                     -- OriginResponseBytes
    origin_response_http_expires text,                                -- OriginResponseHTTPExpires
    origin_response_http_last_modified text,                          -- OriginResponseHTTPLastModified
    response_headers jsonb,                                           -- ResponseHeaders
    worker_cpu_time bigint,                                           -- WorkerCPUTime
    worker_wall_time_us bigint,                                       -- WorkerWallTimeUs
    worker_status text,                                               -- WorkerStatus
    worker_subrequest boolean,                                        -- WorkerSubrequest
    worker_subrequest_count integer,                                  -- WorkerSubrequestCount
    PRIMARY KEY (ray_id)
);

-- 4. reference table, filled once by hand, not by a data flow
CREATE TABLE IF NOT EXISTS ref_edge_colo (
    edge_colo_id    integer PRIMARY KEY,   -- EdgeColoID
    edge_colo_code  text    NOT NULL,      -- EdgeColoCode (several ids can share one code)
    city            text
);
INSERT INTO ref_edge_colo (edge_colo_id, edge_colo_code, city) VALUES
    (962,  'SIN', 'Singapore'),
    (1427, 'SIN', 'Singapore'),
    (964,  'SIN', 'Singapore'),
    (786,  'YYZ', 'Toronto'),
    (556,  'AMS', 'Amsterdam'),
    (984,  'LHR', 'London')
ON CONFLICT (edge_colo_id) DO NOTHING;

-- Indexes: BRIN is tiny and fast on append-only, time-ordered rows; btree for the usual filters.
CREATE INDEX IF NOT EXISTS idx_cf_req_ts_brin  ON cf_request_log USING brin (edge_start_timestamp);
CREATE INDEX IF NOT EXISTS idx_cf_req_host_ts  ON cf_request_log (client_request_host, edge_start_timestamp);
CREATE INDEX IF NOT EXISTS idx_cf_req_status   ON cf_request_log (edge_response_status, edge_start_timestamp);
CREATE INDEX IF NOT EXISTS idx_cf_sec_ts_brin  ON cf_request_security USING brin (edge_start_timestamp);
CREATE INDEX IF NOT EXISTS idx_cf_sec_action   ON cf_request_security (security_rule_id, edge_start_timestamp);
CREATE INDEX IF NOT EXISTS idx_cf_det_ts_brin  ON cf_request_detail USING brin (edge_start_timestamp);

-- To read the full 102-field event, join the three fact tables on ray_id:
--   FROM cf_request_log r
--   JOIN cf_request_security s ON s.ray_id = r.ray_id
--   JOIN cf_request_detail   d ON d.ray_id = r.ray_id
