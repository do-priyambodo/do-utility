{# DO NOT MODIFY THE FOLLOWING LINE #}
{% extends "_shared/templates/_doc_specific_landing_page.html" %}
{% block pagevariables %}
{% include "application-integration/docs/_shared/_integration_connector_localvars.html" %}
{% include "application-integration/_local_variables.html" %}


{% setvar landing_page_title %}Concepts{% endsetvar %}
<meta name="book_path" value="{{book_path}}" />
<meta name="project_path" value="{{project_path}}" />
<meta name="description" content="Understand how {{product_name_short}} works" />

{% endblock %}

{% block doclinks %}

<p>
This page introduces the various fundamental concepts of {{integration}}.
</p>

<div class="card" id="all-concepts">

  <ul class="card-showcase">

    {% setvar lp_title %}Triggers{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/trigger-overview{% endsetvar %}
    {% setvar lp_desc %}
    Understand triggers and learn about the different triggers available in {{application_integration_name}}.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Tasks{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/task-overview{% endsetvar %}
    {% setvar lp_desc %}
    Understand tasks and learn about the different tasks available in {{application_integration_name}}.
    {% endsetvar %}
    
    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Forks and Joins{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/forks-joins{% endsetvar %}
    {% setvar lp_desc %}
    Learn how to specify the execution strategy of a task or a trigger using forks and joins in the integration editor.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Edge and edge conditions{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/edge-overview{% endsetvar %}
    {% setvar lp_desc %}
    Understand edges and learn how to specify conditions that must be met for control the flow of an integration.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Data Mapping{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/data-mapping-overview{% endsetvar %}
    {% setvar lp_desc %}
    Learn how to perform variable assignments within your integration. Explore the different data mapping functions offered in {{application_integration_name}}.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Integration variables{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/variables-overview{% endsetvar %}
    {% setvar lp_desc %}
    Understand and learn how to use variables in the {{integration}} designer.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Integration versions{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/integration-versions{% endsetvar %}
    {% setvar lp_desc %}
    Learn how to develop an integration in collaboration with multiple authors using integration versions.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}
    
    {% setvar lp_title %}Local logging{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/local-logging{% endsetvar %}
    {% setvar lp_desc %}
    Understand local logging for your integration.
    {% endsetvar %}
    {% include "_shared/templates/_landing_page_card.html" %}


  </ul>
</div>

{% endblock %}
