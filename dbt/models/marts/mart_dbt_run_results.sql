{{
  config(
    materialized='view',
    tags=['mart', 'observability']
  )
}}

-- Exposes the run-results log written by the `log_dbt_results` macro
-- (wired in via on-run-end in dbt_project.yml). The underlying table is
-- created lazily by the macro; on a brand-new database the very first
-- `dbt build` will create the table during its on-run-end phase, so this
-- view will resolve on subsequent runs.
--
-- One row per node per invocation. Common queries:
--   - latest invocation:   select * from mart_dbt_run_results
--                          where invocation_id = (select invocation_id
--                                                 from mart_dbt_run_results
--                                                 order by run_started_at desc
--                                                 limit 1);
--   - failures only:       where status in ('error', 'fail', 'runtime error');
--   - slowest models:      order by execution_time_s desc;

select
    invocation_id,
    run_started_at,
    logged_at,
    project_name,
    target_name,
    node_unique_id,
    node_name,
    resource_type,
    materialization,
    schema_name,
    relation_name,
    status,
    case
        when status in ('success', 'pass') then true
        else false
    end                                              as is_success,
    case
        when status in ('error', 'fail', 'runtime error') then true
        else false
    end                                              as is_failure,
    execution_time_s,
    rows_affected,
    failures,
    message
from {{ target.schema }}.dbt_run_results
