{# ---------------------------------------------------------------------------
  log_dbt_results
  ---------------
  Persists one row per node executed in the current invocation
  (models, tests, snapshots, seeds) into a dedicated table so we can build a
  mart on top of it and query history from the LLM frontend / dashboards.

  Wired in via `on-run-end` in dbt_project.yml. dbt exposes the `results`
  collection inside on-run-* hooks — see
  https://docs.getdbt.com/reference/dbt-jinja-functions/on-run-end-context

  Behaviour:
    - First invocation creates {{ target.schema }}.dbt_run_results (idempotent).
    - Each invocation appends rows tagged with `invocation_id` so a single run
      can be reconstructed by filtering on it.
    - Skipped during `dbt parse` / `dbt compile` (results is empty / undefined).
--------------------------------------------------------------------------- #}

{% macro log_dbt_results() %}
  {# Avoid running during parse/compile or when nothing executed. #}
  {% if not execute %}
    {% do return('') %}
  {% endif %}
  {% if results is not defined or results | length == 0 %}
    {% do return('') %}
  {% endif %}

  {% set log_relation = api.Relation.create(
      database=target.database,
      schema=target.schema,
      identifier='dbt_run_results'
  ) %}

  {# Create table if it doesn't exist yet. Kept in the same schema as marts so
     downstream models can `ref()`-free select from it via {{ source() }} or a
     direct fully-qualified reference. Columns chosen to match the dbt
     RunResult / Result API surface. #}
  {% set create_sql %}
    create table if not exists {{ log_relation }} (
      invocation_id      text,
      run_started_at     timestamptz,
      logged_at          timestamptz,
      project_name       text,
      target_name        text,
      node_unique_id     text,
      node_name          text,
      resource_type      text,
      materialization    text,
      schema_name        text,
      relation_name      text,
      status             text,
      execution_time_s   double precision,
      rows_affected      bigint,
      failures           bigint,
      message            text
    )
  {% endset %}
  {% do run_query(create_sql) %}

  {# Build a single multi-row INSERT. Strings are escaped by replacing
     single quotes; numerics fall back to NULL when missing. #}
  {% set rows = [] %}
  {% for res in results %}
    {% set node = res.node %}
    {% set adapter_response = res.adapter_response or {} %}

    {% set message = (res.message or '') | string %}
    {% set message_escaped = message.replace("'", "''") %}

    {% set node_name = (node.name if node else '') | string %}
    {% set unique_id = (node.unique_id if node else '') | string %}
    {% set resource_type = (node.resource_type if node else '') | string %}
    {% set materialization = (node.config.materialized if node and node.config else '') | string %}
    {% set schema_name = (node.schema if node else '') | string %}
    {% set relation_name = (node.alias if node else '') | string %}

    {% set rows_affected = adapter_response.get('rows_affected') if adapter_response else none %}
    {% set failures_val = res.failures if res.failures is not none else 0 %}

    {% set row %}
      (
        '{{ invocation_id }}',
        '{{ run_started_at }}'::timestamptz,
        now(),
        '{{ project_name }}',
        '{{ target.name }}',
        '{{ unique_id }}',
        '{{ node_name }}',
        '{{ resource_type }}',
        '{{ materialization }}',
        '{{ schema_name }}',
        '{{ relation_name }}',
        '{{ res.status }}',
        {{ res.execution_time if res.execution_time is not none else 'null' }},
        {{ rows_affected if rows_affected is not none else 'null' }},
        {{ failures_val }},
        '{{ message_escaped }}'
      )
    {% endset %}
    {% do rows.append(row) %}
  {% endfor %}

  {% if rows | length > 0 %}
    {% set insert_sql %}
      insert into {{ log_relation }} (
        invocation_id, run_started_at, logged_at, project_name, target_name,
        node_unique_id, node_name, resource_type, materialization,
        schema_name, relation_name, status, execution_time_s,
        rows_affected, failures, message
      )
      values
      {{ rows | join(',\n') }}
    {% endset %}
    {% do run_query(insert_sql) %}
    {% do log("[log_dbt_results] persisted " ~ (rows | length) ~ " result row(s) to " ~ log_relation, info=true) %}
  {% endif %}
{% endmacro %}
