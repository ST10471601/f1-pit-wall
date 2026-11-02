{#- Limits an incremental build to the session passed as --vars '{session_key: N}'. -#}
{% macro session_filter() -%}
    {%- if is_incremental() and var('session_key', none) is not none -%}
        where session_key = {{ var('session_key') | int }}
    {%- endif -%}
{%- endmacro %}
