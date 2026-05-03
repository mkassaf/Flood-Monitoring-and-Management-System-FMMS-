/*
 * FMMS — Flood Monitoring and Management System
 * Structurizr DSL workspace
 *
 * Render with structurizr-cli:
 *   docker run --rm -v "$PWD":/usr/local/structurizr structurizr/cli \
 *     export -workspace workspace.dsl -format plantuml/c4plantuml
 * Or upload to https://structurizr.com/dsl
 *
 * Source of truth for: System Context, Container, Deployment views.
 * Component-level decomposition is described in architecture.md (textual)
 * because it changes too often to be worth diagramming in Phase 1.
 */

workspace "FMMS" "Flood Monitoring and Management System" {

    !identifiers hierarchical

    model {

        // ──────────────────────────────────────────────────────────
        // Actors
        // ──────────────────────────────────────────────────────────
        areaManager     = person "Area Manager"     "Monitors and manages a single geographic zone"
        cityManager     = person "City Manager"     "Aggregated multi-zone view across one city"
        regionalManager = person "Regional Manager" "Aggregated multi-city view across one region"
        sysadmin        = person "System Operator"  "Operates and maintains the FMMS platform"

        // ──────────────────────────────────────────────────────────
        // External systems
        // ──────────────────────────────────────────────────────────
        sensors = softwareSystem "Sensor Fleet" {
            description "Up to 150,000 environmental sensors deployed in flood-prone areas. Measure water level, river flow velocity, cumulative rainfall, soil saturation, wind speed and direction, plus operational status."
            tags "External"
        }

        notificationGateway = softwareSystem "Notification Channels" {
            description "Out-of-band notification providers (SMS, email, push). Out of PoC scope; modeled to show extensibility surface."
            tags "External" "Future"
        }

        // ──────────────────────────────────────────────────────────
        // The system under design
        // ──────────────────────────────────────────────────────────
        fmms = softwareSystem "FMMS" "Flood Monitoring and Management System" {

            // Edge / ingestion tier
            mqttBroker = container "MQTT Broker" {
                description "Terminates MQTT/TLS sensor connections. Per-sensor topics; QoS 1; persistent session for adaptive frequency state."
                technology "Eclipse Mosquitto (clustered)"
                tags "Broker"
            }
            ingestionGateway = container "Ingestion Gateway" {
                description "Bridges MQTT to Kafka. Validates schema, verifies sensor identity, stamps server-side ingestion time, partitions by area_id."
                technology "Python / asyncio / paho-mqtt / aiokafka"
            }

            // Streaming backbone
            kafka = container "Event Backbone" {
                description "Topics: telemetry.{area_id}, alerts.priority, alerts.threshold, alerts.malfunction, sensor-status. Replication factor 3. Retention 7d hot."
                technology "Apache Kafka (Redpanda alternative — see ADR-003)"
                tags "Broker"
            }

            // Processing tier
            telemetryService = container "Telemetry Service" {
                description "Consumes telemetry.* (group: telemetry-writer). Batched inserts to TimescaleDB hypertable. Updates Redis hot state per sensor."
                technology "Python / aiokafka / asyncpg"
            }
            ruleEngine = container "Rule Engine" {
                description "Stream processor. Evaluates per-parameter thresholds (FR-06), holds area-level redundancy state for malfunction prioritization (FR-07/08), emits classified alerts."
                technology "Faust (Python). Flink alternative — see ADR-005."
            }
            alertService = container "Alert Service" {
                description "Dedup, prioritize, route alerts by manager scope. Persist for audit. Plugin port for out-of-band notification channels (modifiability — NFR-09)."
                technology "Python / FastAPI"
            }

            // Domain services
            geoService = container "Geo Service" {
                description "Areas, sensors, sensor-to-area binding, area-to-manager assignment, threshold configuration (FR-17/18)."
                technology "FastAPI"
            }
            authService = container "Auth Service" {
                description "User authentication and JWT issuance. Scopes encode role + geographic jurisdiction. RBAC enforced at dashboard-bff."
                technology "FastAPI + python-jose"
            }

            // Edge for users
            dashboardBff = container "Dashboard BFF" {
                description "Aggregates telemetry + alerts for the UI. Enforces RBAC scope. Pushes real-time updates over WebSocket. See ADR-009."
                technology "FastAPI + WebSockets"
            }
            frontend = container "Frontend SPA" {
                description "Map-based real-time UI with role-conditional views. Three landing views: zone (Area Manager), city, region."
                technology "React + Leaflet"
            }

            // Stores
            tsdb = container "Telemetry Store" {
                description "Hypertable for sensor measurements. 90-day hot retention; continuous aggregates for downsampling. See ADR-004."
                technology "TimescaleDB (PostgreSQL extension)"
                tags "Database"
            }
            opdb = container "Operational Store" {
                description "Areas, sensors, managers, alert audit log, thresholds, user accounts."
                technology "PostgreSQL 16"
                tags "Database"
            }
            cache = container "Hot State Cache" {
                description "Latest reading + status per sensor; recent alert summaries; dashboard-read optimized; redundancy state for rule engine."
                technology "Redis 7 (cluster mode in production)"
                tags "Database"
            }

            // Observability
            metrics = container "Metrics" {
                description "Throughput, consumer lag, P95/P99 latency, J/msg, autoscale events. Validates NFR-01/02/03/07."
                technology "Prometheus + Grafana"
                tags "Observability"
            }
            logsTraces = container "Logs + Traces" {
                description "Structured logs and distributed traces from sensor ingestion through alert delivery."
                technology "Loki + Tempo (or OpenTelemetry Collector)"
                tags "Observability"
            }

            // ──────────────────────────────────────────────────────
            // Internal relationships
            // ──────────────────────────────────────────────────────
            ingestionGateway -> mqttBroker      "Subscribes to sensor topics"                "MQTT 5"
            ingestionGateway -> kafka           "Publishes validated telemetry"              "Kafka protocol"
            ingestionGateway -> opdb            "Resolves sensor identity / area binding"    "PostgreSQL"

            telemetryService -> kafka           "Consumes telemetry.*"                       "Kafka protocol"
            telemetryService -> tsdb            "Batched inserts (1s window)"                "PostgreSQL"
            telemetryService -> cache           "Updates last-known sensor state"            "RESP"

            ruleEngine       -> kafka           "Consumes telemetry.*; produces alerts.*"    "Kafka protocol"
            ruleEngine       -> cache           "Reads/writes area redundancy state"         "RESP"
            ruleEngine       -> opdb            "Reads thresholds and area metadata"         "PostgreSQL"

            alertService     -> kafka           "Consumes alerts.*"                          "Kafka protocol"
            alertService     -> opdb            "Persists alert audit log"                   "PostgreSQL"
            alertService     -> cache           "Pushes alert summaries"                     "RESP"

            dashboardBff     -> cache           "Live state reads + WebSocket fan-out"       "RESP + Pub/Sub"
            dashboardBff     -> opdb            "Historical alerts and metadata"             "PostgreSQL"
            dashboardBff     -> tsdb            "Historical measurement queries"             "PostgreSQL"
            dashboardBff     -> authService     "Validates JWT, refreshes scopes"            "HTTPS"
            dashboardBff     -> geoService      "Resolves user scope to area set"            "HTTPS"

            frontend         -> dashboardBff    "REST + real-time stream"                    "HTTPS / WSS"

            geoService       -> opdb            "Reads/writes geo + threshold config"        "PostgreSQL"
            authService      -> opdb            "Reads user accounts and scopes"             "PostgreSQL"

            // Observability instrumentation (subset shown for clarity)
            ingestionGateway -> metrics         "Exposes /metrics"
            telemetryService -> metrics         "Exposes /metrics"
            ruleEngine       -> metrics         "Exposes /metrics"
            alertService     -> metrics         "Exposes /metrics"
            dashboardBff     -> metrics         "Exposes /metrics"
        }

        // ──────────────────────────────────────────────────────────
        // External-to-system relationships
        // ──────────────────────────────────────────────────────────
        sensors             -> fmms.mqttBroker          "Publishes measurements"     "MQTT over TLS, QoS 1"
        areaManager         -> fmms.frontend            "Monitors own zone"          "HTTPS"
        cityManager         -> fmms.frontend            "Monitors city"              "HTTPS"
        regionalManager     -> fmms.frontend            "Monitors region"            "HTTPS"
        sysadmin            -> fmms.metrics             "Operates the platform"      "HTTPS"
        fmms.alertService   -> notificationGateway      "Out-of-band notifications (Phase 7+)" "Async"

        // ──────────────────────────────────────────────────────────
        // Deployment view — Production (cloud, single region, multi-AZ)
        // ──────────────────────────────────────────────────────────
        deploymentEnvironment "Production" {
            deploymentNode "EU Region (e.g. eu-south-1)" {
                deploymentNode "MQTT AZ-A" {
                    containerInstance fmms.mqttBroker
                }
                deploymentNode "MQTT AZ-B" {
                    containerInstance fmms.mqttBroker
                }
                deploymentNode "Kafka cluster (3 brokers, multi-AZ)" {
                    containerInstance fmms.kafka
                    containerInstance fmms.kafka
                    containerInstance fmms.kafka
                }
                deploymentNode "Kubernetes cluster" {
                    deploymentNode "Stateless pool (autoscaled)" {
                        containerInstance fmms.ingestionGateway
                        containerInstance fmms.telemetryService
                        containerInstance fmms.ruleEngine
                        containerInstance fmms.alertService
                        containerInstance fmms.geoService
                        containerInstance fmms.authService
                        containerInstance fmms.dashboardBff
                    }
                    deploymentNode "Static pool (CDN-fronted)" {
                        containerInstance fmms.frontend
                    }
                }
                deploymentNode "Managed RDBMS (primary + replica)" {
                    containerInstance fmms.opdb
                }
                deploymentNode "Managed TimescaleDB cluster" {
                    containerInstance fmms.tsdb
                }
                deploymentNode "Managed Redis cluster" {
                    containerInstance fmms.cache
                }
                deploymentNode "Observability stack" {
                    containerInstance fmms.metrics
                    containerInstance fmms.logsTraces
                }
            }
        }

        // ──────────────────────────────────────────────────────────
        // Deployment view — PoC (single host, Docker Compose)
        // ──────────────────────────────────────────────────────────
        deploymentEnvironment "PoC" {
            deploymentNode "Developer laptop" {
                deploymentNode "Docker Compose" {
                    containerInstance fmms.mqttBroker
                    containerInstance fmms.kafka
                    containerInstance fmms.ingestionGateway
                    containerInstance fmms.telemetryService
                    containerInstance fmms.ruleEngine
                    containerInstance fmms.alertService
                    containerInstance fmms.geoService
                    containerInstance fmms.authService
                    containerInstance fmms.dashboardBff
                    containerInstance fmms.frontend
                    containerInstance fmms.tsdb
                    containerInstance fmms.opdb
                    containerInstance fmms.cache
                    containerInstance fmms.metrics
                    containerInstance fmms.logsTraces
                }
            }
        }
    }

    // ──────────────────────────────────────────────────────────────
    // Views
    // ──────────────────────────────────────────────────────────────
    views {

        systemContext fmms "Context" {
            include *
            autoLayout
            description "FMMS in its operational context. Sensors push telemetry; managers consume role-tailored views."
        }

        container fmms "Containers" {
            include *
            autoLayout lr
            description "Containers and their primary interactions. Edge tier on the left; processing in the middle; user-facing on the right."
        }

        deployment fmms "Production" "ProductionDeployment" {
            include *
            autoLayout
            description "Single-region multi-AZ cloud deployment. Production scale: up to 150K sensors, 50 concurrent managers."
        }

        deployment fmms "PoC" "PocDeployment" {
            include *
            autoLayout
            description "Single-host Docker Compose deployment for the PoC. Simulates 1,000 sensors."
        }

        styles {
            element "Person" {
                shape Person
                background #08427B
                color #ffffff
            }
            element "Software System" {
                background #1168BD
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Future" {
                opacity 50
                border Dashed
            }
            element "Container" {
                background #438DD5
                color #ffffff
            }
            element "Database" {
                shape Cylinder
                background #2E7D32
                color #ffffff
            }
            element "Broker" {
                shape Pipe
                background #F57C00
                color #000000
            }
            element "Observability" {
                background #7E57C2
                color #ffffff
            }
        }
    }
}
